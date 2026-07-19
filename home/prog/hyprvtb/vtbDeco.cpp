#include "vtbDeco.hpp"

#include <hyprland/src/Compositor.hpp>
#include <hyprland/src/desktop/state/FocusState.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/helpers/MiscFunctions.hpp>
#include <hyprland/src/managers/SeatManager.hpp>
#include <hyprland/src/managers/input/InputManager.hpp>
#include <hyprland/src/managers/KeybindManager.hpp>
#include <hyprland/src/render/Renderer.hpp>
#include <hyprland/src/protocols/LayerShell.hpp>
#include <hyprland/src/event/EventBus.hpp>
#include <hyprland/src/render/OpenGL.hpp>

#include <pango/pangocairo.h>
#include <cmath>
#include <format>

#include "globals.hpp"
#include "VtbPassElement.hpp"

using namespace Render::GL;

static CHyprColor configColor(Config::INTEGER color) {
    return CHyprColor{static_cast<uint64_t>(color)};
}

// Fixed interior metrics (logical px), mirroring the old quickshell design:
// two square button cells under the top edge, title filling the rest.
static constexpr int VTB_PAD      = 2; // inset from the bar edge
static constexpr int VTB_CELL_GAP = 2;

static int           cellSize() {
    return g_pGlobalState->config.barWidth->value() - VTB_PAD * 2;
}
static int titleTop() {
    return VTB_PAD + 2 * (cellSize() + VTB_CELL_GAP) + 4;
}

CVtbDeco::CVtbDeco(PHLWINDOW pWindow) : IHyprWindowDecoration(pWindow) {
    m_pWindow = pWindow;

    const auto PMONITOR = pWindow->m_monitor.lock();
    if (PMONITOR)
        PMONITOR->m_scheduledRecalc = true;

    m_pMouseButtonCallback = Event::bus()->m_events.input.mouse.button.listen([&](IPointer::SButtonEvent e, Event::SCallbackInfo& info) { onMouseButton(info, e); });
    m_pMouseMoveCallback   = Event::bus()->m_events.input.mouse.move.listen([&](Vector2D c, Event::SCallbackInfo& info) { onMouseMove(c); });
}

CVtbDeco::~CVtbDeco() {
    std::erase(g_pGlobalState->bars, m_self);
}

SDecorationPositioningInfo CVtbDeco::getPositioningInfo() {
    const auto                 WIDTH   = g_pGlobalState->config.barWidth->value();
    const auto                 ENABLED = g_pGlobalState->config.enabled->value();

    SDecorationPositioningInfo info;
    info.policy   = DECORATION_POSITION_STICKY;
    info.edges    = DECORATION_EDGE_RIGHT;
    // Above the border decoration's priority, so the window border wraps
    // window + bar as a single frame (same trick as hyprbars'
    // bar_precedence_over_border).
    info.priority       = 10005;
    info.reserved       = true;
    info.desiredExtents = {{0, 0}, {ENABLED ? WIDTH : 0, 0}};
    return info;
}

void CVtbDeco::onPositioningReply(const SDecorationPositioningReply& reply) {
    m_bAssignedBox = reply.assignedGeometry;
}

std::string CVtbDeco::getDisplayName() {
    return "Hyprvtb";
}

CBox CVtbDeco::assignedBoxGlobal() {
    if (!validMapped(m_pWindow))
        return {};

    CBox box = m_bAssignedBox;
    box.translate(g_pDecorationPositioner->getEdgeDefinedPoint(DECORATION_EDGE_RIGHT, m_pWindow.lock()));

    const auto PWORKSPACE      = m_pWindow->m_workspace;
    const auto WORKSPACEOFFSET = PWORKSPACE && !m_pWindow->m_pinned ? PWORKSPACE->m_renderOffset->value() : Vector2D();

    return box.translate(WORKSPACEOFFSET);
}

PHLWINDOW CVtbDeco::getOwner() {
    return m_pWindow.lock();
}

void CVtbDeco::draw(PHLMONITOR pMonitor, const float& a) {
    if (!validMapped(m_pWindow) || !g_pGlobalState->config.enabled->value())
        return;

    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW->m_ruleApplicator->decorate().valueOrDefault())
        return;

    auto data = CVtbPassElement::SVtbData{this, a};
    g_pHyprRenderer->m_renderPass.add(makeUnique<CVtbPassElement>(data));
}

// ---- text rendering -------------------------------------------------------

// The title, rendered bottom-to-top: pango draws a single ellipsized line
// into a cairo context rotated -90°, with antialiasing off so the pixel
// font stays crisp. Surface is (lineH x runLen): x = glyph height,
// y = the vertical run the text reads along.
void CVtbDeco::renderTitleTex(int runLenPx, float scale) {
    const auto FONT  = g_pGlobalState->config.font->value();
    const int  SIZE  = std::round(g_pGlobalState->config.fontSize->value() * scale);
    const auto COLOR = configColor(g_pGlobalState->config.textColor->value());
    const int  LINEH = SIZE + 2;

    if (runLenPx < SIZE || m_szLastTitle.empty()) {
        m_pTitleTex = nullptr;
        return;
    }

    auto SURF = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, LINEH, runLenPx);
    auto CR   = cairo_create(SURF);

    cairo_font_options_t* fo = cairo_font_options_create();
    cairo_font_options_set_antialias(fo, CAIRO_ANTIALIAS_NONE);

    cairo_translate(CR, 0, runLenPx);
    cairo_rotate(CR, -M_PI / 2.0);

    PangoLayout* layout = pango_cairo_create_layout(CR);
    pango_cairo_context_set_font_options(pango_layout_get_context(layout), fo);

    PangoFontDescription* fd = pango_font_description_new();
    pango_font_description_set_family(fd, FONT.c_str());
    pango_font_description_set_absolute_size(fd, SIZE * PANGO_SCALE);
    pango_layout_set_font_description(layout, fd);
    pango_layout_set_text(layout, m_szLastTitle.c_str(), -1);
    pango_layout_set_width(layout, runLenPx * PANGO_SCALE);
    pango_layout_set_ellipsize(layout, PANGO_ELLIPSIZE_END);

    cairo_set_source_rgba(CR, COLOR.r, COLOR.g, COLOR.b, COLOR.a);
    cairo_move_to(CR, 0, 0);
    pango_cairo_show_layout(CR, layout);

    pango_font_description_free(fd);
    g_object_unref(layout);
    cairo_font_options_destroy(fo);
    cairo_surface_flush(SURF);

    m_pTitleTex = g_pHyprRenderer->createTexture(SURF);

    cairo_destroy(CR);
    cairo_surface_destroy(SURF);
}

SP<Render::ITexture> CVtbDeco::renderGlyph(const std::string& glyph, float scale) {
    const auto FONT  = g_pGlobalState->config.font->value();
    const int  SIZE  = std::round(g_pGlobalState->config.fontSize->value() * scale);
    const auto COLOR = configColor(g_pGlobalState->config.textColor->value());

    return g_pHyprRenderer->renderText(glyph, COLOR, SIZE, false, FONT, 0);
}

// ---- drawing --------------------------------------------------------------

void CVtbDeco::renderPass(PHLMONITOR pMonitor, const float& a) {
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW)
        return;

    const auto  SCALE   = pMonitor->m_scale;
    const auto  BARW    = g_pGlobalState->config.barWidth->value();
    const bool  FOCUSED = PWINDOW == Desktop::focusState()->window();

    auto        bgColor     = configColor(g_pGlobalState->config.bgColor->value());
    auto        borderColor = configColor(g_pGlobalState->config.buttonBorderColor->value());
    auto        textColor   = configColor(g_pGlobalState->config.textColor->value());
    auto        accentColor = configColor(g_pGlobalState->config.accentColor->value());
    bgColor.a *= a;
    borderColor.a *= a;

    const auto DECOBOX = assignedBoxGlobal();

    CBox       barBox = {DECOBOX.x - pMonitor->m_position.x, DECOBOX.y - pMonitor->m_position.y, DECOBOX.w, DECOBOX.h};
    barBox.translate(PWINDOW->m_floatingOffset).scale(SCALE).round();

    if (barBox.w < 1 || barBox.h < 1)
        return;

    // background
    g_pHyprOpenGL->renderRect(barBox, bgColor, {});

    // local -> monitor-space helper for interior boxes (logical px in)
    auto localBox = [&](double x, double y, double w, double h) {
        return CBox{barBox.x + x * SCALE, barBox.y + y * SCALE, w * SCALE, h * SCALE}.round();
    };

    const int CELL = cellSize();

    // outlined cell helper: 1px outline + bg fill
    auto drawCell = [&](int idx, const CHyprColor& outline) {
        const double y = VTB_PAD + idx * (CELL + VTB_CELL_GAP);
        g_pHyprOpenGL->renderRect(localBox(VTB_PAD, y, CELL, CELL), outline, {});
        g_pHyprOpenGL->renderRect(localBox(VTB_PAD + 1, y + 1, CELL - 2, CELL - 2), bgColor, {});
    };

    // ---- close cell ----
    drawCell(0, borderColor);
    if (!m_pCloseTex || m_fLastScale != SCALE)
        m_pCloseTex = renderGlyph("x", SCALE);
    if (m_pCloseTex && m_pCloseTex->m_texID != 0) {
        const auto TSZ = m_pCloseTex->m_size;
        CBox       gbox = {barBox.x + (VTB_PAD + CELL / 2.0) * SCALE - TSZ.x / 2.0, barBox.y + (VTB_PAD + CELL / 2.0) * SCALE - TSZ.y / 2.0, TSZ.x, TSZ.y};
        g_pHyprOpenGL->renderTexture(m_pCloseTex, gbox.round(), {.a = a});
    }

    // ---- maximize cell ----
    drawCell(1, m_bMaximized ? accentColor : borderColor);
    {
        const double cy  = VTB_PAD + (CELL + VTB_CELL_GAP) + CELL / 2.0;
        const double ind = CELL / 2.0; // indicator square size
        auto         col = m_bMaximized ? accentColor : textColor;
        col.a *= a;
        g_pHyprOpenGL->renderRect(localBox(BARW / 2.0 - ind / 2.0, cy - ind / 2.0, ind, ind), col, {});
        g_pHyprOpenGL->renderRect(localBox(BARW / 2.0 - ind / 2.0 + 1, cy - ind / 2.0 + 1, ind - 2, ind - 2), bgColor, {});
    }

    // ---- title ----
    const int RUNLEN = std::round((DECOBOX.h - titleTop() - VTB_PAD) * SCALE);
    if (m_szLastTitle != PWINDOW->m_title || RUNLEN != m_iLastTitleRun || m_fLastScale != SCALE || !m_pTitleTex) {
        m_szLastTitle  = PWINDOW->m_title;
        m_iLastTitleRun = RUNLEN;
        renderTitleTex(RUNLEN, SCALE);
    }
    m_fLastScale = SCALE;

    if (m_pTitleTex && m_pTitleTex->m_texID != 0) {
        const auto TSZ  = m_pTitleTex->m_size;
        CBox       tbox = {barBox.x + (BARW * SCALE) / 2.0 - TSZ.x / 2.0, barBox.y + titleTop() * SCALE, TSZ.x, TSZ.y};
        g_pHyprOpenGL->renderTexture(m_pTitleTex, tbox.round(), {.a = a});
    }
}

// ---- input ----------------------------------------------------------------

bool CVtbDeco::inputIsValid() {
    if (!g_pGlobalState->config.enabled->value())
        return false;

    if (!m_pWindow->m_workspace || !m_pWindow->m_workspace->isVisible() || !g_pInputManager->m_exclusiveLSes.empty() ||
        (g_pSeatManager->m_seatGrab && !g_pSeatManager->m_seatGrab->accepts(m_pWindow->wlSurface()->resource())))
        return false;

    const auto WINDOWATCURSOR = g_pCompositor->vectorToWindowUnified(g_pInputManager->getMouseCoordsInternal(),
                                                                     Desktop::View::RESERVED_EXTENTS | Desktop::View::INPUT_EXTENTS | Desktop::View::ALLOW_FLOATING);

    auto       focusState = Desktop::focusState();

    if (WINDOWATCURSOR != m_pWindow && m_pWindow != focusState->window())
        return false;

    // don't fight top/overlay layer surfaces (launcher, lock, ...)
    auto     PMONITOR     = focusState->monitor();
    PHLLS    foundSurface = nullptr;
    Vector2D surfaceCoords;

    g_pCompositor->vectorToLayerSurface(g_pInputManager->getMouseCoordsInternal(), &PMONITOR->m_layerSurfaceLayers[ZWLR_LAYER_SHELL_V1_LAYER_TOP], &surfaceCoords, &foundSurface);
    if (foundSurface)
        return false;

    g_pCompositor->vectorToLayerSurface(g_pInputManager->getMouseCoordsInternal(), &PMONITOR->m_layerSurfaceLayers[ZWLR_LAYER_SHELL_V1_LAYER_OVERLAY], &surfaceCoords,
                                        &foundSurface);
    if (foundSurface)
        return false;

    return true;
}

Vector2D CVtbDeco::cursorRelativeToBar() {
    return g_pInputManager->getMouseCoordsInternal() - assignedBoxGlobal().pos();
}

void CVtbDeco::onMouseButton(Event::SCallbackInfo& info, IPointer::SButtonEvent e) {
    if (!inputIsValid())
        return;

    if (e.state != WL_POINTER_BUTTON_STATE_PRESSED) {
        handleUpEvent(info);
        return;
    }

    handleDownEvent(info);
}

void CVtbDeco::onMouseMove(Vector2D coords) {
    if (!m_bDragPending || !validMapped(m_pWindow))
        return;

    m_bDragPending = false;
    g_pKeybindManager->changeMouseBindMode(MBIND_MOVE);
    m_bDraggingThis = true;
}

void CVtbDeco::handleDownEvent(Event::SCallbackInfo& info) {
    const auto PWINDOW = m_pWindow.lock();
    const auto COORDS  = cursorRelativeToBar();
    const auto BOX     = assignedBoxGlobal();

    if (!VECINRECT(COORDS, 0, 0, BOX.w, BOX.h - 1)) {
        if (m_bDraggingThis)
            g_pKeybindManager->m_dispatchers["mouse"]("0movewindow");

        m_bDraggingThis = false;
        m_bDragPending  = false;
        return;
    }

    if (Desktop::focusState()->window() != PWINDOW)
        Desktop::focusState()->fullWindowFocus(PWINDOW, Desktop::FOCUS_REASON_CLICK);

    if (PWINDOW->m_isFloating)
        g_pCompositor->changeWindowZOrder(PWINDOW, true);

    info.cancelled   = true;
    m_bCancelledDown = true;

    const int CELL = cellSize();
    if (VECINRECT(COORDS, VTB_PAD, VTB_PAD, VTB_PAD + CELL, VTB_PAD + CELL)) {
        closeWindow();
        return;
    }
    const int Y1 = VTB_PAD + CELL + VTB_CELL_GAP;
    if (VECINRECT(COORDS, VTB_PAD, Y1, VTB_PAD + CELL, Y1 + CELL)) {
        toggleMaximize();
        return;
    }

    // anywhere else on the bar: drag the window
    m_bDragPending = true;
}

void CVtbDeco::handleUpEvent(Event::SCallbackInfo& info) {
    if (m_pWindow.lock() != Desktop::focusState()->window())
        return;

    if (m_bCancelledDown)
        info.cancelled = true;
    m_bCancelledDown = false;

    if (m_bDraggingThis) {
        g_pKeybindManager->changeMouseBindMode(MBIND_INVALID);
        m_bDraggingThis = false;
    }
    m_bDragPending = false;
}

void CVtbDeco::closeWindow() {
    const auto PWINDOW = m_pWindow.lock();
    if (PWINDOW)
        PWINDOW->sendClose();
}

void CVtbDeco::toggleMaximize() {
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW || !PWINDOW->m_isFloating)
        return;

    const auto PMONITOR = PWINDOW->m_monitor.lock();
    if (!PMONITOR)
        return;

    if (m_bMaximized) {
        g_pKeybindManager->m_dispatchers["movewindowpixel"](std::format("exact {} {},activewindow", (int)m_savedGeometry.x, (int)m_savedGeometry.y));
        g_pKeybindManager->m_dispatchers["resizewindowpixel"](std::format("exact {} {},activewindow", (int)m_savedGeometry.w, (int)m_savedGeometry.h));
        m_bMaximized = false;
    } else {
        m_savedGeometry = {PWINDOW->m_realPosition->goal(), PWINDOW->m_realSize->goal()};

        const auto GAP    = g_pGlobalState->config.maximizeGap->value();
        const auto BARW   = g_pGlobalState->config.barWidth->value();
        CBox       usable = PMONITOR->m_reservedArea.apply(CBox{PMONITOR->m_position, PMONITOR->m_size});

        const int  X = usable.x + GAP;
        const int  Y = usable.y + GAP;
        const int  W = usable.w - GAP * 2 - BARW;
        const int  H = usable.h - GAP * 2;

        g_pKeybindManager->m_dispatchers["movewindowpixel"](std::format("exact {} {},activewindow", X, Y));
        g_pKeybindManager->m_dispatchers["resizewindowpixel"](std::format("exact {} {},activewindow", W, H));
        m_bMaximized = true;
    }
    damageEntire();
}

// ---- misc -----------------------------------------------------------------

eDecorationType CVtbDeco::getDecorationType() {
    return DECORATION_CUSTOM;
}

void CVtbDeco::updateWindow(PHLWINDOW pWindow) {
    damageEntire();
}

void CVtbDeco::onConfigReloaded() {
    m_pTitleTex = nullptr;
    m_pCloseTex = nullptr;
    g_pDecorationPositioner->repositionDeco(this);
    damageEntire();
}

void CVtbDeco::damageEntire() {
    g_pHyprRenderer->damageBox(assignedBoxGlobal());
}

eDecorationLayer CVtbDeco::getDecorationLayer() {
    return DECORATION_LAYER_UNDER;
}

uint64_t CVtbDeco::getDecorationFlags() {
    return DECORATION_ALLOWS_MOUSE_INPUT | DECORATION_PART_OF_MAIN_WINDOW;
}

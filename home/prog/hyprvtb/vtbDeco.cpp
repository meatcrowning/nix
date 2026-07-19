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
#include <hyprland/src/config/shared/actions/ConfigActions.hpp>

#include <pango/pangocairo.h>
#include <cmath>
#include <chrono>
#include <format>

#include "globals.hpp"
#include "VtbPassElement.hpp"

using namespace Render::GL;

static CHyprColor configColor(Config::INTEGER color) {
    return CHyprColor{static_cast<uint64_t>(color)};
}

// Fixed interior metrics (logical px): three square button cells under the
// top edge (close, maximize, minimize), title filling the rest.
static constexpr int VTB_PAD      = 2; // inset from the bar edge
static constexpr int VTB_CELL_GAP = 2;
static constexpr int VTB_CELLS    = 3;

static int           cellSize() {
    return g_pGlobalState->config.barWidth->value() - VTB_PAD * 2;
}
static int titleTop() {
    return VTB_PAD + VTB_CELLS * (cellSize() + VTB_CELL_GAP) + 4;
}

static std::string windowAddress(PHLWINDOW w) {
    return std::format("address:0x{:x}", (uintptr_t)w.get());
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
    if (g_pGlobalState)
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

CBox CVtbDeco::memorableGeometry() {
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW)
        return {};

    if (m_bMaximized)
        return m_savedGeometry; // pre-maximize geometry is the one worth remembering

    const auto POS  = m_bMinimized ? m_minSavedPos : PWINDOW->m_realPosition->goal();
    const auto SIZE = PWINDOW->m_realSize->goal();
    return {POS, SIZE};
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

// The title as a COLUMN of upright letters ("claude" -> c/l/a/u/d/e reading
// top-down): every UTF-8 codepoint on its own pango line, centered, with
// antialiasing off so the pixel font stays crisp.
void CVtbDeco::renderTitleTex(int runLenPx, float scale, const CHyprColor& COLOR) {
    const auto FONT  = g_pGlobalState->config.font->value();
    const int  SIZE  = std::round(g_pGlobalState->config.fontSize->value() * scale);
    const int  BARW  = std::round(g_pGlobalState->config.barWidth->value() * scale);

    if (runLenPx < SIZE || m_szLastTitle.empty()) {
        m_pTitleTex = nullptr;
        return;
    }

    // split into codepoints, one per line; truncate to what fits, with a
    // trailing "…" cell when cut short
    const int                maxLines = runLenPx / SIZE;
    std::vector<std::string> cps;
    for (size_t i = 0; i < m_szLastTitle.size();) {
        size_t len = 1;
        while (i + len < m_szLastTitle.size() && (m_szLastTitle[i + len] & 0xC0) == 0x80)
            len++;
        cps.push_back(m_szLastTitle.substr(i, len));
        i += len;
    }
    std::string stacked;
    const bool  truncated = (int)cps.size() > maxLines;
    const int   shown     = truncated ? std::max(0, maxLines - 1) : (int)cps.size();
    for (int i = 0; i < shown; i++) {
        if (i)
            stacked += "\n";
        stacked += cps[i]; // spaces get their own (blank) cell
    }
    if (truncated)
        stacked += "\n…";

    auto SURF = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, BARW, runLenPx);
    auto CR   = cairo_create(SURF);

    cairo_font_options_t* fo = cairo_font_options_create();
    cairo_font_options_set_antialias(fo, CAIRO_ANTIALIAS_NONE);

    PangoLayout* layout = pango_cairo_create_layout(CR);
    pango_cairo_context_set_font_options(pango_layout_get_context(layout), fo);

    PangoFontDescription* fd = pango_font_description_new();
    pango_font_description_set_family(fd, FONT.c_str());
    pango_font_description_set_absolute_size(fd, SIZE * PANGO_SCALE);
    pango_layout_set_font_description(layout, fd);
    pango_layout_set_text(layout, stacked.c_str(), -1);
    pango_layout_set_width(layout, BARW * PANGO_SCALE);
    pango_layout_set_alignment(layout, PANGO_ALIGN_CENTER);
    pango_layout_set_spacing(layout, 0);

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

SP<Render::ITexture> CVtbDeco::glyphTex(const std::string& glyph, const CHyprColor& color, float scale) {
    const auto key = glyph + "|" + std::format("{:08x}", color.getAsHex());
    auto       it  = m_glyphCache.find(key);
    if (it != m_glyphCache.end() && it->second)
        return it->second;

    const auto FONT = g_pGlobalState->config.font->value();
    const int  SIZE = std::round(g_pGlobalState->config.fontSize->value() * scale);

    auto       tex = g_pHyprRenderer->renderText(glyph, color, SIZE, false, FONT, 0);
    m_glyphCache[key] = tex;
    return tex;
}

// ---- drawing --------------------------------------------------------------

void CVtbDeco::renderPass(PHLMONITOR pMonitor, const float& a) {
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW)
        return;

    const auto SCALE   = pMonitor->m_scale;
    const auto BARW    = g_pGlobalState->config.barWidth->value();
    const bool FOCUSED = PWINDOW == Desktop::focusState()->window();

    auto       bgColor       = configColor(g_pGlobalState->config.bgColor->value());
    auto       bgAltColor    = configColor(g_pGlobalState->config.bgAltColor->value());
    auto       borderColor   = configColor(g_pGlobalState->config.buttonBorderColor->value());
    auto       accentColor   = configColor(g_pGlobalState->config.accentColor->value());
    auto       critColor     = configColor(g_pGlobalState->config.critColor->value());
    auto       inactiveColor = configColor(g_pGlobalState->config.inactiveColor->value());
    bgColor.a *= a;
    bgAltColor.a *= a;
    borderColor.a *= a;

    // Buttons + title follow the window's frame: accent (active-border
    // colour) when focused, the inactive-border grey otherwise.
    const auto textColor = FOCUSED ? accentColor : inactiveColor;

    if (m_fLastScale != SCALE || m_lastTextColor != (uint64_t)textColor.getAsHex() || m_bLastFocus != FOCUSED) {
        m_glyphCache.clear();
        m_pTitleTex     = nullptr;
        m_lastTextColor = (uint64_t)textColor.getAsHex();
        m_bLastFocus    = FOCUSED;
    }

    // A maximized window is pinned to its target: anything that moved or
    // resized it (meta+drag, apps repositioning themselves) gets snapped
    // back — maximized means immovable until unmaximized.
    if (m_bMaximized && !m_bMinimized && PWINDOW->m_isFloating) {
        const auto T = maximizeTarget();
        if (PWINDOW->m_realPosition->goal() != T.pos() || PWINDOW->m_realSize->goal() != T.size()) {
            // resize BEFORE move: Actions::resize keeps the window's centre,
            // so a move-then-resize lands off-target
            Config::Actions::resize(T.size(), false, PWINDOW);
            Config::Actions::move(T.pos(), false, PWINDOW);
        }
    }

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

    // one button cell: hover -> bgAlt fill + 2px outline in `hot`, otherwise
    // 1px outline in the plain button-border colour (mirrors the old QS look)
    auto      drawCell = [&](int idx, const CHyprColor& hot, bool active) {
        const double y       = VTB_PAD + idx * (CELL + VTB_CELL_GAP);
        const bool   hovered = m_iHoverCell == idx;
        const int    bw      = (hovered || active) ? 2 : 1;
        auto         oc      = (hovered || active) ? hot : borderColor;
        oc.a *= a;
        g_pHyprOpenGL->renderRect(localBox(VTB_PAD, y, CELL, CELL), oc, {});
        g_pHyprOpenGL->renderRect(localBox(VTB_PAD + bw, y + bw, CELL - 2 * bw, CELL - 2 * bw), (hovered || active) ? bgAltColor : bgColor, {});
    };

    auto drawGlyph = [&](int idx, const std::string& glyph, const CHyprColor& color) {
        auto tex = glyphTex(glyph, color, SCALE);
        if (!tex || tex->m_texID == 0)
            return;
        const auto   TSZ = tex->m_size;
        const double cy  = VTB_PAD + idx * (CELL + VTB_CELL_GAP) + CELL / 2.0;
        CBox         gbox = {barBox.x + (VTB_PAD + CELL / 2.0) * SCALE - TSZ.x / 2.0, barBox.y + cy * SCALE - TSZ.y / 2.0, TSZ.x, TSZ.y};
        g_pHyprOpenGL->renderTexture(tex, gbox.round(), {.a = a});
    };

    // close [x] — crit on hover, like the QS bar had
    drawCell(0, critColor, false);
    drawGlyph(0, "x", m_iHoverCell == 0 ? critColor : textColor);

    // maximize [=] — accent while maximized or hovered
    drawCell(1, accentColor, m_bMaximized);
    drawGlyph(1, "=", (m_bMaximized || m_iHoverCell == 1) ? accentColor : textColor);

    // minimize [>] — slides the window off to the right
    drawCell(2, accentColor, false);
    drawGlyph(2, ">", m_iHoverCell == 2 ? accentColor : textColor);

    // ---- title, a column of upright letters ----
    const int RUNLEN = std::round((DECOBOX.h - titleTop() - VTB_PAD) * SCALE);
    if (m_szLastTitle != PWINDOW->m_title || RUNLEN != m_iLastTitleRun || m_fLastScale != SCALE || !m_pTitleTex) {
        m_szLastTitle   = PWINDOW->m_title;
        m_iLastTitleRun = RUNLEN;
        renderTitleTex(RUNLEN, SCALE, textColor);
    }
    m_fLastScale = SCALE;

    if (m_pTitleTex && m_pTitleTex->m_texID != 0) {
        const auto TSZ  = m_pTitleTex->m_size;
        CBox       tbox = {barBox.x, barBox.y + titleTop() * SCALE, TSZ.x, TSZ.y};
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

int CVtbDeco::cellAt(const Vector2D& c) {
    const int CELL = cellSize();
    for (int i = 0; i < VTB_CELLS; i++) {
        const double y = VTB_PAD + i * (CELL + VTB_CELL_GAP);
        if (VECINRECT(c, VTB_PAD, y, VTB_PAD + CELL, y + CELL))
            return i;
    }
    return -1;
}

void CVtbDeco::onMouseButton(Event::SCallbackInfo& info, IPointer::SButtonEvent e) {
    if (!g_pGlobalState || !inputIsValid())
        return;

    if (e.state != WL_POINTER_BUTTON_STATE_PRESSED) {
        handleUpEvent(info);
        return;
    }

    handleDownEvent(info);
}

void CVtbDeco::onMouseMove(Vector2D coords) {
    if (!g_pGlobalState)
        return;

    // hover feedback on the button cells
    if (validMapped(m_pWindow) && !m_bMinimized) {
        const auto BOX    = assignedBoxGlobal();
        const auto LOCAL  = g_pInputManager->getMouseCoordsInternal() - BOX.pos();
        const int  cell   = VECINRECT(LOCAL, 0, 0, BOX.w, BOX.h) ? cellAt(LOCAL) : -1;
        if (cell != m_iHoverCell) {
            m_iHoverCell = cell;
            damageEntire();
        }
    }

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

    switch (cellAt(COORDS)) {
        case 0: closeWindow(); return;
        case 1: toggleMaximize(); return;
        case 2: minimizeWindow(); return;
        default: break;
    }

    // anywhere else on the bar: drag the window (maximized windows are
    // pinned — no dragging until unmaximized)
    if (!m_bMaximized)
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

// ---- actions --------------------------------------------------------------

void CVtbDeco::closeWindow() {
    const auto PWINDOW = m_pWindow.lock();
    if (PWINDOW)
        PWINDOW->sendClose();
}

// Edge-to-edge across the monitor's usable area (panel exclusive zones
// already subtracted via the reserved area), minus our own bar width on the
// right. maximize_gap (default 0) is an optional breathing margin.
CBox CVtbDeco::maximizeTarget() {
    const auto PWINDOW  = m_pWindow.lock();
    const auto PMONITOR = PWINDOW ? PWINDOW->m_monitor.lock() : nullptr;
    if (!PMONITOR)
        return {};

    const auto GAP    = g_pGlobalState->config.maximizeGap->value();
    const auto BARW   = g_pGlobalState->config.barWidth->value();
    const CBox usable = PMONITOR->m_reservedArea.apply(CBox{PMONITOR->m_position, PMONITOR->m_size});

    return {usable.x + GAP, usable.y + GAP, usable.w - GAP * 2 - BARW, usable.h - GAP * 2};
}

void CVtbDeco::toggleMaximize() {
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW || !PWINDOW->m_isFloating || m_bMinimized)
        return;

    // Config::Actions directly — the legacy movewindowpixel dispatcher's
    // move path proved unreliable on the lua build, and there's no reason
    // to round-trip through string parsing anyway.
    // resize BEFORE move in both directions: Actions::resize keeps the
    // window's centre, so a move-then-resize drifts by half the size delta.
    if (m_bMaximized) {
        m_bMaximized = false;
        Config::Actions::resize(m_savedGeometry.size(), false, PWINDOW);
        Config::Actions::move(m_savedGeometry.pos(), false, PWINDOW);
    } else {
        m_savedGeometry = {PWINDOW->m_realPosition->goal(), PWINDOW->m_realSize->goal()};

        const auto T = maximizeTarget();
        if (T.w < 50 || T.h < 50)
            return;

        m_bMaximized = true;
        Config::Actions::resize(T.size(), false, PWINDOW);
        Config::Actions::move(T.pos(), false, PWINDOW);
    }
    damageEntire();
}

void CVtbDeco::minimizeWindow() {
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW || !PWINDOW->m_isFloating || m_bMinimized)
        return;

    const auto PMONITOR = PWINDOW->m_monitor.lock();
    if (!PMONITOR)
        return;

    m_minSavedPos = PWINDOW->m_realPosition->goal();
    m_bMinimized  = true;
    m_minimizedAt = Time::steadyNow();

    // slide fully past the right edge (Hyprland's move animation is the
    // "slide out" itself)
    const double X = PMONITOR->m_position.x + PMONITOR->m_size.x;
    Config::Actions::move(Vector2D(X, m_minSavedPos.y), false, PWINDOW);

    // hand focus to another window on the workspace; focusing the minimized
    // window again (e.g. via its panel icon) is the restore trigger
    PHLWINDOW next = nullptr;
    for (auto& w : g_pCompositor->m_windows) {
        if (w == PWINDOW || !w->m_isMapped || w->isHidden() || w->m_workspace != PWINDOW->m_workspace)
            continue;
        // skip other minimized windows
        bool minimized = false;
        for (auto& b : g_pGlobalState->bars) {
            if (b && b->getOwner() == w && b->m_bMinimized) {
                minimized = true;
                break;
            }
        }
        if (!minimized)
            next = w;
    }

    if (next)
        Desktop::focusState()->fullWindowFocus(next, Desktop::FOCUS_REASON_CLICK);
    else
        Desktop::focusState()->resetWindowFocus();
}

void CVtbDeco::restoreFromMinimize() {
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW || !m_bMinimized)
        return;

    m_bMinimized = false;
    Config::Actions::move(m_minSavedPos, false, PWINDOW);
    if (PWINDOW->m_isFloating)
        g_pCompositor->changeWindowZOrder(PWINDOW, true);
    damageEntire();
}

void CVtbDeco::onFocusGained() {
    if (!m_bMinimized)
        return;

    // ignore focus churn caused by the minimize itself
    if (std::chrono::duration_cast<std::chrono::milliseconds>(Time::steadyNow() - m_minimizedAt).count() < 300)
        return;

    restoreFromMinimize();
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
    m_glyphCache.clear();
    if (!validMapped(m_pWindow))
        return;
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

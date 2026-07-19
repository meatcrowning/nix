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
#include <hyprland/src/config/ConfigValue.hpp>
#include <hyprland/src/layout/target/Target.hpp>
#include <hyprland/src/devices/IKeyboard.hpp>
#include <hyprland/src/config/supplementary/executor/Executor.hpp>

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

// Fixed interior metrics (logical px): four square button cells under the
// top edge (close, maximize, minimize, pin), title filling the rest.
static constexpr int VTB_PAD      = 2; // inset from the bar edge
static constexpr int VTB_CELL_GAP = 2;
static constexpr int VTB_CELLS    = 4;

static int           cellSize() {
    return g_pGlobalState->config.barWidth->value() - VTB_PAD * 2;
}
static int titleTop() {
    return VTB_PAD + VTB_CELLS * (cellSize() + VTB_CELL_GAP) + 4;
}

// KDE-style resize engine constants. Edge bitmask + the width of the
// right-edge handle strip on the outer side of the titlebar.
enum : uint32_t {
    RS_EDGE_L = 1,
    RS_EDGE_R = 2,
    RS_EDGE_T = 4,
    RS_EDGE_B = 8,
};
static constexpr int    VTB_RESIZE_STRIP = 6;  // px of the bar's outer edge acting as the right handle — the "very edge", like the other sides
static constexpr double VTB_MIN_SIZE     = 50; // fallback when the client reports no min size

// linux/input-event-codes.h values (avoid the include)
static constexpr uint32_t VTB_BTN_LEFT  = 272;
static constexpr uint32_t VTB_BTN_RIGHT = 273;

static bool superHeld() {
    const auto KB = g_pSeatManager->m_keyboard.lock();
    return KB && (KB->getModifiers() & (1 << 6)); // bit 6 = LOGO/SUPER (modmask 64)
}

// Vista system sounds (user's set in ~/.local/share/sounds/vista — see
// quickshell/Sounds.qml for the full event map). The executor is
// shell-interpreted (config exec_cmd relies on $HOME the same way).
void vtbPlaySound(const char* file) {
    Config::Supplementary::executor()->spawn(std::string("pw-play \"$HOME/.local/share/sounds/vista/") + file + "\" 2>/dev/null");
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

    // pin [>>] — Hyprland pin: keeps the window on top and on every
    // workspace. Lit accent while pinned, like maximize while maximized.
    const bool PINNED = PWINDOW->m_pinned;
    drawCell(3, accentColor, PINNED);
    drawGlyph(3, ">>", (PINNED || m_iHoverCell == 3) ? accentColor : textColor);

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

// ---- KDE-style resize engine ----------------------------------------------
//
// Hyprland's native resize (border grab or the resizewindow dispatcher,
// DragController.cpp) picks a corner purely by which QUADRANT of the window
// the drag started in — grabbing the middle of one side still moves two
// edges, even though the border cursor icon (InputManager's
// setBorderIconDirection) correctly shows a single-edge arrow there. This
// engine does what the icon promises: side handles move one edge, corner
// zones move the two edges meeting there. Floating windows only; tiled and
// bar-less windows (scratchpad) fall through to the native behavior.

// The visual frame: window + our bar (they're wrapped by one border).
static CBox frameBox(PHLWINDOW w) {
    CBox box = {w->m_realPosition->value(), w->m_realSize->value()};
    if (g_pGlobalState->config.enabled->value())
        box.w += g_pGlobalState->config.barWidth->value();
    return box;
}

// Border grab (plain LMB): mirrors the zone math of Hyprland's border icon
// (CORNER = rounding + border + 10; rounding is 0 here) over the frame,
// extended outward by the same grab halo native resize uses. Inside the
// frame only the bar's outer strip is a handle (the client area isn't).
uint32_t CVtbDeco::borderResizeZone(const Vector2D& M) {
    static auto PRESIZEONBORDER = CConfigValue<Config::INTEGER>("general:resize_on_border");
    static auto PEXTENDGRAB     = CConfigValue<Config::INTEGER>("general:extend_border_grab_area");
    if (!*PRESIZEONBORDER)
        return 0;

    const auto   PWINDOW = m_pWindow.lock();
    const CBox   FRAME   = frameBox(PWINDOW);
    const double GRAB    = PWINDOW->getRealBorderSize() + *PEXTENDGRAB;
    const double CORNERZ = PWINDOW->getRealBorderSize() + 10;

    const CBox   HALO = {FRAME.x - GRAB, FRAME.y - GRAB, FRAME.w + 2 * GRAB, FRAME.h + 2 * GRAB};
    if (!HALO.containsPoint(M))
        return 0;

    // corner-leeway hints, same thresholds as the border icon
    uint32_t hintH = 0, hintV = 0;
    if (M.x < FRAME.x + CORNERZ)
        hintH = RS_EDGE_L;
    else if (M.x > FRAME.x + FRAME.w - CORNERZ)
        hintH = RS_EDGE_R;
    if (M.y < FRAME.y + CORNERZ)
        hintV = RS_EDGE_T;
    else if (M.y > FRAME.y + FRAME.h - CORNERZ)
        hintV = RS_EDGE_B;

    if (!FRAME.containsPoint(M)) {
        // in the halo: which side(s) is the cursor actually past?
        uint32_t edges = 0;
        if (M.x < FRAME.x)
            edges |= RS_EDGE_L;
        else if (M.x > FRAME.x + FRAME.w)
            edges |= RS_EDGE_R;
        if (M.y < FRAME.y)
            edges |= RS_EDGE_T;
        else if (M.y > FRAME.y + FRAME.h)
            edges |= RS_EDGE_B;
        // past one side but within the corner zone of the other axis -> corner
        if (edges == RS_EDGE_L || edges == RS_EDGE_R)
            edges |= hintV;
        else if (edges == RS_EDGE_T || edges == RS_EDGE_B)
            edges |= hintH;
        return edges;
    }

    // inside the frame: only the bar's outermost strip acts as the right
    // handle (button cells take priority — the caller checks them first via
    // the normal bar path, but be defensive here too)
    const auto BARBOX = assignedBoxGlobal();
    const auto LOCAL  = M - BARBOX.pos();
    if (VECINRECT(LOCAL, 0, 0, BARBOX.w, BARBOX.h) && cellAt(LOCAL) == -1 && LOCAL.x > BARBOX.w - VTB_RESIZE_STRIP)
        return RS_EDGE_R | hintV;

    return 0;
}

// Meta+RMB grab anywhere in the frame: KWin-style 3x3 zones. Outer ring maps
// to the 8 handles; the centre cell falls back to the nearest corner.
uint32_t CVtbDeco::interiorResizeZone(const Vector2D& M) {
    const auto PWINDOW = m_pWindow.lock();
    const CBox FRAME   = frameBox(PWINDOW);
    if (!FRAME.containsPoint(M) || FRAME.w < 1 || FRAME.h < 1)
        return 0;

    const int col = std::clamp((int)((M.x - FRAME.x) / (FRAME.w / 3.0)), 0, 2);
    const int row = std::clamp((int)((M.y - FRAME.y) / (FRAME.h / 3.0)), 0, 2);

    uint32_t  edges = 0;
    if (col == 0)
        edges |= RS_EDGE_L;
    else if (col == 2)
        edges |= RS_EDGE_R;
    if (row == 0)
        edges |= RS_EDGE_T;
    else if (row == 2)
        edges |= RS_EDGE_B;

    if (!edges) { // centre cell: nearest corner
        edges |= (M.x < FRAME.x + FRAME.w / 2.0) ? RS_EDGE_L : RS_EDGE_R;
        edges |= (M.y < FRAME.y + FRAME.h / 2.0) ? RS_EDGE_T : RS_EDGE_B;
    }
    return edges;
}

bool CVtbDeco::tryStartEdgeResize(Event::SCallbackInfo& info, const IPointer::SButtonEvent& e) {
    const auto PWINDOW = m_pWindow.lock();
    if (!validMapped(m_pWindow) || !PWINDOW->m_isFloating || PWINDOW->isFullscreen() || m_bMinimized || m_bMaximized)
        return false;

    const auto MOUSE = g_pInputManager->getMouseCoordsInternal();
    uint32_t   edges = 0;

    if (e.button == VTB_BTN_RIGHT && superHeld())
        edges = interiorResizeZone(MOUSE);
    else if (e.button == VTB_BTN_LEFT)
        edges = borderResizeZone(MOUSE);

    if (!edges)
        return false;

    if (Desktop::focusState()->window() != PWINDOW)
        Desktop::focusState()->fullWindowFocus(PWINDOW, Desktop::FOCUS_REASON_CLICK);
    g_pCompositor->changeWindowZOrder(PWINDOW, true);

    m_bEdgeResizing  = true;
    m_resizeEdges    = edges;
    m_resStartMouse  = MOUSE;
    m_resStartBox    = {PWINDOW->m_realPosition->goal(), PWINDOW->m_realSize->goal()};
    info.cancelled   = true; // keep native (quadrant-corner) border resize out of it
    m_bCancelledDown = true;
    return true;
}

// Same application path as Hyprland's own DragController: clamp the size,
// compensate the position for left/top handles, then push it through the
// layout target (setPositionGlobal + warpPositionSize — instant, no
// animation rubber-banding).
void CVtbDeco::updateEdgeResize() {
    const auto PWINDOW = m_pWindow.lock();
    if (!validMapped(m_pWindow)) {
        endEdgeResize();
        return;
    }

    const auto TARGET = PWINDOW->layoutTarget();
    if (!TARGET) {
        endEdgeResize();
        return;
    }

    const auto DELTA   = g_pInputManager->getMouseCoordsInternal() - m_resStartMouse;

    Vector2D   newSize = m_resStartBox.size();
    if (m_resizeEdges & RS_EDGE_R)
        newSize.x += DELTA.x;
    if (m_resizeEdges & RS_EDGE_L)
        newSize.x -= DELTA.x;
    if (m_resizeEdges & RS_EDGE_B)
        newSize.y += DELTA.y;
    if (m_resizeEdges & RS_EDGE_T)
        newSize.y -= DELTA.y;

    const auto MINSIZE = TARGET->minSize().value_or(Vector2D{VTB_MIN_SIZE, VTB_MIN_SIZE});
    const auto MAXSIZE = TARGET->maxSize().value_or(Vector2D{1e9, 1e9});
    newSize            = newSize.clamp(MINSIZE, MAXSIZE);

    Vector2D newPos = m_resStartBox.pos();
    if (m_resizeEdges & RS_EDGE_L)
        newPos.x += m_resStartBox.w - newSize.x;
    if (m_resizeEdges & RS_EDGE_T)
        newPos.y += m_resStartBox.h - newSize.y;

    CBox wb = {newPos, newSize};
    wb.round();

    TARGET->setPositionGlobal(wb);
    TARGET->warpPositionSize();
    TARGET->damageEntire();
}

void CVtbDeco::endEdgeResize() {
    m_bEdgeResizing  = false;
    m_resizeEdges    = 0;
    m_bCancelledDown = false;
    damageEntire();
}

void CVtbDeco::onMouseButton(Event::SCallbackInfo& info, IPointer::SButtonEvent e) {
    if (!g_pGlobalState)
        return;

    // A running edge-resize must ALWAYS see the release, even if the cursor
    // ended up over another window or a layer surface (inputIsValid would
    // gate it out and leave the resize stuck to the cursor).
    if (e.state != WL_POINTER_BUTTON_STATE_PRESSED && m_bEdgeResizing) {
        endEdgeResize();
        info.cancelled = true;
        return;
    }

    if (!inputIsValid())
        return;

    if (e.state != WL_POINTER_BUTTON_STATE_PRESSED) {
        handleUpEvent(info);
        return;
    }

    if (tryStartEdgeResize(info, e))
        return;

    handleDownEvent(info);
}

void CVtbDeco::onMouseMove(Vector2D coords) {
    if (!g_pGlobalState)
        return;

    if (m_bEdgeResizing) {
        updateEdgeResize();
        return;
    }

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

    // Titlebar buttons are ACTIONS: they get the Vista click (minimize plays
    // its own Minimize.wav instead — one sound per action, never two).
    switch (cellAt(COORDS)) {
        case 0: vtbPlaySound("Windows Navigation Start.wav"); closeWindow(); return;
        case 1: vtbPlaySound("Windows Navigation Start.wav"); toggleMaximize(); return;
        case 2: minimizeWindow(); return;
        case 3: vtbPlaySound("Windows Navigation Start.wav"); togglePin(); return;
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
    // Inset by the border width so the window frame stays visible against
    // the screen edges / panel when maximized.
    const auto BS     = PWINDOW->getRealBorderSize() + GAP;
    const CBox usable = PMONITOR->m_reservedArea.apply(CBox{PMONITOR->m_position, PMONITOR->m_size});

    return {usable.x + BS, usable.y + BS, usable.w - BS * 2 - BARW, usable.h - BS * 2};
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

// Toggle Hyprland's own pin state (floating-only). Routed through the "pin"
// dispatcher rather than flipping m_pinned directly so the workspace/rule
// bookkeeping Hyprland does on pin stays correct — same map used for the
// drag "mouse" dispatch above. The window was just focused in
// handleDownEvent, but pass the address explicitly so we pin THIS window
// regardless of focus timing.
void CVtbDeco::togglePin() {
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW || !PWINDOW->m_isFloating)
        return;

    g_pKeybindManager->m_dispatchers["pin"](windowAddress(PWINDOW));
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
    vtbPlaySound("Windows Minimize.wav");

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

    // Focusing `next` raises it to the top of the floating stack, which would
    // otherwise pop it OVER the minimizing window before its slide-out finishes
    // (the window would appear to teleport instead of sliding away). Re-raise
    // the minimizing window so it stays visually on top for the whole slide;
    // once it's off-screen its z-order no longer matters, and restore re-raises
    // it anyway.
    if (PWINDOW->m_isFloating)
        g_pCompositor->changeWindowZOrder(PWINDOW, true);
}

void CVtbDeco::restoreFromMinimize() {
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW || !m_bMinimized)
        return;

    m_bMinimized = false;
    vtbPlaySound("Windows Restore.wav");
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

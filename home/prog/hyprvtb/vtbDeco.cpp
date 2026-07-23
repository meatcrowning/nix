#include "vtbDeco.hpp"

#include <hyprland/src/Compositor.hpp>
#include <hyprland/src/desktop/state/FocusState.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/helpers/MiscFunctions.hpp>
#include <hyprland/src/managers/SeatManager.hpp>
#include <hyprland/src/managers/input/InputManager.hpp>
#include <hyprland/src/managers/KeybindManager.hpp>
#include <hyprland/src/render/Renderer.hpp>
#include <hyprland/src/render/Framebuffer.hpp>
#include <hyprland/src/protocols/LayerShell.hpp>
#include <hyprland/src/event/EventBus.hpp>
#include <hyprland/src/render/OpenGL.hpp>
#include <hyprland/src/config/shared/actions/ConfigActions.hpp>
#include <hyprland/src/config/ConfigValue.hpp>
#include <hyprland/src/layout/target/Target.hpp>
#include <hyprland/src/devices/IKeyboard.hpp>
#include <hyprland/src/managers/cursor/CursorShapeOverrideController.hpp>
#include <hyprland/src/managers/eventLoop/EventLoopManager.hpp>

#include <pango/pangocairo.h>
#include <xkbcommon/xkbcommon.h>
#include <xkbcommon/xkbcommon-keysyms.h>
#include <cmath>
#include <chrono>
#include <cstdio>
#include <format>

#include "globals.hpp"
#include "VtbPassElement.hpp"

#include <hyprland/src/render/pass/RectPassElement.hpp>

using namespace Render::GL;

static CHyprColor configColor(Config::INTEGER color) {
    return CHyprColor{static_cast<uint64_t>(color)};
}

// Fixed interior metrics (logical px). The bar is DOUBLE-WIDE for every
// window: two columns of bar_width each. The INNER column (adjacent to the
// window content) holds app-registered buttons (vtbIpc) — empty for apps that
// registered none; the OUTER column holds the five system cells (close,
// maximize, minimize, pin, roll-up) with the stacked title under them, exactly
// as the single-wide bar did.
static constexpr int VTB_PAD      = 2; // inset from the bar edge
static constexpr int VTB_CELL_GAP = 2;
static constexpr int VTB_CELLS    = 5;
static constexpr int VTB_SEP_H    = 12;   // spacer height between app-button groups
static constexpr int VTB_APPCELL  = 1000; // m_iHoverCell base for app cells (0-4 = system)

// How long a clicked cell stays inverted as activation feedback.
static constexpr float VTB_FLASH_MS = 220.f;

// Hard (sharp, un-blurred) drop shadow cast to the bottom-left of a normal
// window: a solid rectangle offset this many logical px down and left, behind
// the window.
static constexpr int VTB_SHADOW_SIZE = 24;

// roll-up / roll-out animation timing: the whole two-beat animation runs over
// VTB_ROLL_DURATION seconds, of which the drawer slide takes the first
// VTB_ROLL_SLIDE_FRAC and the "set down" the rest (reversed for roll-out).
static constexpr float VTB_ROLL_DURATION   = 0.26f;
static constexpr float VTB_ROLL_SLIDE_FRAC = 0.55f;

// After a roll-out's slide lands, the window is un-hidden but kept covered by
// its (still-drawn) snapshot for this long, so the client — QtWebEngine (surfer)
// presents black on the first frame after its surface un-hides — has time to
// repaint into its buffer before the snapshot is dropped. Without the hold that
// black first frame showed as the whole window flashing once the unroll landed.
static constexpr float VTB_ROLL_REVEAL_HOLD = 0.09f;

// The lone-bar fade at the tail of a window-close animation (after the roll-up).
static constexpr float VTB_FADE_DURATION = 0.16f;

static float rollRemap(float x, float a, float b) {
    return std::clamp((x - a) / (b - a), 0.f, 1.f);
}
static float rollEaseOutCubic(float t) {
    return 1.f - std::pow(1.f - t, 3.f);
}
static float rollEaseInOut(float t) {
    return t < 0.5f ? 4.f * t * t * t : 1.f - std::pow(-2.f * t + 2.f, 3.f) / 2.f;
}

// One column's width (the bar_width config value) and the full double-wide
// bar. The system column starts at colW() in bar-local coordinates.
static int colW() {
    return g_pGlobalState->config.barWidth->value();
}
static int totalBarW() {
    return colW() * 2;
}
static int           cellSize() {
    return colW() - VTB_PAD * 2;
}
static int titleTop() {
    return VTB_PAD + VTB_CELLS * (cellSize() + VTB_CELL_GAP) + 4;
}

// The two button columns (inner app column, then outer system column) are laid
// out as ONE grid centered in the double-wide bar, with the gap BETWEEN the
// columns equal to the gap between rows (VTB_CELL_GAP) and matching left/right
// margins. Bar-local logical x of each column's cells:
static int gridLeftMargin() {
    return (totalBarW() - (2 * cellSize() + VTB_CELL_GAP)) / 2;
}
static int    innerColX() { return gridLeftMargin(); }
static int    sysColX() { return gridLeftMargin() + cellSize() + VTB_CELL_GAP; }
// The stacked title / footer are colW-wide textures centered on their column.
static double titleTexX() { return sysColX() + cellSize() / 2.0 - colW() / 2.0; }
static double footerTexX() { return innerColX() + cellSize() / 2.0 - colW() / 2.0; }

// Walk the app-button column's layout: calls cb(index, y) for EVERY entry
// (cells and separators alike — the callback checks isSep()). Single source of
// truth for drawing and hit-testing. Two groups: normal buttons stack from the
// top down; buttons flagged `bottom` stack anchored to the bottom of the column
// (the settings button), never overlapping the top group. `contentH` is the
// bar's logical height.
template <typename F>
static void walkAppLayout(const std::vector<SVtbAppButton>& btns, double contentH, F&& cb) {
    const int  CELL = cellSize();
    const auto adv  = [&](const SVtbAppButton& b) { return b.isSep() ? (VTB_SEP_H + VTB_CELL_GAP) : (CELL + VTB_CELL_GAP); };

    double y = VTB_PAD; // top group
    for (size_t i = 0; i < btns.size(); i++) {
        if (btns[i].bottom)
            continue;
        cb(i, y);
        y += adv(btns[i]);
    }

    double bh = 0; // bottom group's total height
    for (size_t i = 0; i < btns.size(); i++)
        if (btns[i].bottom)
            bh += adv(btns[i]);

    double by = std::max(y, contentH - VTB_PAD - bh); // from the bottom up, but never into the top group
    for (size_t i = 0; i < btns.size(); i++) {
        if (!btns[i].bottom)
            continue;
        cb(i, by);
        by += adv(btns[i]);
    }
}

// Total logical height of the bottom-anchored button group (0 if none) — used
// to keep the footer above it.
static double bottomGroupH(const std::vector<SVtbAppButton>& btns) {
    double bh = 0;
    for (const auto& b : btns)
        if (b.bottom)
            bh += b.isSep() ? (VTB_SEP_H + VTB_CELL_GAP) : (cellSize() + VTB_CELL_GAP);
    return bh;
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
    m_pMouseAxisCallback   = Event::bus()->m_events.input.mouse.axis.listen([&](IPointer::SAxisEvent e, Event::SCallbackInfo& info) { onMouseAxis(info, e); });
    m_pKeyboardKeyCallback = Event::bus()->m_events.input.keyboard.key.listen([&](IKeyboard::SKeyEvent e, Event::SCallbackInfo& info) { onKeyboardKey(info, e); });
}

// Codepoint-boundary walk over a UTF-8 buffer: previous / next boundary byte
// offset from `pos` (used by the title editor's cursor movement / deletes).
static size_t prevCp(const std::string& s, size_t pos) {
    if (pos == 0)
        return 0;
    size_t p = pos - 1;
    while (p > 0 && (static_cast<unsigned char>(s[p]) & 0xC0) == 0x80)
        p--;
    return p;
}
static size_t nextCp(const std::string& s, size_t pos) {
    if (pos >= s.size())
        return s.size();
    size_t p = pos + 1;
    while (p < s.size() && (static_cast<unsigned char>(s[p]) & 0xC0) == 0x80)
        p++;
    return p;
}
static int countCp(const std::string& s, size_t byteLen) {
    int n = 0;
    for (size_t i = 0; i < byteLen && i < s.size();) {
        i = nextCp(s, i);
        n++;
    }
    return n;
}

CVtbDeco::~CVtbDeco() {
    if (m_bCursorOverridden)
        Cursor::overrideController->unsetOverride(Cursor::CURSOR_OVERRIDE_WINDOW_EDGE);
    if (g_pGlobalState)
        std::erase(g_pGlobalState->bars, m_self);
}

SDecorationPositioningInfo CVtbDeco::getPositioningInfo() {
    const auto                 ENABLED = g_pGlobalState->config.enabled->value();

    SDecorationPositioningInfo info;
    info.policy   = DECORATION_POSITION_STICKY;
    info.edges    = DECORATION_EDGE_RIGHT;
    // Above the border decoration's priority, so the window border wraps
    // window + bar as a single frame (same trick as hyprbars'
    // bar_precedence_over_border).
    info.priority       = 10005;
    info.reserved       = true;
    info.desiredExtents = {{0.0, 0.0}, {ENABLED ? (double)totalBarW() : 0.0, 0.0}};
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

    const auto PWINDOW = m_pWindow.lock();
    CBox       box     = m_bAssignedBox;
    box.translate(g_pDecorationPositioner->getEdgeDefinedPoint(DECORATION_EDGE_RIGHT, PWINDOW));

    // Fallback when the positioner hasn't handed us a box yet: right after a
    // roll-out lands the window un-hides and the deco positioner needs a frame
    // to re-run, leaving m_bAssignedBox at 0x0 — so the bar box collapses and
    // renderPass early-returns (barBox.w < 1), which blinked the titlebar out
    // for a frame the instant the animation finished, then back once the
    // positioner caught up. Derive the box straight off the window geometry
    // (content's right edge, totalBarW wide, full height — mirrors frameBox()).
    if (box.w < 1 || box.h < 1) {
        const auto POS = PWINDOW->m_realPosition->value();
        const auto SZ  = PWINDOW->m_realSize->value();
        box            = {POS.x + SZ.x, POS.y, (double)totalBarW(), SZ.y};
    }

    const auto PWORKSPACE      = PWINDOW->m_workspace;
    const auto WORKSPACEOFFSET = PWORKSPACE && !PWINDOW->m_pinned ? PWORKSPACE->m_renderOffset->value() : Vector2D();

    return box.translate(WORKSPACEOFFSET);
}

// While shaded the window is hidden and its geometry is frozen, so the bar is
// drawn/hit-tested against the box captured at shade time; otherwise it tracks
// the live decoration position. The shaded bar sits DROPPED by the current
// set-down fraction (a fully rolled bar rests a shadow-offset lower than the
// raised captured box — that's the "set down" resting state).
CBox CVtbDeco::effectiveBoxGlobal() {
    if (!m_bRolledUp && m_rollAnim == ROLL_NONE)
        return assignedBoxGlobal();
    CBox b = m_rollBox;
    b.y += VTB_SHADOW_SIZE * downTNow();
    return b;
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

    // (a shaded window keeps its real geometry — it's hidden, not resized —
    // so the normal path below already reports the right box)
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

// A string as a COLUMN of upright letters ("claude" -> c/l/a/u/d/e reading
// top-down): every UTF-8 codepoint on its own pango line, centered, with
// antialiasing off so the pixel font stays crisp. One column wide (colW) —
// used for the title (outer column) and the app footer (inner column).
SP<Render::ITexture> CVtbDeco::renderStackedTex(const std::string& text, int runLenPx, float scale, const CHyprColor& COLOR, int* outTextH, int* outLines,
                                                bool ellipsis) {
    const auto FONT  = g_pGlobalState->config.font->value();
    const int  SIZE  = std::round(g_pGlobalState->config.fontSize->value() * scale);
    const int  BARW  = std::round(colW() * scale);

    if (runLenPx < SIZE || text.empty())
        return nullptr;

    // split into codepoints, one per line; truncate to what fits, with a
    // trailing "…" cell when cut short (unless ellipsis is off — the editor
    // stacks the whole buffer and lets pango clip to the surface)
    const int                maxLines = runLenPx / SIZE;
    std::vector<std::string> cps;
    for (size_t i = 0; i < text.size();) {
        size_t len = 1;
        while (i + len < text.size() && (text[i + len] & 0xC0) == 0x80)
            len++;
        cps.push_back(text.substr(i, len));
        i += len;
    }
    std::string stacked;
    const bool  truncated = ellipsis && (int)cps.size() > maxLines;
    const int   shown     = truncated ? std::max(0, maxLines - 1) : (int)cps.size();
    for (int i = 0; i < shown; i++) {
        if (i)
            stacked += "\n";
        stacked += cps[i]; // spaces get their own (blank) cell
    }
    if (truncated)
        stacked += "\n…";
    if (outLines)
        *outLines = shown + (truncated ? 1 : 0);

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

    if (outTextH) {
        int lw = 0, lh = 0;
        pango_layout_get_pixel_size(layout, &lw, &lh);
        *outTextH = lh;
    }

    pango_font_description_free(fd);
    g_object_unref(layout);
    cairo_font_options_destroy(fo);
    cairo_surface_flush(SURF);

    auto tex = g_pHyprRenderer->createTexture(SURF);

    cairo_destroy(CR);
    cairo_surface_destroy(SURF);
    return tex;
}

void CVtbDeco::renderTitleTex(int runLenPx, float scale, const CHyprColor& color) {
    m_pTitleTex = renderStackedTex(m_szLastTitle, runLenPx, scale, color);
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
    const bool FOCUSED = PWINDOW == Desktop::focusState()->window();

    auto       bgColor       = configColor(g_pGlobalState->config.bgColor->value());
    auto       bgAltColor    = configColor(g_pGlobalState->config.bgAltColor->value());
    auto       borderColor   = configColor(g_pGlobalState->config.buttonBorderColor->value());
    auto       accentColor   = configColor(g_pGlobalState->config.accentColor->value());
    auto       critColor     = configColor(g_pGlobalState->config.critColor->value());
    auto       inactiveColor = configColor(g_pGlobalState->config.inactiveColor->value());
    bgColor.a *= a;
    bgAltColor.a *= a;
    // NB: borderColor is NOT pre-multiplied by `a` here — drawCellXY applies `a`
    // to the outline colour itself (so the non-pre-multiplied `hot` case fades
    // right). Pre-multiplying here too made the button outlines fade as a^2,
    // vanishing faster than the bar during the close fade-out.

    // Buttons + title follow the window's frame: accent (active-border
    // colour) when focused, the inactive-border grey otherwise.
    auto textColor = FOCUSED ? accentColor : inactiveColor;

    // During the roll animation the tint crossfades focused<->unfocused in step
    // with the SLIDE (rollSlideT: 0 fully out/focused .. 1 tucked/unfocused),
    // independent of the real focus state (handed away the moment we shaded). Tied
    // to the slide, not the set-down beat, so the bar text comes to focus in step
    // with the window border (drawRollBorder) and the emerging content — the bar
    // used to change tint during the early lift beat, out of sync with everything.
    float      rollSlideT = 0.f, rollDownT = 0.f;
    const bool ROLLANIM   = rollAnimSubProgress(rollSlideT, rollDownT);
    if (ROLLANIM) {
        auto lerp = [](const CHyprColor& x, const CHyprColor& y, float t) {
            return CHyprColor{x.r + (y.r - x.r) * t, x.g + (y.g - x.g) * t, x.b + (y.b - x.b) * t, x.a + (y.a - x.a) * t};
        };
        textColor = lerp(accentColor, inactiveColor, rollSlideT);
    }

    if (m_fLastScale != SCALE || m_lastTextColor != (uint64_t)textColor.getAsHex() || m_bLastFocus != FOCUSED) {
        m_glyphCache.clear();
        m_tooltipCache.clear();
        m_pTitleTex     = nullptr;
        m_pFooterTex    = nullptr;
        m_pEditTex      = nullptr;
        m_szLastFooter.clear();
        m_lastTextColor = (uint64_t)textColor.getAsHex();
        m_bLastFocus    = FOCUSED;
    }

    // The title editor needs the keyboard, so it only lives while focused —
    // clicking away (losing focus) discards the edit.
    if (m_bEditing && !FOCUSED)
        exitEdit(false);

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

    const auto DECOBOX = effectiveBoxGlobal();

    CBox       barBox = {DECOBOX.x - pMonitor->m_position.x, DECOBOX.y - pMonitor->m_position.y, DECOBOX.w, DECOBOX.h};
    barBox.translate(PWINDOW->m_floatingOffset).scale(SCALE).round();

    if (barBox.w < 1 || barBox.h < 1)
        return;

    // roll animation: the drop shadow goes down first, so the opaque bar (and
    // the sliding snapshot, drawn at the end) occlude its centre — only the
    // bottom-left L-overhang shows, collapsing to nothing as the bar sets down.
    if (ROLLANIM)
        drawRollShadow(barBox, SCALE, rollSlideT, rollDownT, a);

    // background
    g_pHyprOpenGL->renderRect(barBox, bgColor, {});

    // local -> monitor-space helper for interior boxes (logical px in)
    auto localBox = [&](double x, double y, double w, double h) {
        return CBox{barBox.x + x * SCALE, barBox.y + y * SCALE, w * SCALE, h * SCALE}.round();
    };

    const int CELL = cellSize();

    // Whether a cell is currently showing its click-activation flash.
    const auto FLASHNOW    = Time::steadyNow();
    auto       cellFlashing = [&](int id) {
        return id >= 0 && m_flashCell == id &&
            std::chrono::duration<float, std::milli>(FLASHNOW - m_flashAt).count() < VTB_FLASH_MS;
    };

    // one button cell at bar-local (x, y): flash -> solid highlight fill (the
    // caller draws the glyph in bg for the inverted look); lit -> bgAlt fill +
    // 2px outline in `hot`; otherwise 1px outline in the plain button-border
    // colour (mirrors the old QS look)
    auto      drawCellXY = [&](double x, double y, const CHyprColor& hot, bool lit, bool flash = false) {
        if (flash) {
            auto fc = hot;
            fc.a *= a;
            g_pHyprOpenGL->renderRect(localBox(x, y, CELL, CELL), fc, {});
            return;
        }
        const int bw = lit ? 2 : 1;
        auto      oc = lit ? hot : borderColor;
        oc.a *= a;
        g_pHyprOpenGL->renderRect(localBox(x, y, CELL, CELL), oc, {});
        g_pHyprOpenGL->renderRect(localBox(x + bw, y + bw, CELL - 2 * bw, CELL - 2 * bw), lit ? bgAltColor : bgColor, {});
    };

    auto drawGlyphXY = [&](double x, double y, const std::string& glyph, const CHyprColor& color) {
        auto tex = glyphTex(glyph, color, SCALE);
        if (!tex || tex->m_texID == 0)
            return;
        const auto TSZ  = tex->m_size;
        CBox       gbox = {barBox.x + (x + CELL / 2.0) * SCALE - TSZ.x / 2.0, barBox.y + (y + CELL / 2.0) * SCALE - TSZ.y / 2.0, TSZ.x, TSZ.y};
        g_pHyprOpenGL->renderTexture(tex, gbox.round(), {.a = a});
    };

    // the five system cells live in the OUTER column. An `active` cell (a held
    // toggle: maximized / pinned / rolled-up) holds the full inverted look —
    // solid accent fill + bg glyph, the same as a click-flash but persistent —
    // so it reads as "stays pressed" until toggled off. Mere hover on a
    // non-active cell keeps the subtler lit outline instead.
    auto drawCell = [&](int idx, const CHyprColor& hot, bool active) {
        const double y = VTB_PAD + idx * (CELL + VTB_CELL_GAP);
        const bool hoverLit = m_iHoverCell == idx && !active;
        drawCellXY(sysColX(), y, hot, hoverLit, cellFlashing(idx) || active);
    };

    auto drawGlyph = [&](int idx, const std::string& glyph, const CHyprColor& color, bool active = false) {
        const bool inverted = cellFlashing(idx) || active;
        drawGlyphXY(sysColX(), VTB_PAD + idx * (CELL + VTB_CELL_GAP), glyph, inverted ? bgColor : color);
    };

    // close [x] — crit on hover, like the QS bar had
    drawCell(0, critColor, false);
    drawGlyph(0, "x", m_iHoverCell == 0 ? critColor : textColor);

    // maximize [=] — inverted while maximized (held), accent while hovered
    drawCell(1, accentColor, m_bMaximized);
    drawGlyph(1, "=", (m_bMaximized || m_iHoverCell == 1) ? accentColor : textColor, m_bMaximized);

    // minimize [>] — slides the window off to the right
    drawCell(2, accentColor, false);
    drawGlyph(2, ">", m_iHoverCell == 2 ? accentColor : textColor);

    // pin [o>] — Hyprland pin: keeps the window on top and on every
    // workspace. Inverted while pinned, like maximize while maximized.
    const bool PINNED = PWINDOW->m_pinned;
    drawCell(3, accentColor, PINNED);
    drawGlyph(3, "o>", (PINNED || m_iHoverCell == 3) ? accentColor : textColor, PINNED);

    // roll-up — windowshade toggle: [>>] hides the window down to just this
    // bar; while shaded it shows [<<] to roll it back. Inverted while shaded.
    drawCell(4, accentColor, m_bRolledUp);
    drawGlyph(4, m_bRolledUp ? "<<" : ">>", (m_bRolledUp || m_iHoverCell == 4) ? accentColor : textColor, m_bRolledUp);

    // ---- title, a column of upright letters (outer column, under the cells) ----
    // In edit mode the same region becomes the address editor: it shows the
    // live edit buffer, a caret (or an inverted block when the whole field is
    // selected), instead of the window title.
    const int    TITLETOP = titleTopEff();
    const int    RUNLEN = std::round((DECOBOX.h - TITLETOP - VTB_PAD) * SCALE);
    const double TITLEX = barBox.x + titleTexX() * SCALE;
    const double TITLEY = barBox.y + TITLETOP * SCALE;

    if (m_bEditing) {
        // auto-scroll to keep the caret on-screen whenever it MOVED (typing /
        // arrows / click) — not on a manual wheel-scroll, which leaves it put.
        if (m_editCursor != m_editLastCaret) {
            m_editLastCaret = m_editCursor;
            ensureEditCaretVisible();
        }

        const size_t selLo  = std::min(m_editSelAnchor, m_editCursor);
        const size_t selHi  = std::max(m_editSelAnchor, m_editCursor);
        const bool   hasSel = selHi > selLo;

        // byte offset of the first visible row (the m_editScrollCp'th codepoint)
        size_t visStart = 0;
        for (int i = 0; i < m_editScrollCp && visStart < m_editBuf.size(); i++)
            visStart = nextCp(m_editBuf, visStart);

        // rows below are relative to the scroll offset; everything is clamped to
        // the visible window so a long URL's selection/text never spills past the
        // bar's bottom edge (which used to run off-window and flicker).
        const int loCp = hasSel ? (countCp(m_editBuf, selLo) - m_editScrollCp) : 0;
        const int hiCp = hasSel ? (countCp(m_editBuf, selHi) - m_editScrollCp) : 0;

        if (!m_pEditTex) {
            int th = 0, lines = 0;
            // render only from the scroll offset; pango clips to the RUNLEN-tall
            // surface, so nothing is drawn below the bar
            const std::string SHOWN = m_editBuf.empty() ? std::string(" ") : m_editBuf.substr(visStart);
            m_pEditTex   = renderStackedTex(SHOWN, RUNLEN, SCALE, textColor, &th, &lines, /*ellipsis=*/false);
            m_iEditLineH = lines > 0 ? th / lines : std::round(g_pGlobalState->config.fontSize->value() * SCALE);
            m_iEditLines = lines;
            // the selected substring (bg colour, drawn over the accent block so
            // those rows invert), clamped to the visible window: it starts at
            // max(selLo, visStart) and its own surface is only as tall as the
            // space left below that row, so it can't spill either.
            m_pEditSelTex = nullptr;
            if (hasSel && m_iEditLineH > 0) {
                const size_t vSelLo    = std::max(selLo, visStart);
                const int    selRow    = std::max(0, loCp);
                const int    selRunLen = std::max(0, RUNLEN - selRow * m_iEditLineH);
                if (selHi > vSelLo && selRunLen >= m_iEditLineH)
                    m_pEditSelTex = renderStackedTex(m_editBuf.substr(vSelLo, selHi - vSelLo), selRunLen, SCALE, bgColor, nullptr, nullptr, /*ellipsis=*/false);
            }
        }

        const int maxRow = m_iEditLineH > 0 ? std::max(0, RUNLEN / m_iEditLineH) : 0;
        if (m_pEditTex && m_pEditTex->m_texID != 0) {
            const auto TSZ = m_pEditTex->m_size;
            if (hasSel && m_iEditLineH > 0) {
                const int blkLo = std::clamp(loCp, 0, maxRow);
                const int blkHi = std::clamp(hiCp, 0, maxRow);
                if (blkHi > blkLo) {
                    CBox block = {TITLEX, TITLEY + blkLo * (double)m_iEditLineH, (double)TSZ.x, (blkHi - blkLo) * (double)m_iEditLineH};
                    g_pHyprOpenGL->renderRect(block.round(), accentColor, {});
                }
            }
            CBox tbox = {TITLEX, TITLEY, TSZ.x, TSZ.y};
            g_pHyprOpenGL->renderTexture(m_pEditTex, tbox.round(), {.a = a});
        }
        if (hasSel && m_pEditSelTex && m_pEditSelTex->m_texID != 0 && m_iEditLineH > 0) {
            const auto TSZ    = m_pEditSelTex->m_size;
            const int  selRow = std::max(0, loCp);
            CBox       sbox   = {TITLEX, TITLEY + selRow * (double)m_iEditLineH, TSZ.x, TSZ.y};
            g_pHyprOpenGL->renderTexture(m_pEditSelTex, sbox.round(), {.a = a});
        }
        // caret: a horizontal bar at the cursor's row (relative to scroll), drawn
        // only when there's no selection and the row is within the visible window.
        if (!hasSel && m_iEditLineH > 0) {
            const long ms       = std::chrono::duration_cast<std::chrono::milliseconds>(Time::steadyNow() - m_editBlinkAt).count();
            const bool blinkOn  = (ms / 500) % 2 == 0;
            const int  caretRow = countCp(m_editBuf, m_editCursor) - m_editScrollCp;
            if (blinkOn && caretRow >= 0 && caretRow <= maxRow) {
                const double cy = TITLEY + caretRow * (double)m_iEditLineH;
                CBox caret = {TITLEX + 2 * SCALE, cy, (double)(cellSize() - 4) * SCALE, std::max(1.0, 2.0 * (double)SCALE)};
                g_pHyprOpenGL->renderRect(caret.round(), accentColor, {});
            }
            damageEntire(); // keep the blink ticking on a still cursor
        }
    } else {
        if (m_szLastTitle != PWINDOW->m_title || RUNLEN != m_iLastTitleRun || m_fLastScale != SCALE || !m_pTitleTex) {
            m_szLastTitle   = PWINDOW->m_title;
            m_iLastTitleRun = RUNLEN;
            renderTitleTex(RUNLEN, SCALE, textColor);
        }

        if (m_pTitleTex && m_pTitleTex->m_texID != 0) {
            const auto TSZ  = m_pTitleTex->m_size;
            CBox       tbox = {TITLEX, TITLEY, TSZ.x, TSZ.y};
            g_pHyprOpenGL->renderTexture(m_pTitleTex, tbox.round(), {.a = a});
        }
    }
    m_fLastScale = SCALE;

    // page-loading spinner: in the slot titleTopEff() reserved (below roll-up,
    // above the address), cycle | \ - / ~8fps while the browser reports loading.
    {
        SVtbAppReg lreg;
        if (VtbIpc::get(appPid(), lreg) && lreg.titleEdit && lreg.loading) {
            static const char* FRAMES[4] = {"|", "\\", "-", "/"};
            const long         ms        = std::chrono::duration_cast<std::chrono::milliseconds>(Time::steadyNow().time_since_epoch()).count();
            drawGlyphXY(sysColX(), titleTop(), FRAMES[(ms / 120) % 4], FOCUSED ? accentColor : inactiveColor);
            damageEntire(); // keep it spinning
        }
    }

    // ---- inner column: app-registered buttons + stacked footer (vtbIpc) ----
    m_lastIpcSerial = VtbIpc::serial.load(std::memory_order_relaxed);
    SVtbAppReg reg;
    if (VtbIpc::get(appPid(), reg)) {
        const double CONTENTH  = DECOBOX.h;
        double       appBottom = VTB_PAD; // bottom of the TOP group (footer stays below it)

        walkAppLayout(reg.buttons, CONTENTH, [&](size_t i, double y) {
            const auto& b = reg.buttons[i];

            // separator ("-"): a thin divider line centred in the gap
            if (b.isSep()) {
                if (y + VTB_SEP_H <= CONTENTH - VTB_PAD) {
                    auto sc = textColor;
                    sc.a *= a;
                    g_pHyprOpenGL->renderRect(localBox(innerColX() + 2, y + VTB_SEP_H / 2.0, cellSize() - 4, 1), sc, {});
                }
                if (!b.bottom)
                    appBottom = std::max(appBottom, y + VTB_SEP_H);
                return;
            }

            if (y + CELL > CONTENTH - VTB_PAD)
                return; // window too short for this cell — clip, don't overlap
            if (!b.bottom)
                appBottom = std::max(appBottom, y + CELL);

            const bool  disabled = b.state == 2;
            const bool  hovered  = m_iHoverCell == (int)(VTB_APPCELL + i);
            const bool  active   = !disabled && b.state == 1;    // held selection
            const bool  hoverLit = !disabled && hovered && !active;
            // lit cells grey to the inactive tone on unfocused windows, like
            // the old in-window strip did (win.fgAccent)
            const auto& litCol   = FOCUSED ? accentColor : inactiveColor;

            // an active (state==1) cell holds the full inverted look — accent
            // fill + bg glyph — persistently, like a click-flash that never
            // reverts, so a selected tab / sort field / show-hidden toggle reads
            // as "held down" until a sibling is picked. Hover on a non-active
            // cell stays the subtler lit outline.
            const bool flashing = cellFlashing(VTB_APPCELL + (int)i);
            const bool inverted = flashing || active;
            drawCellXY(innerColX(), y, litCol, hoverLit, inverted);
            // disabled cells dim to the inactive grey, like filer's 0.4-opacity look
            drawGlyphXY(innerColX(), y, b.label, inverted ? bgColor : (disabled ? inactiveColor : (hoverLit ? litCol : textColor)));
        });

        // footer: short stacked text at the bottom of the inner column (filer's
        // dir-size readout), kept ABOVE any bottom-anchored buttons. Rendered
        // with the same pango path as the title; skipped if too short to fit.
        const double BH     = bottomGroupH(reg.buttons);
        const int    FRUNLEN = std::round((CONTENTH - appBottom - BH - VTB_PAD * 2) * SCALE);
        if (reg.footer != m_szLastFooter || FRUNLEN != m_iLastFooterRun || !m_pFooterTex) {
            m_szLastFooter   = reg.footer;
            m_iLastFooterRun = FRUNLEN;
            m_iFooterTextH   = 0;
            m_pFooterTex     = renderStackedTex(reg.footer, FRUNLEN, SCALE, textColor, &m_iFooterTextH);
        }
        if (m_pFooterTex && m_pFooterTex->m_texID != 0) {
            // the texture's glyphs start at its top; bottom-anchor using the real
            // pango text height so the readout hugs the bar's bottom edge (above
            // the bottom-anchored group, if any)
            const auto TSZ  = m_pFooterTex->m_size;
            CBox       fbox = {barBox.x + footerTexX() * SCALE, barBox.y + barBox.h - (VTB_PAD + BH) * SCALE - m_iFooterTextH, TSZ.x, TSZ.y};
            g_pHyprOpenGL->renderTexture(m_pFooterTex, fbox.round(), {.a = a});
        }

        // drag-reorder feedback: an accent insertion bar at the target slot and
        // a lifted copy of the dragged button following the cursor's Y.
        if (m_bAppDragging && m_iAppDragTarget >= 0) {
            double tgtY = -1;
            walkAppLayout(reg.buttons, CONTENTH, [&](size_t i, double y) {
                if ((int)i == m_iAppDragTarget)
                    tgtY = y;
            });
            if (tgtY >= 0) {
                auto ac = accentColor;
                ac.a *= a;
                g_pHyprOpenGL->renderRect(localBox(innerColX(), tgtY - VTB_CELL_GAP / 2.0 - 1, CELL, 2), ac, {});
            }
            // lifted cell at the cursor's Y (clamped into the column)
            const auto   MOUSELOCAL = g_pInputManager->getMouseCoordsInternal() - assignedBoxGlobal().pos();
            const double liftY      = std::clamp(MOUSELOCAL.y - CELL / 2.0, (double)VTB_PAD, CONTENTH - VTB_PAD - CELL);
            if (m_iAppPressIdx >= 0 && m_iAppPressIdx < (int)reg.buttons.size()) {
                drawCellXY(innerColX(), liftY, FOCUSED ? accentColor : inactiveColor, true, false);
                drawGlyphXY(innerColX(), liftY, reg.buttons[m_iAppPressIdx].label, FOCUSED ? accentColor : inactiveColor);
            }
            damageEntire();
        }
    }

    // keep repainting while a click-flash plays, then clear it (the cell reverts
    // to its normal look on the frame the flash expires)
    if (m_flashCell != -1) {
        if (cellFlashing(m_flashCell))
            damageEntire();
        else
            m_flashCell = -1;
    }

    // roll animation: the window snapshot sliding into / out of the bar, drawn
    // over the bar's own draws but clipped to the left of the bar column (the
    // drop shadow was already drawn before the background, above).
    if (ROLLANIM)
        drawRollSnapshot(barBox, SCALE, rollSlideT, a);

    // roll animation: the window border, crossfading focused<->unfocused in step
    // with the SLIDE (not the set-down), so unrolling looks like the window
    // "coming to focus" as it emerges and rolling up looks like it dimming as it
    // tucks away. The snapshot is clipped to the bare client rect (no border in
    // it), and the hidden window draws none, so this is the only border shown for
    // the whole animation — it hands off seamlessly to the live window's own
    // (warped-active) border the instant the roll-out lands.
    if (ROLLANIM)
        drawRollBorder(barBox, SCALE, rollSlideT, accentColor, inactiveColor, a);

    // NOTE: the hover tooltip is NOT drawn here — this pass element is an
    // UNDER-layer decoration (drawn before the window surface), and the tooltip
    // overhangs the window to the left, so drawing it here would put it behind
    // the window. It's enqueued separately at RENDER_POST_WINDOWS; see
    // enqueueTooltip / drawTooltipPass.
}

// The collapsing drop shadow of the visible composite (remaining client + bar),
// offset down+left by the current float height; at downT 1 the offset is 0, so
// the bar/snapshot sit flush over it and it vanishes ("set down"). Drawn before
// the bar so only the L-overhang survives the occlusion.
void CVtbDeco::drawRollShadow(const CBox& barBoxDev, float scale, float slideT, float downT, float a) {
    const double shadowOff = VTB_SHADOW_SIZE * (1.f - downT) * scale;
    if (shadowOff <= 0.5)
        return;
    const double clientW  = m_rollWinBox.w * scale;
    const double barRight = barBoxDev.x + barBoxDev.w;
    // left edge of the still-visible content as it tucks right into the bar
    const double visLeft   = barBoxDev.x - clientW * (1.f - slideT);
    CBox         shadowBox = {visLeft - shadowOff, barBoxDev.y + shadowOff, barRight - visLeft, barBoxDev.h};
    CHyprColor   sc        = {0.0, 0.0, 0.0, 0.6 * a};
    g_pHyprOpenGL->renderRect(shadowBox.round(), sc, {});
}

// The window snapshot sliding right into the bar (or back out), clipped at the
// bar's left edge so it disappears behind the bar like a closing drawer. Drawn
// after the bar; the clip keeps it from painting over the bar column.
void CVtbDeco::drawRollSnapshot(const CBox& barBoxDev, float scale, float slideT, float a) {
    if (!m_rollSnapTex || m_rollSnapTex->m_texID == 0 || slideT >= 0.999f)
        return;
    const double clientW = m_rollWinBox.w * scale;
    if (clientW < 1.0)
        return;

    // The snapshot is a MONITOR-sized texture with the window at m_rollSnapOrigin,
    // so we can't just stretch the whole thing into the content box (that shrinks
    // the entire screen into the bar). Instead draw the full texture 1:1, offset so
    // the window's sub-rect lands exactly where the content should be, and clip to
    // the still-visible strip (its sliding left edge to the bar's left edge) so no
    // neighbouring desktop leaks in and the drawer-into-bar occlusion is preserved.
    const double                        contentLeft = barBoxDev.x - clientW * (1.f - slideT);
    CBox                                fullBox     = {contentLeft - m_rollSnapOrigin.x, barBoxDev.y - m_rollSnapOrigin.y,
                                                       m_rollSnapTex->m_size.x, m_rollSnapTex->m_size.y};
    CRegion                             clip        = CBox{contentLeft, barBoxDev.y, barBoxDev.x - contentLeft, barBoxDev.h}.round();
    CHyprOpenGLImpl::STextureRenderData data;
    data.a          = a;
    data.clipRegion = clip;
    g_pHyprOpenGL->renderTexture(m_rollSnapTex, fullBox.round(), data);
}

// The emerging window's border during a roll animation, framing the WHOLE
// visible frame — the sliding content AND the titlebar it's tucked against (the
// window border wraps client + titlebar as one). Colour crossfades
// unfocused->focused with how far the content has slid OUT (revealT: 0 fully
// tucked .. 1 fully out) — independent of the real focus state, which was handed
// away when the window shaded. Ties the fade to the slide so it runs across the
// whole visible motion and lands on the focused tint exactly as the window does.
void CVtbDeco::drawRollBorder(const CBox& barBoxDev, float scale, float slideT, const CHyprColor& focused, const CHyprColor& unfocused, float a) {
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW)
        return;
    const double bs = PWINDOW->getRealBorderSize() * scale;
    if (bs < 1.0)
        return;

    const double clientW = m_rollWinBox.w * scale;
    if (clientW < 1.0)
        return;
    const double cl = barBoxDev.x - clientW * (1.f - slideT); // frame left (content), sliding
    const double cr = barBoxDev.x + barBoxDev.w;              // frame right (titlebar's right edge)
    const double ct = barBoxDev.y;                            // frame top
    const double ch = barBoxDev.h;                            // frame height (== window height)
    const double fw = cr - cl;                                // visible frame width (content + bar)

    const float  revealT = 1.f - slideT; // 0 tucked .. 1 out
    CHyprColor   bc      = {unfocused.r + (focused.r - unfocused.r) * revealT, unfocused.g + (focused.g - unfocused.g) * revealT,
                            unfocused.b + (focused.b - unfocused.b) * revealT, unfocused.a + (focused.a - unfocused.a) * revealT};
    bc.a *= a;

    g_pHyprOpenGL->renderRect(CBox{cl - bs, ct - bs, fw + 2 * bs, bs}.round(), bc, {});   // top
    g_pHyprOpenGL->renderRect(CBox{cl - bs, ct + ch, fw + 2 * bs, bs}.round(), bc, {});   // bottom
    g_pHyprOpenGL->renderRect(CBox{cl - bs, ct - bs, bs, ch + 2 * bs}.round(), bc, {});   // left
    g_pHyprOpenGL->renderRect(CBox{cr, ct - bs, bs, ch + 2 * bs}.round(), bc, {});        // right (bar's outer edge)
}

// Hover text for a cell: fixed strings for the five system cells, the
// registered tooltip for app cells ("" = draw nothing).
std::string CVtbDeco::tooltipForCell(int cell) {
    switch (cell) {
        case 0: return "close";
        case 1: return m_bMaximized ? "unmaximize" : "maximize";
        case 2: return "minimize";
        case 3: return "pin";
        case 4: return m_bRolledUp ? "unroll" : "roll up";
        default: break;
    }
    if (cell >= VTB_APPCELL) {
        SVtbAppReg reg;
        if (VtbIpc::get(appPid(), reg)) {
            const size_t i = cell - VTB_APPCELL;
            if (i < reg.buttons.size())
                return reg.buttons[i].tooltip;
        }
    }
    return "";
}

double CVtbDeco::cellCenterY(int cell) {
    const int CELL = cellSize();
    if (cell >= 0 && cell < VTB_CELLS)
        return VTB_PAD + cell * (CELL + VTB_CELL_GAP) + CELL / 2.0;
    if (cell >= VTB_APPCELL) {
        SVtbAppReg reg;
        if (VtbIpc::get(appPid(), reg)) {
            const size_t want = cell - VTB_APPCELL;
            double       cy   = -1;
            walkAppLayout(reg.buttons, effectiveBoxGlobal().h, [&](size_t i, double y) {
                if (i == want && !reg.buttons[i].isSep())
                    cy = y + CELL / 2.0;
            });
            return cy;
        }
    }
    return -1;
}

// The pop-out label itself: 1px accent outline, bar-background fill, pixel
// font — the same look filer's old in-window tooltips had. Animated: slides
// OUT of the bar's left edge (OutCubic, ~220ms) like the quickshell hover
// widgets slide out of the screen edge, and retracts back into it. The label
// starts fully tucked behind the bar and is clipped to the bar's left edge, so
// the un-emerged part stays hidden behind the bar as it travels. Called each
// rendered frame from drawTooltipPass while m_bTooltipShown; advances the slide
// phase itself and re-damages until it settles, so it animates on a still cursor.
static constexpr float VTB_TT_SLIDE_MS = 220.f; // matches SlidePopup's 220ms card slide

static float easeOutCubic(float t) {
    const float u = 1.f - std::clamp(t, 0.f, 1.f);
    return 1.f - u * u * u;
}

void CVtbDeco::renderTooltip(PHLMONITOR pMonitor, const CBox& barBox, float SCALE, float a) {
    if (!m_bTooltipShown)
        return;

    // advance the slide phase toward the current target (1 shown, 0 retracted)
    const float TARGET = m_ttWantShown ? 1.f : 0.f;
    const auto  NOW    = Time::steadyNow();
    float       dt     = std::chrono::duration<float, std::milli>(NOW - m_ttPhaseAt).count();
    m_ttPhaseAt        = NOW;
    dt                 = std::clamp(dt, 0.f, 64.f); // cap so a stale timestamp can't jump the slide
    const float step   = dt / VTB_TT_SLIDE_MS;
    if (m_ttPhase < TARGET)
        m_ttPhase = std::min(TARGET, m_ttPhase + step);
    else if (m_ttPhase > TARGET)
        m_ttPhase = std::max(TARGET, m_ttPhase - step);
    const bool animating = (m_ttPhase != TARGET);

    // fully retracted -> finalize: stop being an active element next frame
    if (m_ttPhase <= 0.f && !m_ttWantShown) {
        m_bTooltipShown = false;
        m_ttCell        = -1;
        if (m_tooltipBox.w > 0) {
            CBox b = m_tooltipBox;
            g_pHyprRenderer->damageBox(b.expand(4));
            m_tooltipBox = {};
        }
        return;
    }

    const auto TEXT = tooltipForCell(m_ttCell);
    const double CY = cellCenterY(m_ttCell);
    if (TEXT.empty() || CY < 0)
        return;

    auto bgColor   = configColor(g_pGlobalState->config.bgColor->value());
    auto accent    = configColor(g_pGlobalState->config.accentColor->value());
    auto textCol   = configColor(g_pGlobalState->config.textColor->value());

    const float E = easeOutCubic(m_ttPhase); // eased slide amount (no fade — it emerges from behind the bar)
    bgColor.a *= a;
    accent.a *= a;

    const auto FONT = g_pGlobalState->config.font->value();
    const int  SIZE = std::round(g_pGlobalState->config.fontSize->value() * SCALE);
    const auto KEY  = TEXT + "|" + std::format("{:08x}", textCol.getAsHex());

    auto       it  = m_tooltipCache.find(KEY);
    auto       tex = (it != m_tooltipCache.end()) ? it->second : (m_tooltipCache[KEY] = g_pHyprRenderer->renderText(TEXT, textCol, SIZE, false, FONT, 0));
    if (!tex || tex->m_texID == 0)
        return;

    const double PADPX = 6 * SCALE;
    const double W     = tex->m_size.x + PADPX * 2;
    const double H     = tex->m_size.y + PADPX * 2;

    // rest position sits just left of the bar; at phase 0 the label is shoved a
    // full width+gap to the RIGHT so it's entirely tucked behind the bar, then
    // slides left out into place. hideDist = W + gap => right edge starts at the
    // bar's left edge.
    const double restX    = barBox.x - W - 6 * SCALE;
    const double hideDist = W + 6 * SCALE;
    const double slideX   = restX + (1.f - E) * hideDist;

    // Clip everything to the LEFT of the bar so the not-yet-emerged part stays
    // hidden behind it. renderRect/renderTexture reset the GL scissor to their
    // own damage region internally, so a manual scissor would be ignored — pass
    // a clipped damage region via the render-data structs instead.
    CRegion clip = g_pHyprRenderer->m_renderData.damage.copy();
    clip.intersect(CBox{0.0, 0.0, barBox.x, (double)pMonitor->m_transformedSize.y});

    CBox box = {slideX, barBox.y + CY * SCALE - H / 2.0, W, H};
    box.round();

    g_pHyprOpenGL->renderRect(box, accent, {.damage = &clip});
    CBox inner = {box.x + SCALE, box.y + SCALE, box.w - 2 * SCALE, box.h - 2 * SCALE};
    g_pHyprOpenGL->renderRect(inner.round(), bgColor, {.damage = &clip});
    CBox tbox = {box.x + PADPX, box.y + PADPX, (double)tex->m_size.x, (double)tex->m_size.y};
    g_pHyprOpenGL->renderTexture(tex, tbox.round(), {.damage = &clip, .a = a});

    // remember the GLOBAL logical box (covering the full slide range, up to the
    // bar edge) so a later damage clears every pixel the label could have touched
    const auto   DECOBOX = effectiveBoxGlobal();
    const double LW      = W / SCALE + 10;
    const double LH      = H / SCALE + 4;
    m_tooltipBox         = {DECOBOX.x - LW, DECOBOX.y + CY - LH / 2.0, LW + 2, LH};

    // keep frames coming until the slide settles (a motionless cursor emits no
    // events of its own; this self-sustains the animation)
    if (animating)
        g_pHyprRenderer->damageBox(CBox{m_tooltipBox});
}

// Begin the click-activation flash on a cell (system 0-4 or app 1000+i): the
// cell inverts for VTB_FLASH_MS, self-damaging each frame in renderPass until
// it expires. Feedback that a press registered.
void CVtbDeco::flashCell(int cell) {
    m_flashCell = cell;
    m_flashAt   = Time::steadyNow();
    damageEntire();
}

// Request the tooltip retract (slide + fade back out). The actual teardown
// happens in renderTooltip once the phase reaches 0; here we just flip the
// target and kick a frame so the retract animates instead of snapping.
void CVtbDeco::hideTooltip() {
    if (!m_bTooltipShown || !m_ttWantShown)
        return;
    m_ttWantShown = false;
    m_ttPhaseAt   = Time::steadyNow(); // fresh dt so the slide-out starts smooth
    if (m_tooltipBox.w > 0)
        g_pHyprRenderer->damageBox(CBox{m_tooltipBox}.expand(4));
}

// The tooltip's own pass element body (RENDER_POST_WINDOWS): recompute the
// monitor-local bar box the same way renderPass does, then draw the label.
void CVtbDeco::drawTooltipPass(PHLMONITOR pMonitor, float a) {
    if (!m_bTooltipShown || !validMapped(m_pWindow) || !pMonitor)
        return;
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW)
        return;

    const auto SCALE   = pMonitor->m_scale;
    const auto DECOBOX = effectiveBoxGlobal();

    CBox       barBox = {DECOBOX.x - pMonitor->m_position.x, DECOBOX.y - pMonitor->m_position.y, DECOBOX.w, DECOBOX.h};
    barBox.translate(PWINDOW->m_floatingOffset).scale(SCALE).round();
    if (barBox.w < 1 || barBox.h < 1)
        return;

    renderTooltip(pMonitor, barBox, SCALE, a);
}

// Enqueue the hover tooltip over the window surface. Called per-monitor from
// main.cpp's RENDER_POST_WINDOWS hook; no-ops unless a tooltip is showing for
// a window on this monitor.
void CVtbDeco::enqueueTooltip(PHLMONITOR pMonitor) {
    if (!m_bTooltipShown || !g_pGlobalState || !g_pGlobalState->config.enabled->value())
        return;
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW || !pMonitor || PWINDOW->m_monitor.lock() != pMonitor)
        return;

    auto data        = CVtbPassElement::SVtbData{this, 1.F};
    data.tooltipOnly = true;
    g_pHyprRenderer->m_renderPass.add(makeUnique<CVtbPassElement>(data));
}

void CVtbDeco::mainThreadTick(uint64_t ipcSerial) {
    // Reliable roll-animation finalize. stepRollAnim kicks finishRollAnim via
    // doLater with a captured weak `self`, but that weak-ref lock()s to null a
    // tick later — the deco's self-ref is orphaned when its owning UP is moved
    // into addWindowDecoration — so finishRollAnim never runs and m_rollAnim
    // stays stuck at ROLL_UP/OUT. That made every click read as "inert mid-
    // animation" and skipped the rolled-up hover path (buttons unclickable, hover
    // lit the wrong cell). The tick reaches this live deco through the `bars`
    // weak-ref that DOES resolve, and runs off the render loop — exactly the safe
    // context finishRollAnim needs — so drive the finalize from here too.
    if (m_rollFinishing && m_rollAnim != ROLL_NONE)
        finishRollAnim();

    if (!validMapped(m_pWindow))
        return;

    // registration changed since the last render -> pre-upload the new glyphs
    // (so the redraw doesn't create+sample them in one tiler job — the
    // flash-blank fix) then repaint the bar. This runs from the timer, off the
    // render pass, which is exactly the separate GPU submission we need; it's
    // also why the serial check lives here and not in onMouseMove any more.
    if (ipcSerial != m_lastIpcSerial) {
        m_lastIpcSerial = ipcSerial;
        prewarmGlyphs();
        damageEntire();
    }

    // address editor open: keep frames coming so the caret blinks on a still
    // cursor, and skip the hover-tooltip dwell (the bar is in edit mode).
    if (m_bEditing) {
        damageEntire();
        return;
    }

    // tooltip dwell (hover state is maintained by onMouseMove; this just starts
    // the slide-in once the cursor has rested long enough). Skip if we're
    // already showing THIS cell — otherwise re-fire when the tooltip is absent,
    // retracting, or belongs to a different cell.
    const bool alreadyShowingHover = m_bTooltipShown && m_ttWantShown && m_ttCell == m_iHoverCell;
    // Tooltips only on the focused window — an unfocused window's bar shouldn't
    // pop labels (the cursor is usually just passing over it to click-focus).
    const bool FOCUSED = m_pWindow.lock() == Desktop::focusState()->window();
    if (FOCUSED && m_iHoverCell != -1 && !m_bMinimized && !alreadyShowingHover &&
        std::chrono::duration_cast<std::chrono::milliseconds>(Time::steadyNow() - m_hoverSince).count() > 450 && !tooltipForCell(m_iHoverCell).empty()) {
        m_ttCell        = m_iHoverCell;
        m_ttWantShown   = true;
        m_bTooltipShown = true;
        m_ttPhaseAt     = Time::steadyNow(); // fresh dt so the slide-in starts smooth
        // Pre-size the tooltip box to a generous strip left of the cell BEFORE
        // the first render: the RENDER_POST_WINDOWS pass element uses it as its
        // bounding box, so it must already cover the label on the frame the
        // tooltip first appears (renderTooltip narrows it to the exact box).
        const auto   B  = effectiveBoxGlobal();
        const double CY = cellCenterY(m_ttCell);
        if (CY >= 0) {
            m_tooltipBox = {B.x - 360, B.y + CY - 30, 360, 60};
            g_pHyprRenderer->damageBox(CBox{m_tooltipBox});
        }
        damageEntire();
    } else if (!FOCUSED && m_bTooltipShown && m_ttWantShown) {
        // Lost focus while a tooltip was out (focus can change without the
        // cursor leaving our bar) — retract it.
        hideTooltip();
    }
}

pid_t CVtbDeco::appPid() {
    if (m_appPid == -1) {
        const auto W = m_pWindow.lock();
        m_appPid     = W ? W->getPID() : 0;
    }
    return m_appPid;
}

// Hit-test the inner (app) column: index into reg.buttons, or -1.
int CVtbDeco::appCellAt(const Vector2D& c, const SVtbAppReg& reg) {
    if (c.x < innerColX() || c.x > innerColX() + cellSize())
        return -1;
    int hit = -1;
    walkAppLayout(reg.buttons, effectiveBoxGlobal().h, [&](size_t i, double y) {
        if (!reg.buttons[i].isSep() && c.y >= y && c.y <= y + cellSize())
            hit = (int)i;
    });
    return hit;
}

// Render this window's app-button glyph textures into the cache NOW, from the
// main-thread timer — a GPU submission separate from (and before) the frame
// that samples them. Fixes a flash-blank on Apple-Silicon/Asahi: when several
// buttons changed colour at once (filer enabling copy/cut/… on a selection),
// renderPass created those glyph textures AND sampled them in the same tiler
// job, and the just-uploaded textures read blank for that one frame. Cheap: a
// handful of small glyphs, only when the registration changed.
void CVtbDeco::prewarmGlyphs() {
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW)
        return;
    const auto PMONITOR = PWINDOW->m_monitor.lock();
    if (!PMONITOR)
        return;
    const float SCALE   = PMONITOR->m_scale;
    const bool  FOCUSED = PWINDOW == Desktop::focusState()->window();

    const auto accentColor   = configColor(g_pGlobalState->config.accentColor->value());
    const auto inactiveColor = configColor(g_pGlobalState->config.inactiveColor->value());
    const auto bgColor       = configColor(g_pGlobalState->config.bgColor->value());
    const auto textColor     = FOCUSED ? accentColor : inactiveColor;

    SVtbAppReg reg;
    if (!VtbIpc::get(appPid(), reg))
        return;
    for (const auto& b : reg.buttons) {
        if (b.isSep() || b.label.empty())
            continue;
        // every colour a glyph can be drawn in: normal, disabled, lit, flashed
        glyphTex(b.label, textColor, SCALE);
        glyphTex(b.label, inactiveColor, SCALE);
        glyphTex(b.label, accentColor, SCALE);
        glyphTex(b.label, bgColor, SCALE);
    }
}

// Nearest DRAGGABLE app slot to the cursor's Y (the reorder drop target) — the
// reorder is confined to the draggable group (surfer's tabs); -1 if none.
int CVtbDeco::appDropSlot(const Vector2D& c, const SVtbAppReg& reg) {
    int    best     = -1;
    double bestDist = 1e9;
    const int CELL  = cellSize();
    walkAppLayout(reg.buttons, effectiveBoxGlobal().h, [&](size_t i, double y) {
        if (!reg.buttons[i].draggable)
            return;
        const double d = std::abs(c.y - (y + CELL / 2.0));
        if (d < bestDist) {
            bestDist = d;
            best     = (int)i;
        }
    });
    return best;
}

// ---- title address editor -------------------------------------------------

bool CVtbDeco::titleEditEnabled() {
    SVtbAppReg reg;
    return VtbIpc::get(appPid(), reg) && reg.titleEdit;
}

// titleTop() plus a one-cell spinner slot reserved while a browser window's page
// is loading (renderPass draws the | \ - / spinner in that slot). Both the title
// texture and the address-editor hit-testing use this, so they shift down
// together while loading and stay in sync.
int CVtbDeco::titleTopEff() {
    SVtbAppReg reg;
    const bool spin = VtbIpc::get(appPid(), reg) && reg.titleEdit && reg.loading;
    return titleTop() + (spin ? (cellSize() + VTB_CELL_GAP) : 0);
}

// The clickable address-bar region: the outer column band from the title top
// down (where the stacked title texture is drawn).
bool CVtbDeco::inTitleRegion(const Vector2D& c) {
    return c.y >= titleTopEff() && c.x >= sysColX() && c.x <= sysColX() + cellSize();
}

void CVtbDeco::enterEdit() {
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW)
        return;
    m_editBuf       = PWINDOW->m_title; // seed with the current address (surfer sets title = URL)
    m_editCursor    = m_editBuf.size(); // whole field selected on open, like a browser:
    m_editSelAnchor = 0;                //   anchor 0 .. cursor end
    m_bEditDragging = false;
    m_editScrollCp  = 0;                // show the URL from the top; wheel/caret scroll from here
    m_editLastCaret = m_editCursor;     // don't auto-scroll to the (end) caret on open
    m_bEditing      = true;
    m_pEditTex      = nullptr;
    m_pEditSelTex   = nullptr;
    m_editBlinkAt   = Time::steadyNow();
    hideTooltip();
    damageEntire();
}

void CVtbDeco::exitEdit(bool submit) {
    if (!m_bEditing)
        return;
    m_bEditing = false;
    if (submit)
        VtbIpc::sendAddr(appPid(), m_editBuf);
    m_editBuf.clear();
    m_editCursor    = 0;
    m_editSelAnchor = 0;
    m_bEditDragging = false;
    m_pEditTex      = nullptr;
    m_pEditSelTex   = nullptr;
    damageEntire();
}

// Erase the current selection (if any), collapsing the caret to its start.
// Returns whether there was a selection to delete.
bool CVtbDeco::deleteEditSelection() {
    if (m_editSelAnchor == m_editCursor)
        return false;
    const size_t lo = std::min(m_editSelAnchor, m_editCursor);
    const size_t hi = std::max(m_editSelAnchor, m_editCursor);
    m_editBuf.erase(lo, hi - lo);
    m_editCursor    = lo;
    m_editSelAnchor = lo;
    m_pEditTex      = nullptr;
    return true;
}

// Map a bar-local Y (logical px) to a byte offset on a codepoint boundary — the
// row under the cursor in the vertically-stacked address text. Used for
// click-to-place-caret and click-drag selection.
size_t CVtbDeco::editByteAtLocalY(double localY) {
    const double scale = m_fLastScale > 0 ? m_fLastScale : 1.0;
    const double lineH = (m_iEditLineH > 0) ? m_iEditLineH / scale
                                            : (double)g_pGlobalState->config.fontSize->value();
    const int displayRow = (int)std::floor((localY - titleTopEff()) / std::max(1.0, lineH));
    const int nCp = countCp(m_editBuf, m_editBuf.size());
    // the on-screen rows start at m_editScrollCp, so add it back to the click row
    const int row = std::clamp(displayRow + m_editScrollCp, 0, nCp);
    size_t off = 0;
    for (int k = 0; k < row; k++)
        off = nextCp(m_editBuf, off);
    return off;
}

// How many stacked codepoint rows fit in the address editor's height (device
// px / line height), matching renderPass's RUNLEN / m_iEditLineH.
int CVtbDeco::editVisibleRows() {
    const double scale = m_fLastScale > 0 ? m_fLastScale : 1.0;
    const double avail = (effectiveBoxGlobal().h - titleTopEff() - VTB_PAD) * scale;
    const double lineH = m_iEditLineH > 0 ? (double)m_iEditLineH
                                          : (g_pGlobalState->config.fontSize->value() * scale);
    return std::max(1, (int)std::floor(avail / std::max(1.0, lineH)));
}

// Scroll the vertical address text so the caret's row is on-screen. Only nudges
// when the caret is above/below the visible window, so a manual wheel-scroll
// that keeps the caret in view isn't yanked back.
void CVtbDeco::ensureEditCaretVisible() {
    const int caretCp = countCp(m_editBuf, m_editCursor);
    const int rows    = editVisibleRows();
    const int before  = m_editScrollCp;
    if (caretCp < m_editScrollCp)
        m_editScrollCp = caretCp;
    else if (caretCp >= m_editScrollCp + rows)
        m_editScrollCp = caretCp - rows + 1;
    if (m_editScrollCp < 0)
        m_editScrollCp = 0;
    if (m_editScrollCp != before)
        m_pEditTex = nullptr; // scrolled -> rebuild the (substring) texture
}

// Wheel while the address editor is open scrolls the stacked URL instead of the
// page (we own the keyboard grab; owning the wheel too keeps a long URL
// navigable). Only the focused/editing window's deco consumes it.
void CVtbDeco::onMouseAxis(Event::SCallbackInfo& info, const IPointer::SAxisEvent& e) {
    if (!m_bEditing)
        return;
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW || PWINDOW != Desktop::focusState()->window())
        return;
    if (e.axis != WL_POINTER_AXIS_VERTICAL_SCROLL || e.delta == 0.0)
        return;
    info.cancelled = true; // scroll the editor, not the page
    const int totalCp   = countCp(m_editBuf, m_editBuf.size());
    const int rows      = editVisibleRows();
    const int maxScroll = std::max(0, totalCp - rows);
    const int next      = std::clamp(m_editScrollCp + (e.delta > 0 ? 1 : -1), 0, maxScroll);
    if (next != m_editScrollCp) {
        m_editScrollCp = next;
        m_pEditTex     = nullptr;
        damageEntire();
    }
}

// Keyboard grab while the address editor is open: swallow the keys we act on
// (info.cancelled stops them before keybinds AND the focused client), but let
// Ctrl/Alt/Super combos through so compositor shortcuts still work — same as a
// focused text field. Fires for every deco's listener; only the one editing acts.
void CVtbDeco::onKeyboardKey(Event::SCallbackInfo& info, const IKeyboard::SKeyEvent& e) {
    if (!m_bEditing)
        return;

    // Only swallow keys while WE are the focused window. If focus slipped away
    // before renderPass could cancel the edit, bail out here — never eat keys
    // meant for another client.
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW || PWINDOW != Desktop::focusState()->window()) {
        exitEdit(false);
        return;
    }

    const auto KB = g_pSeatManager->m_keyboard.lock();
    if (!KB || !KB->m_xkbState)
        return;

    const uint32_t     xkbcode = e.keycode + 8; // libinput -> xkb
    const xkb_keysym_t sym     = xkb_state_key_get_one_sym(KB->m_xkbState, xkbcode);
    const uint32_t     mods    = KB->getModifiers();

    // editing Ctrl combos we handle ourselves: Ctrl+A selects the whole field.
    // (Copy/paste would need wl-clipboard plumbing — not wired yet.) Everything
    // else with Ctrl/Alt/Super falls through to global keybinds below.
    if ((mods & HL_MODIFIER_CTRL) && !(mods & (HL_MODIFIER_ALT | HL_MODIFIER_META))
        && (sym == XKB_KEY_a || sym == XKB_KEY_A)) {
        info.cancelled = true;
        if (e.state == WL_KEYBOARD_KEY_STATE_PRESSED) {
            m_editSelAnchor = 0;
            m_editCursor    = m_editBuf.size();
            m_pEditTex      = nullptr;
            damageEntire();
        }
        return;
    }

    // let global keybinds (Super+…, Ctrl/Alt combos) pass straight through
    if (mods & (HL_MODIFIER_CTRL | HL_MODIFIER_ALT | HL_MODIFIER_META))
        return;

    char       utf8[8] = {0};
    const int  n       = xkb_state_key_get_utf8(KB->m_xkbState, xkbcode, utf8, sizeof(utf8));
    const bool printable = n > 0 && static_cast<unsigned char>(utf8[0]) >= 0x20 && static_cast<unsigned char>(utf8[0]) != 0x7f;

    bool ours = printable;
    switch (sym) {
        case XKB_KEY_Escape:
        case XKB_KEY_Return:
        case XKB_KEY_KP_Enter:
        case XKB_KEY_BackSpace:
        case XKB_KEY_Delete:
        case XKB_KEY_Left:
        case XKB_KEY_Right:
        case XKB_KEY_Home:
        case XKB_KEY_End: ours = true; break;
        default: break;
    }
    if (!ours) // modifiers, F-keys, etc. — leave for the normal pipeline
        return;

    info.cancelled = true;                                  // swallow press AND release
    if (e.state != WL_KEYBOARD_KEY_STATE_PRESSED)
        return;

    m_editBlinkAt = Time::steadyNow(); // reset blink so the caret is solid while typing

    if (sym == XKB_KEY_Escape) {
        exitEdit(false);
        return;
    }
    if (sym == XKB_KEY_Return || sym == XKB_KEY_KP_Enter) {
        exitEdit(true);
        return;
    }

    // Shift extends the selection; an unshifted move collapses it. Anchor stays
    // put while Shift is held, so anchor..cursor is the live selection range.
    const bool shift = mods & HL_MODIFIER_SHIFT;

    switch (sym) {
        case XKB_KEY_Left:
            if (m_editSelAnchor != m_editCursor && !shift)
                m_editCursor = std::min(m_editSelAnchor, m_editCursor); // collapse to near edge
            else
                m_editCursor = prevCp(m_editBuf, m_editCursor);
            if (!shift) m_editSelAnchor = m_editCursor;
            m_pEditTex = nullptr; damageEntire(); return;
        case XKB_KEY_Right:
            if (m_editSelAnchor != m_editCursor && !shift)
                m_editCursor = std::max(m_editSelAnchor, m_editCursor);
            else
                m_editCursor = nextCp(m_editBuf, m_editCursor);
            if (!shift) m_editSelAnchor = m_editCursor;
            m_pEditTex = nullptr; damageEntire(); return;
        case XKB_KEY_Home:
            m_editCursor = 0;
            if (!shift) m_editSelAnchor = m_editCursor;
            m_pEditTex = nullptr; damageEntire(); return;
        case XKB_KEY_End:
            m_editCursor = m_editBuf.size();
            if (!shift) m_editSelAnchor = m_editCursor;
            m_pEditTex = nullptr; damageEntire(); return;
        case XKB_KEY_BackSpace:
            if (!deleteEditSelection() && m_editCursor > 0) {
                const size_t p = prevCp(m_editBuf, m_editCursor);
                m_editBuf.erase(p, m_editCursor - p);
                m_editCursor    = p;
                m_editSelAnchor = p;
                m_pEditTex      = nullptr;
            }
            damageEntire();
            return;
        case XKB_KEY_Delete:
            if (!deleteEditSelection() && m_editCursor < m_editBuf.size()) {
                const size_t nx = nextCp(m_editBuf, m_editCursor);
                m_editBuf.erase(m_editCursor, nx - m_editCursor);
                m_editSelAnchor = m_editCursor;
                m_pEditTex      = nullptr;
            }
            damageEntire();
            return;
        default: break;
    }

    if (printable) {
        deleteEditSelection();               // typing replaces any selection
        m_editBuf.insert(m_editCursor, utf8, n);
        m_editCursor    += n;
        m_editSelAnchor  = m_editCursor;
        m_pEditTex       = nullptr;
        damageEntire();
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

    // Accept only when the cursor is over US, or over EMPTY space while we're
    // focused (the resize halo just outside our frame). The old test also
    // accepted "we're focused" when the cursor sat over ANOTHER window — so a
    // focused window hidden BEHIND another still grabbed presses aimed at the
    // window on top, then moved/resized itself and cancelled the event (e.g.
    // dragging filer's inner bar moved the focused window behind it, and filer
    // never got the press). If something else occupies the point, it occludes
    // us and must own the event.
    if (WINDOWATCURSOR != m_pWindow && (WINDOWATCURSOR || m_pWindow != focusState->window()))
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
    // system cells live in the OUTER column of the double-wide bar
    const int CELL = cellSize();
    const int X    = sysColX();
    for (int i = 0; i < VTB_CELLS; i++) {
        const double y = VTB_PAD + i * (CELL + VTB_CELL_GAP);
        if (VECINRECT(c, X, y, X + CELL, y + CELL))
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

// The visual frame: window + our (double-wide) bar, wrapped by one border.
static CBox frameBox(PHLWINDOW w) {
    CBox box = {w->m_realPosition->value(), w->m_realSize->value()};
    if (g_pGlobalState->config.enabled->value())
        box.w += totalBarW();
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
    if (!validMapped(m_pWindow) || !PWINDOW->m_isFloating || PWINDOW->isFullscreen() || m_bMinimized || m_bMaximized || m_bRolledUp)
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

    // Releases are processed UNGATED: they only clear/finish this deco's own
    // press state. Gating them behind inputIsValid (or focus, see
    // handleUpEvent) is how stale state leaked — a resize could stick if the
    // cursor ended over a layer surface, and a stale cancelled-press flag
    // ate a later client release (the stuck-mouse-after-restore bug).
    if (e.state != WL_POINTER_BUTTON_STATE_PRESSED) {
        if (m_bEdgeResizing) {
            endEdgeResize();
            info.cancelled = true;
            return;
        }
        if (m_bRolledUp) {
            if (m_rollAnim == ROLL_NONE)
                handleRolledUp(info);
            return;
        }
        handleUpEvent(info);
        return;
    }

    // clicks are inert while a roll animation plays (the bar is in motion)
    if (m_rollAnim != ROLL_NONE)
        return;

    // A shaded window is hidden, so the normal inputIsValid() path (which needs
    // the window under the cursor / focused) never accepts — hit-test the
    // floating bar ourselves instead.
    if (m_bRolledUp) {
        handleRolledDown(info);
        return;
    }

    if (!inputIsValid())
        return;

    if (tryStartEdgeResize(info, e))
        return;

    handleDownEvent(info);
}

void CVtbDeco::onMouseMove(Vector2D coords) {
    if (!g_pGlobalState)
        return;

    // selecting in the address editor: drag the cursor end to the row under the
    // pointer (anchor stays at the press point), extending the highlight.
    if (m_bEditDragging) {
        const auto   BOX   = assignedBoxGlobal();
        const auto   LOCAL = g_pInputManager->getMouseCoordsInternal() - BOX.pos();
        const size_t at    = editByteAtLocalY(LOCAL.y);
        if (at != m_editCursor) {
            m_editCursor = at;
            m_pEditTex   = nullptr;
            damageEntire();
        }
        return;
    }

    // App-button registration changes are handled by the main-thread timer
    // (mainThreadTick), which pre-warms glyph textures before repainting — see
    // the note there. Doing it here too would repaint WITHOUT that pre-warm and
    // reintroduce the flash-blank, so onMouseMove no longer touches the serial.

    if (m_bEdgeResizing) {
        updateEdgeResize();
        return;
    }

    // shaded window: either drag its floating bar (relocating the hidden
    // window) or just hover-test it — no resize cursor. Inert mid-animation.
    if (m_bRolledUp && m_rollAnim == ROLL_NONE) {
        if (m_bRollDragPending || m_bRollDragging) {
            const auto DELTA = g_pInputManager->getMouseCoordsInternal() - m_rollDragMouseStart;
            if (!m_bRollDragging && (std::abs(DELTA.x) + std::abs(DELTA.y)) > 4)
                m_bRollDragging = true;
            if (m_bRollDragging) {
                const auto PWINDOW = m_pWindow.lock();
                // Clear the bar's old spot at the box it was actually DRAWN in:
                // effectiveBoxGlobal() is m_rollBox dropped by VTB_SHADOW_SIZE, so
                // damaging raw m_rollBox left the bottom shadow-strip of the bar
                // un-repainted — a dark trail that read as a shadow smear behind
                // a moving rolled-up window.
                g_pHyprRenderer->damageBox(CBox{effectiveBoxGlobal()}.expand(2));
                m_rollBox.x  = m_rollDragBoxStart.x + DELTA.x;
                m_rollBox.y  = m_rollDragBoxStart.y + DELTA.y;
                m_iHoverCell = -1;
                if (PWINDOW) {
                    // Move the hidden window so it reappears here on restore.
                    // Update BOTH the logical box (m_position) and the animated
                    // draw position: warping only m_realPosition left m_position
                    // stale, so a later real drag snapped back to the pre-shade
                    // spot before following the cursor (the "skips positions" bug).
                    const Vector2D NEWPOS = m_rollDragWinStart + DELTA;
                    PWINDOW->m_position = NEWPOS;
                    PWINDOW->m_realPosition->setValueAndWarp(NEWPOS);
                }
                g_pHyprRenderer->damageBox(CBox{effectiveBoxGlobal()}.expand(2)); // new spot, same cushion
            }
            return;
        }

        // Hit-test the bar where it's actually DRAWN. renderPass draws it at
        // effectiveBoxGlobal() (the DROPPED resting box — m_rollBox is the raised
        // capture, VTB_SHADOW_SIZE too high) translated by the window's floating
        // offset. Hit-testing against raw m_rollBox was off by both, so the wrong
        // cell lit (or none) — and clicks (which use effectiveBoxGlobal) missed
        // by the floating offset too; fold both in so all three agree.
        const auto     HIT = effectiveBoxGlobal();
        const auto     PW  = m_pWindow.lock();
        const Vector2D OFF = PW ? PW->m_floatingOffset : Vector2D();
        const auto     LOCAL = g_pInputManager->getMouseCoordsInternal() - (HIT.pos() + OFF);
        const int      cell  = VECINRECT(LOCAL, 0, 0, HIT.w, HIT.h) ? cellAt(LOCAL) : -1;
        if (cell != m_iHoverCell) {
            m_iHoverCell = cell;
            m_hoverSince = Time::steadyNow(); // the main-thread tick pops the tooltip after the dwell
            hideTooltip();
            damageEntire();
        }
        return;
    }

    // app-button press in progress: promote to a drag once the cursor travels,
    // then track the drop slot (draggable buttons only — surfer's tabs). A
    // non-draggable button dragged off cancels its pending click.
    if (m_bAppPressPending) {
        const auto   DELTA = g_pInputManager->getMouseCoordsInternal() - m_appDragMouseStart;
        const double dist  = std::abs(DELTA.x) + std::abs(DELTA.y);
        if (!m_bAppDragging && dist > 6) {
            if (m_appPressDraggable)
                m_bAppDragging = true;
            else
                m_bAppPressPending = false;
        }
        if (m_bAppDragging) {
            SVtbAppReg reg;
            if (VtbIpc::get(appPid(), reg)) {
                const auto LOCAL = g_pInputManager->getMouseCoordsInternal() - assignedBoxGlobal().pos();
                const int  tgt   = appDropSlot(LOCAL, reg);
                if (tgt != m_iAppDragTarget)
                    m_iAppDragTarget = tgt;
            }
            damageEntire();
        }
        if (m_bAppPressPending)
            return; // holding a button — don't fall through to window hover/drag
    }

    // hover feedback on the button cells (system column + app column)
    if (validMapped(m_pWindow) && !m_bMinimized) {
        const auto BOX    = assignedBoxGlobal();
        const auto LOCAL  = g_pInputManager->getMouseCoordsInternal() - BOX.pos();
        int        cell   = VECINRECT(LOCAL, 0, 0, BOX.w, BOX.h) ? cellAt(LOCAL) : -1;
        if (cell == -1 && VECINRECT(LOCAL, 0, 0, BOX.w, BOX.h)) {
            SVtbAppReg reg;
            if (VtbIpc::get(appPid(), reg)) {
                const int AI = appCellAt(LOCAL, reg);
                if (AI >= 0 && reg.buttons[AI].state != 2) // disabled cells don't light
                    cell = VTB_APPCELL + AI;
            }
        }
        if (cell != m_iHoverCell) {
            m_iHoverCell = cell;
            m_hoverSince = Time::steadyNow(); // the main-thread tick pops the tooltip after the dwell
            hideTooltip();
            damageEntire();
        }

        // Resize cursor over OUR right-edge zones. Hyprland's border-icon
        // logic suppresses itself over decorations and only knows the client
        // box, so the bar strip / right halo never get a cursor from it —
        // set the same WINDOW_EDGE override it uses for the other sides.
        if (m_pWindow->m_isFloating && !m_bMaximized && !m_bEdgeResizing && g_pInputManager->m_currentlyHeldButtons.empty()) {
            const auto MOUSE = g_pInputManager->getMouseCoordsInternal();
            // ...but only when our edge is actually the top-most thing here. If
            // another window is stacked over ours at this point, the edge is
            // occluded and can't be grabbed — offering the resize cursor there
            // was misleading (the press is already rejected by inputIsValid's
            // same window-at-cursor test). vectorToWindowUnified honours z-order;
            // a null result is empty space, where a halo edge-grab is still valid.
            const auto WINDOWATCURSOR = g_pCompositor->vectorToWindowUnified(
                MOUSE, Desktop::View::RESERVED_EXTENTS | Desktop::View::INPUT_EXTENTS | Desktop::View::ALLOW_FLOATING);
            const bool occluded = WINDOWATCURSOR && WINDOWATCURSOR != m_pWindow;
            const auto Z        = occluded ? 0u : borderResizeZone(MOUSE);
            if (Z & RS_EDGE_R) {
                const char* shape = (Z & RS_EDGE_T) ? "top_right_corner" : (Z & RS_EDGE_B) ? "bottom_right_corner" : "right_side";
                Cursor::overrideController->setOverride(shape, Cursor::CURSOR_OVERRIDE_WINDOW_EDGE);
                m_bCursorOverridden = true;
            } else if (m_bCursorOverridden) {
                Cursor::overrideController->unsetOverride(Cursor::CURSOR_OVERRIDE_WINDOW_EDGE);
                m_bCursorOverridden = false;
            }
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

    // Was this window already focused when the press landed? A click on an
    // UNFOCUSED window's address bar should only focus it (like every other
    // click-to-focus) — the edit opens on the NEXT click. Captured before we
    // steal focus just below.
    const bool WASFOCUSED = Desktop::focusState()->window() == PWINDOW;

    if (!WASFOCUSED)
        Desktop::focusState()->fullWindowFocus(PWINDOW, Desktop::FOCUS_REASON_CLICK);

    if (PWINDOW->m_isFloating)
        g_pCompositor->changeWindowZOrder(PWINDOW, true);

    info.cancelled   = true;
    m_bCancelledDown = true;
    hideTooltip(); // a press dismisses the hover label

    // address editor already open: clicking in the field places the caret at
    // the clicked row and starts a drag-selection from there; a press anywhere
    // else on the bar cancels the edit and proceeds.
    if (m_bEditing) {
        if (titleEditEnabled() && inTitleRegion(COORDS)) {
            const size_t at = editByteAtLocalY(COORDS.y);
            m_editCursor    = at;
            m_editSelAnchor = at;
            m_bEditDragging = true;
            m_editBlinkAt   = Time::steadyNow();
            m_pEditTex      = nullptr;
            damageEntire();
            return;
        }
        exitEdit(false);
    }

    // fire the click-activation flash on whichever system cell was hit (close /
    // minimize also close/hide the window, so their flash just isn't seen)
    const int SYSCELL = cellAt(COORDS);
    if (SYSCELL >= 0)
        flashCell(SYSCELL);

    switch (SYSCELL) {
        case 0: closeWindow(); return;
        case 1: toggleMaximize(); return;
        case 2: minimizeWindow(); return;
        case 3: togglePin(); return;
        case 4: toggleRollup(); return;
        default: break;
    }

    // inner column: app-registered buttons. A press ARMS the button — the CLICK
    // fires on release (handleUpEvent), so a press+drag can instead reorder a
    // draggable button. Disabled cells are inert but still swallow the press.
    {
        SVtbAppReg reg;
        if (VtbIpc::get(appPid(), reg)) {
            const int AI = appCellAt(COORDS, reg);
            if (AI >= 0) {
                if (reg.buttons[AI].state == 2)
                    return; // disabled: inert
                m_bAppPressPending  = true;
                m_bAppDragging      = false;
                m_iAppPressIdx      = AI;
                m_appPressId        = reg.buttons[AI].id;
                m_appPressDraggable = reg.buttons[AI].draggable;
                m_appDragMouseStart = g_pInputManager->getMouseCoordsInternal();
                m_iAppDragTarget    = AI;
                return;
            }
        }
    }

    // editable title (address bar): a plain click opens the editor; a drag from
    // here still moves the window (promoted on move), so just arm both. But if
    // this press only focused the window, mark it focus-only so the release
    // doesn't also open the editor — the user edits on the second click.
    if (titleEditEnabled() && inTitleRegion(COORDS)) {
        m_bTitlePressPending   = true;
        m_bTitlePressFocusOnly = !WASFOCUSED;
        if (!m_bMaximized)
            m_bDragPending = true;
        return;
    }

    // anywhere else on the bar: drag the window (maximized windows are
    // pinned — no dragging until unmaximized)
    if (!m_bMaximized)
        m_bDragPending = true;
}

void CVtbDeco::handleUpEvent(Event::SCallbackInfo& info) {
    // Clear press state UNCONDITIONALLY. This used to early-return when the
    // window wasn't focused — but a minimize click hops focus to the next
    // window mid-press, so the minimize's cancelled-press flag survived
    // here. After restoring the window, its deco then cancelled the FIRST
    // client release ("mouse stuck on a down-click until you click again",
    // any app). One flag, one press: consume the release iff we consumed
    // its press, and always reset.
    const bool CANCELLED = m_bCancelledDown;
    m_bCancelledDown     = false;

    // finishing an address-editor drag-selection: the range is already set (a
    // plain click left anchor == cursor, i.e. just a caret); clear the flag.
    if (m_bEditDragging) {
        m_bEditDragging = false;
        if (CANCELLED)
            info.cancelled = true;
        return;
    }

    // app-button release: a click (no drag) activates via CLICK; a drag drops a
    // reorder via REORDER (draggable buttons only).
    if (m_bAppPressPending) {
        const bool        dragging = m_bAppDragging;
        const int         src      = m_iAppPressIdx;
        const int         tgt      = m_iAppDragTarget;
        const std::string srcId    = m_appPressId;
        m_bAppPressPending = false;
        m_bAppDragging     = false;
        m_iAppPressIdx     = -1;
        m_iAppDragTarget   = -1;
        if (dragging) {
            if (tgt >= 0 && tgt != src) {
                SVtbAppReg reg;
                if (VtbIpc::get(appPid(), reg) && tgt < (int)reg.buttons.size())
                    VtbIpc::sendReorder(appPid(), srcId, reg.buttons[tgt].id);
            }
            damageEntire();
        } else {
            flashCell(VTB_APPCELL + src); // activation feedback
            VtbIpc::sendClick(appPid(), srcId);
        }
        m_bDragPending = false;
        if (CANCELLED)
            info.cancelled = true;
        return;
    }

    // title-region release: a click (never promoted to a window drag) opens the
    // address editor — unless the press only focused the window (edit on the
    // next click).
    if (m_bTitlePressPending) {
        const bool wasDrag     = m_bDraggingThis;
        const bool focusOnly   = m_bTitlePressFocusOnly;
        m_bTitlePressPending   = false;
        m_bTitlePressFocusOnly = false;
        if (m_bDraggingThis) {
            g_pKeybindManager->changeMouseBindMode(MBIND_INVALID);
            m_bDraggingThis = false;
        }
        m_bDragPending = false;
        if (!wasDrag && !m_bEditing && !focusOnly)
            enterEdit();
        if (CANCELLED)
            info.cancelled = true;
        return;
    }

    if (m_bDraggingThis) {
        g_pKeybindManager->changeMouseBindMode(MBIND_INVALID);
        m_bDraggingThis = false;
    }
    m_bDragPending = false;

    if (CANCELLED)
        info.cancelled = true;
}

// Click on a shaded window's floating bar. The window is hidden (so where its
// body used to be is click-through), and we own the hit-test: [x] closes it,
// anything else on the bar un-shades. info.cancelled stops the click from
// falling through to whatever window is now behind the bar.
void CVtbDeco::handleRolledDown(Event::SCallbackInfo& info) {
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW)
        return;
    if (!PWINDOW->m_pinned && (!PWINDOW->m_workspace || !PWINDOW->m_workspace->isVisible()))
        return;

    // hit-test the bar where it's actually drawn: dropped by the set-down
    // (effectiveBoxGlobal) AND shifted by the window's floating offset, exactly
    // as renderPass positions it — otherwise a restored window's non-zero
    // floating offset slid the buttons out from under the click.
    const auto BAR   = effectiveBoxGlobal();
    const auto MOUSE = g_pInputManager->getMouseCoordsInternal();
    const auto LOCAL = MOUSE - (BAR.pos() + PWINDOW->m_floatingOffset);
    if (!VECINRECT(LOCAL, 0, 0, BAR.w, BAR.h))
        return; // not on the bar — let the click pass through to what's behind

    info.cancelled   = true;
    m_bCancelledDown = true;
    hideTooltip();

    const int CELL = cellAt(LOCAL);
    if (CELL >= 0)
        flashCell(CELL); // activation feedback (shaded bar draws through the same renderPass)
    if (CELL == 0) {
        closeWindow(); // [x] closes even while shaded
        return;
    }

    // Arm a drag. onMouseMove promotes it to an actual move once the cursor
    // travels past a small threshold (dragging the shade relocates the still-
    // hidden window); handleRolledUp treats a release-without-move on the
    // roll-up cell ([<<]) as the un-shade click. Pressing anywhere else on the
    // bar can still drag it, but a plain click there is inert — only the button
    // unrolls.
    m_bRollDragPending   = true;
    m_bRollDragging      = false;
    m_iRollPressCell     = CELL;
    m_rollDragMouseStart = MOUSE;
    m_rollDragBoxStart   = m_rollBox;
    m_rollDragWinStart   = PWINDOW->m_position; // logical box, same as a real drag reads
}

void CVtbDeco::handleRolledUp(Event::SCallbackInfo& info) {
    const bool CANCELLED  = m_bCancelledDown;
    const bool WASPENDING = m_bRollDragPending;
    const bool WASDRAG    = m_bRollDragging;
    const int  PRESSCELL  = m_iRollPressCell;
    m_bCancelledDown   = false;
    m_bRollDragPending = false;
    m_bRollDragging    = false;
    m_iRollPressCell   = -1;

    // Un-shade ONLY when the roll-up cell ([<<]) was clicked without dragging.
    // A plain click elsewhere on the bar does nothing — the button is the only
    // way to unroll (a bare-bar click used to unroll, which was too easy to hit).
    if (WASPENDING && !WASDRAG && PRESSCELL == 4)
        toggleRollup();

    if (CANCELLED)
        info.cancelled = true;
}

// ---- actions --------------------------------------------------------------

void CVtbDeco::closeWindow() {
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW)
        return;
    if (m_bClosing)
        return; // animation already running

    // Only the ordinary floating case gets the roll-up + fade close animation;
    // tiled / minimized / maximized windows just close. The window stays alive
    // (and so does this deco) for the whole animation — we hold sendClose() until
    // the bar has faded out.
    if (!PWINDOW->m_isFloating || m_bMinimized || m_bMaximized) {
        PWINDOW->sendClose();
        return;
    }

    m_bClosing = true;
    if (m_bRolledUp)
        startBarFade();               // already shaded -> straight to the fade-out
    else
        startRollAnim(ROLL_UP);       // roll it up first; finishRollAnim kicks the fade
}

// Begin the tail of the close animation: the lone (shaded) bar fades to nothing.
void CVtbDeco::startBarFade() {
    m_bBarFading      = true;
    m_barFadeProgress = 0.f;
    m_barFadeAt       = Time::steadyNow();
    damageEntire();
}

// Begin the open animation for a freshly-mapped floating window: snapshot +
// hide it (so only the bar shows), then fade the bar in. renderShadeIfRolled
// starts the roll-out reveal once the fade-in completes. Runs from window.open
// (dispatch path), so makeSnapshot is safe here (not mid render-stage).
void CVtbDeco::startOpenReveal() {
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW || !PWINDOW->m_isFloating || m_bRolledUp || m_rollAnim != ROLL_NONE)
        return;

    // A freshly-mapped window is still mid open-animation (value() != goal()), so
    // warp it straight to its settled geometry first — otherwise makeSnapshot
    // captures the half-animated frame and m_rollSnapOrigin (computed off goal())
    // wouldn't line up with where the pixels actually landed in the FB.
    PWINDOW->m_realPosition->setValueAndWarp(PWINDOW->m_realPosition->goal());
    PWINDOW->m_realSize->setValueAndWarp(PWINDOW->m_realSize->goal());

    CBox       g   = {PWINDOW->m_realPosition->value(), PWINDOW->m_realSize->value()};
    const auto WS  = PWINDOW->m_workspace;
    const auto OFF = (WS && !PWINDOW->m_pinned) ? WS->m_renderOffset->value() : Vector2D();
    g.translate(OFF);
    m_rollWinBox = g;

    // The decoration positioner hasn't run yet at window.open, so assignedBoxGlobal()
    // is still 0x0 here — build the bar box directly: it sits on the content's right
    // edge, totalBarW() wide and the window's full height (mirrors frameBox()).
    m_rollBox = {m_rollWinBox.x + m_rollWinBox.w, m_rollWinBox.y, (double)totalBarW(), m_rollWinBox.h};

    g_pHyprRenderer->makeSnapshot(PWINDOW);
    if (PWINDOW->m_snapshotFB && PWINDOW->m_snapshotFB->isAllocated())
        m_rollSnapTex = PWINDOW->m_snapshotFB->getTexture();
    const auto SNAPMON = PWINDOW->m_monitor.lock();
    if (SNAPMON)
        m_rollSnapOrigin = (m_rollWinBox.pos() - SNAPMON->m_position) * SNAPMON->m_scale;

    m_bRolledUp = true;
    hideRolledWindow(PWINDOW);

    // fade the lone bar in; on completion renderShadeIfRolled rolls it out
    m_bOpening        = true;
    m_bBarFadingIn    = true;
    m_barFadeProgress = 0.f;
    m_barFadeAt       = Time::steadyNow();
    damageEntire();
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
    const auto BARW   = totalBarW();
    // Inset by the border width so the window frame stays visible against
    // the screen edges / panel when maximized.
    const auto BS     = PWINDOW->getRealBorderSize() + GAP;
    const CBox usable = PMONITOR->m_reservedArea.apply(CBox{PMONITOR->m_position, PMONITOR->m_size});

    return {usable.x + BS, usable.y + BS, usable.w - BS * 2 - BARW, usable.h - BS * 2};
}

void CVtbDeco::toggleMaximize() {
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW || !PWINDOW->m_isFloating || m_bMinimized || m_bRolledUp)
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

// Windowshade by HIDING the whole window (not resizing it): the window keeps
// its geometry and is marked hidden, so Hyprland stops rendering it and stops
// routing input to it — only this bar remains, drawn by the render-stage hook
// in main.cpp and hit-tested here. Because nothing is moved or resized, this
// works for every app regardless of min size, leaves no client sliver, and —
// key detail — restoring is just an un-hide: the window reappears exactly
// where it is now, never snapping back to some pre-shade position. Floating
// only, and mutually exclusive with maximize/minimize (guarded there too).
// Hide a window being shaded and hand focus to another window on its workspace.
// Split out of the roll-up path because the animation defers the hide to the
// first render frame (the snapshot has to be grabbed while the window is still
// visible).
void CVtbDeco::hideRolledWindow(PHLWINDOW PWINDOW) {
    // Damage the FULL bounding box — border + drop shadow, not just the client
    // rect. Hiding the window stops it (and its shadow decoration) drawing, but
    // only the region we damage gets repainted with what's behind; damaging the
    // bare client box left the border outline and shadow halo as stale pixels.
    CBox stale = PWINDOW->getFullWindowBoundingBox();
    stale.expand(8); // small cushion for shadow blur bleed past the reported extents
    g_pHyprRenderer->damageBox(stale);
    PWINDOW->setHidden(true);

    // hand focus to another visible, non-hidden window on this workspace
    PHLWINDOW next = nullptr;
    for (auto& w : g_pCompositor->m_windows) {
        if (w == PWINDOW || !w->m_isMapped || w->isHidden() || w->m_workspace != PWINDOW->m_workspace)
            continue;
        next = w;
    }
    if (next)
        Desktop::focusState()->fullWindowFocus(next, Desktop::FOCUS_REASON_CLICK);
    else
        Desktop::focusState()->resetWindowFocus();
}

// Eased sub-progress for the two beats. slideT: 0 = content fully out/visible,
// 1 = tucked entirely behind the bar. downT: 0 = raised with full shadow, 1 =
// set down with no shadow. Roll-out runs the beats in the reverse order (lift
// the bar / re-grow the shadow first, then slide the content back out). Returns
// false when no animation is in flight.
bool CVtbDeco::rollAnimSubProgress(float& slideT, float& downT) {
    if (m_rollAnim == ROLL_NONE)
        return false;
    const float g = std::clamp(m_rollProgress, 0.f, 1.f);
    if (m_rollAnim == ROLL_UP) {
        slideT = rollEaseOutCubic(rollRemap(g, 0.f, VTB_ROLL_SLIDE_FRAC));
        downT  = rollEaseInOut(rollRemap(g, VTB_ROLL_SLIDE_FRAC, 1.f));
    } else {
        downT  = 1.f - rollEaseInOut(rollRemap(g, 0.f, 1.f - VTB_ROLL_SLIDE_FRAC));
        slideT = 1.f - rollEaseOutCubic(rollRemap(g, 1.f - VTB_ROLL_SLIDE_FRAC, 1.f));
    }
    return true;
}

// Current set-down fraction: the live animation value, else 1 for a window that
// rests fully rolled up and 0 for one that isn't (drives the bar's dropped
// resting position in effectiveBoxGlobal).
float CVtbDeco::downTNow() {
    float slideT = 0.f, downT = 0.f;
    if (rollAnimSubProgress(slideT, downT))
        return downT;
    return m_bRolledUp ? 1.f : 0.f;
}

void CVtbDeco::startRollAnim(eRollAnim dir) {
    m_rollAnim         = dir;
    m_rollProgress     = 0.f;
    m_rollFinishing    = false;
    m_rollAnimAt       = Time::steadyNow();
    m_iHoverCell       = -1;
    m_bRollDragPending = false;
    m_bRollDragging    = false;

    if (dir == ROLL_UP) {
        const auto PWINDOW = m_pWindow.lock();
        m_rollBox          = assignedBoxGlobal(); // raised bar position
        if (PWINDOW) {
            // client box in the same global-logical frame the shadow/snapshot use
            CBox       g   = {PWINDOW->m_realPosition->value(), PWINDOW->m_realSize->value()};
            const auto WS  = PWINDOW->m_workspace;
            const auto OFF = (WS && !PWINDOW->m_pinned) ? WS->m_renderOffset->value() : Vector2D();
            g.translate(OFF);
            m_rollWinBox = g;

            // Capture the window's pixels NOW, while it's still visible and we're
            // OUTSIDE the render loop (this runs from the input / dispatch path,
            // the same context Hyprland snapshots closing windows from). Doing it
            // mid render-stage re-enters the renderer and corrupts the in-flight
            // frame -> hard crash. m_rollSnapTex keeps the texture alive for the
            // whole shade (both the roll-up slide and the eventual roll-out).
            g_pHyprRenderer->makeSnapshot(PWINDOW);
            if (PWINDOW->m_snapshotFB && PWINDOW->m_snapshotFB->isAllocated())
                m_rollSnapTex = PWINDOW->m_snapshotFB->getTexture();
            // makeSnapshot renders into a MONITOR-sized framebuffer, so the window
            // is only a sub-rect of the texture; remember its device-px top-left
            // there so drawRollSnapshot can sample just the window, not the whole
            // screen scaled down into the bar.
            const auto SNAPMON = PWINDOW->m_monitor.lock();
            if (SNAPMON)
                m_rollSnapOrigin = (m_rollWinBox.pos() - SNAPMON->m_position) * SNAPMON->m_scale;
        }
        m_bRolledUp = true; // the bar is now the standalone floating bar
        if (PWINDOW)
            hideRolledWindow(PWINDOW);
    }
    // ROLL_OUT: the window is already hidden and m_rollSnapTex still holds its
    // (frozen) pixels from roll-up — nothing to capture. Focus it NOW, at the
    // very start of the reveal, so Hyprland's border-colour fade animates to the
    // focused/active tint DURING the roll-out (the anim ticks even while the
    // window is hidden) instead of only snapping active after it lands. Also wake
    // the client early so it starts repainting.
    if (dir == ROLL_OUT) {
        m_bRollReveal = false;
        if (const auto PWINDOW = m_pWindow.lock()) {
            Desktop::focusState()->fullWindowFocus(PWINDOW, Desktop::FOCUS_REASON_CLICK);
            VtbIpc::sendWake(appPid());
        }
    }

    damageEntire();
}

void CVtbDeco::stepRollAnim() {
    if (m_rollAnim == ROLL_NONE || m_rollFinishing)
        return;
    const auto  now = Time::steadyNow();
    const float dt  = std::chrono::duration<float>(now - m_rollAnimAt).count();
    m_rollAnimAt    = now;
    m_rollProgress += dt / VTB_ROLL_DURATION;
    if (m_rollProgress >= 1.f) {
        m_rollProgress = 1.f;

        // Roll-out reveal hold: the slide has landed (slideT==0, so the snapshot
        // now fully covers the content at its final resting spot). Un-hide the
        // real window UNDER that still-drawn snapshot so it repaints while hidden
        // behind it, and keep covering it for VTB_ROLL_REVEAL_HOLD before dropping
        // the snapshot — otherwise the client's black first-frame flashed through.
        if (m_rollAnim == ROLL_OUT) {
            if (!m_bRollReveal) {
                // un-hiding / refocusing / reordering isn't safe mid render-stage
                // (same reason finishRollAnim is deferred), so arm the guard and
                // hold clock now and do the window work on the next loop turn.
                m_bRollReveal  = true;
                m_rollRevealAt = now;
                WP<CVtbDeco> self = m_self;
                g_pEventLoopManager->doLater([self]() {
                    if (auto d = self.lock())
                        d->beginRollReveal();
                });
                return; // stay in ROLL_OUT; the hold elapses over the next frames
            }
            if (std::chrono::duration<float>(now - m_rollRevealAt).count() < VTB_ROLL_REVEAL_HOLD)
                return; // still covering; let the client finish painting
        }

        m_rollFinishing = true;
        // finalize OUT of the render loop — finishRollAnim un-hides / refocuses /
        // reorders the window, none of which is safe to do mid render-stage. The
        // frame(s) until it fires render the terminal look (progress==1), which
        // is visually identical to the settled state, so there's no seam.
        WP<CVtbDeco> self = m_self;
        g_pEventLoopManager->doLater([self]() {
            if (auto d = self.lock())
                d->finishRollAnim();
        });
    }
}

// Roll-out slide has landed: bring the window back to life NOW, under the still-
// drawn snapshot, so it repaints before the snapshot is dropped (see the hold
// note above). Deferred out of stepRollAnim via doLater — the un-hide/focus/
// reorder here is not safe mid render-stage. Everything except dropping the
// snapshot mirrors the ROLL_OUT branch of finishRollAnim; that runs after the
// hold to tear the snapshot down. m_bRollReveal / m_rollRevealAt were already
// set by the caller so the hold clock starts when it armed, not when this fires.
void CVtbDeco::beginRollReveal() {
    if (m_rollAnim != ROLL_OUT) // superseded (e.g. re-rolled) before this fired
        return;
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW)
        return;
    PWINDOW->setHidden(false);
    g_pCompositor->changeWindowZOrder(PWINDOW, true);
    Desktop::focusState()->fullWindowFocus(PWINDOW, Desktop::FOCUS_REASON_CLICK);
    // Re-register Hyprland's own decorations (border/shadow) for the freshly
    // un-hidden window. Without this an INITIAL open reveal came up with no
    // window border at all until the first move (which repositions the decos and
    // re-adds them); a move is exactly what this call stands in for.
    PWINDOW->updateWindowDecos();
    warpBorderToFocused(PWINDOW);
    VtbIpc::sendWake(appPid());
    // paint the live window (still under the snapshot) as one full frame
    CBox full = PWINDOW->getFullWindowBoundingBox();
    full.expand(VTB_SHADOW_SIZE + 4);
    g_pHyprRenderer->damageBox(full);
}

// Snap a just-un-hidden window's border straight to its focused colour instead
// of letting it EASE there. Hyprland doesn't tick the border-fade animation
// while a window is hidden, so on un-hide the fade starts from the stale
// (inactive) tint and crossfades to active over ~185ms — which read as "the
// border only turns focused a beat AFTER the unroll finished", even though the
// window was focused when it un-hid. The fullWindowFocus that precedes each call
// already re-pointed the fade at the active colour; we just complete it in place
// by warping the progress to its goal. (We deliberately do NOT call
// onFocusAnimUpdate here — on a freshly-mapped window it left the border colour
// in a state Hyprland wouldn't render until the next move, so the initial
// window opened with no border at all.)
void CVtbDeco::warpBorderToFocused(PHLWINDOW pWindow) {
    if (!pWindow || !pWindow->m_borderFadeAnimationProgress)
        return;
    pWindow->m_borderFadeAnimationProgress->setValueAndWarp(pWindow->m_borderFadeAnimationProgress->goal());
}

void CVtbDeco::finishRollAnim() {
    const auto      PWINDOW = m_pWindow.lock();
    const eRollAnim dir     = m_rollAnim;
    m_rollAnim              = ROLL_NONE;
    m_rollProgress          = 1.f;
    m_rollFinishing         = false;

    if (dir == ROLL_OUT) {
        // the window comes back to life at its original geometry. It was already
        // un-hidden/focused during the reveal hold (beginRollReveal); dropping
        // the snapshot here is the last step — the client has repainted under it
        // by now, so no black frame shows through.
        m_bRolledUp        = false;
        m_bRollReveal      = false;
        m_iHoverCell       = -1;
        m_bRollDragPending = false;
        m_bRollDragging    = false;
        m_bOpening         = false; // open reveal (if any) is done
        m_rollSnapTex      = nullptr;
        if (PWINDOW) {
            PWINDOW->setHidden(false);
            g_pCompositor->changeWindowZOrder(PWINDOW, true);
            Desktop::focusState()->fullWindowFocus(PWINDOW, Desktop::FOCUS_REASON_CLICK);
            PWINDOW->updateWindowDecos(); // re-add Hyprland's border/shadow (see beginRollReveal)
            warpBorderToFocused(PWINDOW); // border already active from the hold; keep it snapped
            // the surface was hidden; nudge the client to repaint (QtWebEngine
            // presents black after its surface is un-hidden until it redraws)
            VtbIpc::sendWake(appPid());
            // Damage the FULL frame as one region — client body, the right-edge
            // titlebar deco, the border wrapping both, and the drop shadow — so
            // every side repaints on the same frame. Damaging only the bar box
            // (m_rollBox) left the border/titlebar on the wide right edge to
            // repaint a frame or two late, so it flashed / appeared after the
            // other three sides.
            CBox full = PWINDOW->getFullWindowBoundingBox();
            full.expand(VTB_SHADOW_SIZE + 4);
            g_pHyprRenderer->damageBox(full);
        }
    }
    // ROLL_UP: the window stays hidden; the bar simply settles into its dropped
    // resting state (downTNow() now reads 1 off m_bRolledUp). If this roll-up was
    // the first half of a close, start the tail bar fade-out now.
    if (dir == ROLL_UP && m_bClosing)
        startBarFade();

    damageEntire();
}

// Roll-up windowshade toggle. Animated by default (drawer slide + set-down);
// the session-restore path passes animate=false to snap straight to the rolled
// state at login. Floating only, mutually exclusive with maximize/minimize.
// Re-entry while an animation is in flight is ignored.
void CVtbDeco::toggleRollup(bool animate) {
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW || !PWINDOW->m_isFloating || m_bMinimized || m_bMaximized)
        return;
    if (m_rollAnim != ROLL_NONE)
        return;

    if (animate) {
        startRollAnim(m_bRolledUp ? ROLL_OUT : ROLL_UP);
        return;
    }

    // instant path (no animation): straight to the target state
    if (m_bRolledUp) {
        m_bRolledUp        = false;
        m_iHoverCell       = -1;
        m_bRollDragPending = false;
        m_bRollDragging    = false;
        m_rollSnapTex      = nullptr;
        g_pHyprRenderer->damageBox(m_rollBox);
        PWINDOW->setHidden(false);
        g_pCompositor->changeWindowZOrder(PWINDOW, true);
        Desktop::focusState()->fullWindowFocus(PWINDOW, Desktop::FOCUS_REASON_CLICK);
        VtbIpc::sendWake(appPid());
        damageEntire();
        return;
    }

    m_rollBox          = assignedBoxGlobal();
    m_bRolledUp        = true;
    m_iHoverCell       = -1;
    m_bRollDragPending = false;
    m_bRollDragging    = false;
    hideRolledWindow(PWINDOW);
    damageEntire(); // draws the bar at its dropped resting position
}

// Enqueue the shaded window's bar (and, mid-animation, its sliding snapshot +
// drop shadow) into the current frame's render pass. Called per-monitor from
// main.cpp's render-stage hook (a hidden window gets no draw() of its own), and
// also drives the roll-up / roll-out animation clock. Skips monitors/workspaces
// the shade isn't showing on.
void CVtbDeco::renderShadeIfRolled(PHLMONITOR pMonitor) {
    if (!g_pGlobalState || !g_pGlobalState->config.enabled->value())
        return;
    if (!m_bRolledUp && m_rollAnim == ROLL_NONE)
        return;

    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW || !pMonitor || PWINDOW->m_monitor.lock() != pMonitor)
        return;
    if (!PWINDOW->m_pinned && (!PWINDOW->m_workspace || !PWINDOW->m_workspace->isVisible()))
        return;

    stepRollAnim();

    // roll-out just landed: the window is live again, nothing here to draw (it
    // renders its own decorations this same frame, past this render stage)
    if (!m_bRolledUp && m_rollAnim == ROLL_NONE)
        return;

    // keep frames coming until the animation lands: damage the whole reach of
    // the slide + shadow so the next frame repaints it
    if (m_rollAnim != ROLL_NONE) {
        const double L = m_rollWinBox.x - VTB_SHADOW_SIZE;
        const double R = m_rollBox.x + m_rollBox.w;
        const double H = std::max(m_rollBox.h, m_rollWinBox.h) + 2 * VTB_SHADOW_SIZE;
        g_pHyprRenderer->damageBox(CBox{L, m_rollBox.y - VTB_SHADOW_SIZE, R - L, H});
    }

    // Lone-bar fade, shared by open (fade IN, then roll out) and close (roll up,
    // then fade OUT and ask the client to close). Only one is ever active.
    float barA = 1.f;
    if (m_bBarFadingIn || m_bBarFading) {
        const auto  now = Time::steadyNow();
        const float dt  = std::chrono::duration<float>(now - m_barFadeAt).count();
        m_barFadeAt     = now;
        m_barFadeProgress = std::min(1.f, m_barFadeProgress + dt / VTB_FADE_DURATION);
        barA              = m_bBarFadingIn ? m_barFadeProgress : (1.f - m_barFadeProgress);

        if (m_barFadeProgress < 1.f) {
            g_pHyprRenderer->damageBox(CBox{m_rollBox}.expand(VTB_SHADOW_SIZE)); // keep frames coming
        } else if (m_bBarFadingIn) {
            // open: bar is fully in — now roll the content out to reveal it. The
            // roll-out reuses the snapshot captured in startOpenReveal.
            m_bBarFadingIn = false;
            barA           = 1.f;
            startRollAnim(ROLL_OUT);
        } else if (!m_bCloseReady) {
            // close: bar has faded to nothing — actually close the window now,
            // deferred off the render loop (the window's own weak-ref is reliable,
            // unlike our self-ref).
            m_bCloseReady = true;
            g_pHyprRenderer->damageBox(CBox{m_rollBox}.expand(VTB_SHADOW_SIZE)); // final clear of the bar
            PHLWINDOWREF w = m_pWindow;
            g_pEventLoopManager->doLater([w]() {
                if (auto win = w.lock())
                    win->sendClose();
            });
        }
    }

    auto data = CVtbPassElement::SVtbData{this, barA};
    g_pHyprRenderer->m_renderPass.add(makeUnique<CVtbPassElement>(data));
}

void CVtbDeco::minimizeWindow() {
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW || !PWINDOW->m_isFloating || m_bMinimized || m_bRolledUp)
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
    g_pHyprRenderer->damageBox(effectiveBoxGlobal());
}

eDecorationLayer CVtbDeco::getDecorationLayer() {
    return DECORATION_LAYER_UNDER;
}

uint64_t CVtbDeco::getDecorationFlags() {
    return DECORATION_ALLOWS_MOUSE_INPUT | DECORATION_PART_OF_MAIN_WINDOW;
}

// ---- CVtbShadowDeco: bottom-left hard drop shadow -------------------------

CVtbShadowDeco::CVtbShadowDeco(PHLWINDOW pWindow) : IHyprWindowDecoration(pWindow), m_pWindow(pWindow) {
    ;
}

CVtbShadowDeco::~CVtbShadowDeco() {
    ;
}

SDecorationPositioningInfo CVtbShadowDeco::getPositioningInfo() {
    SDecorationPositioningInfo info;
    info.policy   = DECORATION_POSITION_ABSOLUTE;
    info.edges    = DECORATION_EDGE_LEFT | DECORATION_EDGE_BOTTOM;
    info.priority = 5;      // below the titlebar; order among non-solid decos is irrelevant
    info.reserved = false;  // must NOT inset the window — this is just a shadow
    // Declare the shadow's reach so a moving window's damage box includes it:
    // left + bottom for the L-overhang, and right for the titlebar strip the
    // shadow now spans (so its under-bar bottom edge doesn't trail on moves).
    const double BARW = g_pGlobalState && g_pGlobalState->config.enabled->value() ? (double)totalBarW() : 0.0;
    info.desiredExtents = {{(double)VTB_SHADOW_SIZE, 0.0}, {BARW, (double)VTB_SHADOW_SIZE}};
    return info;
}

void CVtbShadowDeco::onPositioningReply(const SDecorationPositioningReply& reply) {
    m_bAssignedBox = reply.assignedGeometry; // empty for ABSOLUTE; we position off the window
}

void CVtbShadowDeco::draw(PHLMONITOR pMonitor, const float& a) {
    if (!validMapped(m_pWindow) || !g_pGlobalState || !g_pGlobalState->config.enabled->value())
        return;

    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW->m_ruleApplicator->decorate().valueOrDefault() || PWINDOW->isFullscreen())
        return;

    // no shadow on our custom-maximized windows, nor on a rolled-up one (the
    // sibling titlebar knows). A rolled-up window is hidden and its lone bar
    // casts no shadow at rest — but this bottom-layer deco still gets drawn for
    // the hidden window, so without this guard dragging the bar drags a stale
    // hard shadow that trails and flashes. isRolledUp() stays true across the
    // whole roll-up/roll-out animation too, where drawRollShadow owns the shadow.
    for (auto& b : g_pGlobalState->bars) {
        if (b && b->getOwner() == PWINDOW) {
            if (b->isMaximized() || b->isRolledUp())
                return;
            break;
        }
    }

    const auto SCALE = pMonitor->m_scale;

    // Global window box with the same workspace-slide + floating-drag offsets
    // the titlebar uses, so the shadow tracks the window through animations.
    CBox       g   = {PWINDOW->m_realPosition->value(), PWINDOW->m_realSize->value()};
    const auto WS  = PWINDOW->m_workspace;
    const auto OFF = (WS && !PWINDOW->m_pinned) ? WS->m_renderOffset->value() : Vector2D();
    g.translate(OFF);

    CBox local = {g.x - pMonitor->m_position.x, g.y - pMonitor->m_position.y, g.w, g.h};
    local.translate(PWINDOW->m_floatingOffset).scale(SCALE).round();
    if (local.w < 1 || local.h < 1)
        return;

    // Frame-sized rect offset down and left; NON_SOLID + BOTTOM layer means the
    // window (and its titlebar) covers the centre and only the sharp L-overhang
    // shows. m_realSize is the client surface only — the titlebar is a reserved
    // deco on the RIGHT edge, so the visible frame is that much wider; widen the
    // shadow to match or the whole bar column casts nothing.
    const double N    = VTB_SHADOW_SIZE * SCALE;
    const double BARW = totalBarW() * SCALE;
    CBox         shadowBox = {local.x - N, local.y + N, local.w + BARW, local.h};
    shadowBox.round();

    // Self-damage on motion. Hyprland's per-frame drag/animation damage covers
    // the window + border but NOT this custom bottom-layer deco's left+bottom
    // overhang (the now-disabled native drop shadow used to incidentally cover
    // it), so a moving window trailed the hard shadow's left edge. Whenever the
    // footprint moves, damage its old ∪ new (global-logical, incl. the drag's
    // floatingOffset) so the trailing edge repaints. Stable when the window is.
    const auto&  FO     = PWINDOW->m_floatingOffset;
    CBox         coverG = {g.x + FO.x - VTB_SHADOW_SIZE, g.y + FO.y, g.w + VTB_SHADOW_SIZE + totalBarW(), g.h + VTB_SHADOW_SIZE};
    if (coverG.x != m_lastCoverBox.x || coverG.y != m_lastCoverBox.y || coverG.w != m_lastCoverBox.w || coverG.h != m_lastCoverBox.h) {
        if (m_lastCoverBox.w > 0)
            g_pHyprRenderer->damageBox(CBox{m_lastCoverBox}.expand(2));
        g_pHyprRenderer->damageBox(CBox{coverG}.expand(2));
        m_lastCoverBox = coverG;
    }

    CHyprColor color = {0.0, 0.0, 0.0, 0.6}; // hard, near-solid black
    color.a *= a;

    CRectPassElement::SRectData data;
    data.box   = shadowBox;
    data.color = color;
    g_pHyprRenderer->m_renderPass.add(makeUnique<CRectPassElement>(data));
}

void CVtbShadowDeco::damageEntire() {
    if (!validMapped(m_pWindow))
        return;
    const auto PWINDOW = m_pWindow.lock();
    CBox       g = {PWINDOW->m_realPosition->value(), PWINDOW->m_realSize->value()};
    const double N    = VTB_SHADOW_SIZE;
    const double BARW = g_pGlobalState && g_pGlobalState->config.enabled->value() ? (double)totalBarW() : 0.0;
    // window box grown by the shadow's left + bottom overhang, plus the titlebar
    // strip on the right (the shadow now spans it too)
    g_pHyprRenderer->damageBox(CBox{g.x - N, g.y, g.w + N + BARW, g.h + N});
}

eDecorationType CVtbShadowDeco::getDecorationType() {
    return DECORATION_CUSTOM;
}

void CVtbShadowDeco::updateWindow(PHLWINDOW) {
    damageEntire();
}

eDecorationLayer CVtbShadowDeco::getDecorationLayer() {
    return DECORATION_LAYER_BOTTOM;
}

uint64_t CVtbShadowDeco::getDecorationFlags() {
    return DECORATION_NON_SOLID;
}

std::string CVtbShadowDeco::getDisplayName() {
    return "HyprvtbShadow";
}

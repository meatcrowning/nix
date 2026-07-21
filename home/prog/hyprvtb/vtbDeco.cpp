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
#include <hyprland/src/managers/cursor/CursorShapeOverrideController.hpp>

#include <pango/pangocairo.h>
#include <xkbcommon/xkbcommon.h>
#include <xkbcommon/xkbcommon-keysyms.h>
#include <cmath>
#include <chrono>
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

// Walk the app-button column's layout: calls cb(index, y) for every real
// button cell (spacers advance y without a cell). Single source of truth for
// both drawing and hit-testing.
template <typename F>
static void walkAppCells(const std::vector<SVtbAppButton>& btns, F&& cb) {
    double y = VTB_PAD;
    for (size_t i = 0; i < btns.size(); i++) {
        if (btns[i].isSep()) {
            y += VTB_SEP_H + VTB_CELL_GAP;
            continue;
        }
        cb(i, y);
        y += cellSize() + VTB_CELL_GAP;
    }
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

    CBox box = m_bAssignedBox;
    box.translate(g_pDecorationPositioner->getEdgeDefinedPoint(DECORATION_EDGE_RIGHT, m_pWindow.lock()));

    const auto PWORKSPACE      = m_pWindow->m_workspace;
    const auto WORKSPACEOFFSET = PWORKSPACE && !m_pWindow->m_pinned ? PWORKSPACE->m_renderOffset->value() : Vector2D();

    return box.translate(WORKSPACEOFFSET);
}

// While shaded the window is hidden and its geometry is frozen, so the bar is
// drawn/hit-tested against the box captured at shade time; otherwise it tracks
// the live decoration position.
CBox CVtbDeco::effectiveBoxGlobal() {
    return m_bRolledUp ? m_rollBox : assignedBoxGlobal();
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
    borderColor.a *= a;

    // Buttons + title follow the window's frame: accent (active-border
    // colour) when focused, the inactive-border grey otherwise.
    const auto textColor = FOCUSED ? accentColor : inactiveColor;

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

    // the five system cells live in the OUTER column
    auto drawCell = [&](int idx, const CHyprColor& hot, bool active) {
        const double y = VTB_PAD + idx * (CELL + VTB_CELL_GAP);
        drawCellXY(sysColX(), y, hot, m_iHoverCell == idx || active, cellFlashing(idx));
    };

    auto drawGlyph = [&](int idx, const std::string& glyph, const CHyprColor& color) {
        drawGlyphXY(sysColX(), VTB_PAD + idx * (CELL + VTB_CELL_GAP), glyph, cellFlashing(idx) ? bgColor : color);
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

    // pin [o>] — Hyprland pin: keeps the window on top and on every
    // workspace. Lit accent while pinned, like maximize while maximized.
    const bool PINNED = PWINDOW->m_pinned;
    drawCell(3, accentColor, PINNED);
    drawGlyph(3, "o>", (PINNED || m_iHoverCell == 3) ? accentColor : textColor);

    // roll-up — windowshade toggle: [>>] hides the window down to just this
    // bar; while shaded it shows [<<] to roll it back. Lit accent while shaded.
    drawCell(4, accentColor, m_bRolledUp);
    drawGlyph(4, m_bRolledUp ? "<<" : ">>", (m_bRolledUp || m_iHoverCell == 4) ? accentColor : textColor);

    // ---- title, a column of upright letters (outer column, under the cells) ----
    // In edit mode the same region becomes the address editor: it shows the
    // live edit buffer, a caret (or an inverted block when the whole field is
    // selected), instead of the window title.
    const int    RUNLEN = std::round((DECOBOX.h - titleTop() - VTB_PAD) * SCALE);
    const double TITLEX = barBox.x + titleTexX() * SCALE;
    const double TITLEY = barBox.y + titleTop() * SCALE;

    if (m_bEditing) {
        if (!m_pEditTex) {
            int th = 0, lines = 0;
            // a blank buffer still needs a texture so the caret has a line to sit on
            const std::string SHOWN = m_editBuf.empty() ? std::string(" ") : m_editBuf;
            m_pEditTex   = renderStackedTex(SHOWN, RUNLEN, SCALE, m_editSelectAll ? bgColor : textColor, &th, &lines, /*ellipsis=*/false);
            m_iEditLineH = lines > 0 ? th / lines : std::round(g_pGlobalState->config.fontSize->value() * SCALE);
            m_iEditLines = lines;
        }
        if (m_pEditTex && m_pEditTex->m_texID != 0) {
            const auto TSZ = m_pEditTex->m_size;
            // whole-field selection: an accent block behind the (bg-coloured)
            // text, sized to the real text height (not the full column run)
            if (m_editSelectAll) {
                const double selH = std::min((double)TSZ.y, (double)(m_iEditLineH * std::max(1, m_iEditLines)));
                CBox         sel  = {TITLEX, TITLEY, TSZ.x, selH};
                g_pHyprOpenGL->renderRect(sel.round(), accentColor, {});
            }
            CBox tbox = {TITLEX, TITLEY, TSZ.x, TSZ.y};
            g_pHyprOpenGL->renderTexture(m_pEditTex, tbox.round(), {.a = a});
        }
        // caret: a horizontal bar between codepoint rows at the cursor, blinking
        // ~500ms. Not drawn while the whole field is selected (the block shows it).
        if (!m_editSelectAll && m_iEditLineH > 0) {
            const long ms      = std::chrono::duration_cast<std::chrono::milliseconds>(Time::steadyNow() - m_editBlinkAt).count();
            const bool blinkOn = (ms / 500) % 2 == 0;
            if (blinkOn) {
                int caretLine = countCp(m_editBuf, m_editCursor);
                const int maxLine = std::max(0, RUNLEN / std::max(1, m_iEditLineH));
                caretLine       = std::clamp(caretLine, 0, maxLine);
                const double cy = TITLEY + caretLine * (double)m_iEditLineH;
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

    // ---- inner column: app-registered buttons + stacked footer (vtbIpc) ----
    m_lastIpcSerial = VtbIpc::serial.load(std::memory_order_relaxed);
    SVtbAppReg reg;
    if (VtbIpc::get(appPid(), reg)) {
        // separators ("-"): a thin divider line centred in the separator gap
        // (surfer's rule under copy-url, above the tab buttons)
        {
            double sy = VTB_PAD;
            for (size_t i = 0; i < reg.buttons.size(); i++) {
                if (reg.buttons[i].isSep()) {
                    if (sy + VTB_SEP_H <= DECOBOX.h - VTB_PAD) {
                        auto sc = textColor;
                        sc.a *= a;
                        g_pHyprOpenGL->renderRect(localBox(innerColX() + 2, sy + VTB_SEP_H / 2.0, cellSize() - 4, 1), sc, {});
                    }
                    sy += VTB_SEP_H + VTB_CELL_GAP;
                } else {
                    sy += CELL + VTB_CELL_GAP;
                }
            }
        }

        double appBottom = VTB_PAD; // where the buttons end (footer must stay below)
        walkAppCells(reg.buttons, [&](size_t i, double y) {
            if (y + CELL > DECOBOX.h - VTB_PAD)
                return; // window too short for this cell — clip, don't overlap
            appBottom = y + CELL;

            const auto& b        = reg.buttons[i];
            const bool  disabled = b.state == 2;
            const bool  hovered  = m_iHoverCell == (int)(VTB_APPCELL + i);
            const bool  lit      = !disabled && (hovered || b.state == 1);
            // lit cells grey to the inactive tone on unfocused windows, like
            // the old in-window strip did (win.fgAccent)
            const auto& litCol   = FOCUSED ? accentColor : inactiveColor;

            const bool flashing = cellFlashing(VTB_APPCELL + (int)i);
            drawCellXY(innerColX(), y, litCol, lit, flashing);
            // disabled cells dim to the inactive grey, like filer's 0.4-opacity look
            drawGlyphXY(innerColX(), y, b.label, flashing ? bgColor : (disabled ? inactiveColor : (lit ? litCol : textColor)));
        });

        // footer: short stacked text pinned to the bottom of the inner column
        // (filer's dir-size readout). Rendered with the same pango path as the
        // title; skipped if the window is too short to fit any of it.
        const int FRUNLEN = std::round((DECOBOX.h - appBottom - VTB_PAD * 2) * SCALE);
        if (reg.footer != m_szLastFooter || FRUNLEN != m_iLastFooterRun || !m_pFooterTex) {
            m_szLastFooter   = reg.footer;
            m_iLastFooterRun = FRUNLEN;
            m_iFooterTextH   = 0;
            m_pFooterTex     = renderStackedTex(reg.footer, FRUNLEN, SCALE, textColor, &m_iFooterTextH);
        }
        if (m_pFooterTex && m_pFooterTex->m_texID != 0) {
            // the texture's glyphs start at its top; bottom-anchor using the real
            // pango text height so the readout hugs the bar's bottom edge
            const auto TSZ  = m_pFooterTex->m_size;
            CBox       fbox = {barBox.x + footerTexX() * SCALE, barBox.y + barBox.h - VTB_PAD * SCALE - m_iFooterTextH, TSZ.x, TSZ.y};
            g_pHyprOpenGL->renderTexture(m_pFooterTex, fbox.round(), {.a = a});
        }

        // drag-reorder feedback: an accent insertion bar at the target slot and
        // a lifted copy of the dragged button following the cursor's Y.
        if (m_bAppDragging && m_iAppDragTarget >= 0) {
            double tgtY = -1, srcY = -1;
            walkAppCells(reg.buttons, [&](size_t i, double y) {
                if ((int)i == m_iAppDragTarget)
                    tgtY = y;
                if ((int)i == m_iAppPressIdx)
                    srcY = y;
            });
            if (tgtY >= 0) {
                auto ac = accentColor;
                ac.a *= a;
                g_pHyprOpenGL->renderRect(localBox(innerColX(), tgtY - VTB_CELL_GAP / 2.0 - 1, CELL, 2), ac, {});
            }
            // lifted cell at the cursor's Y (clamped into the column)
            const auto  MOUSELOCAL = g_pInputManager->getMouseCoordsInternal() - assignedBoxGlobal().pos();
            const double liftY     = std::clamp(MOUSELOCAL.y - CELL / 2.0, (double)VTB_PAD, DECOBOX.h - VTB_PAD - CELL);
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

    // NOTE: the hover tooltip is NOT drawn here — this pass element is an
    // UNDER-layer decoration (drawn before the window surface), and the tooltip
    // overhangs the window to the left, so drawing it here would put it behind
    // the window. It's enqueued separately at RENDER_POST_WINDOWS; see
    // enqueueTooltip / drawTooltipPass.
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
            walkAppCells(reg.buttons, [&](size_t i, double y) {
                if (i == want)
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
    if (!validMapped(m_pWindow))
        return;

    // registration changed since the last render -> repaint the bar (covers
    // sort-arrow flips after a click, surfer's loading state, etc., without
    // waiting for the mouse to move)
    if (ipcSerial != m_lastIpcSerial) {
        m_lastIpcSerial = ipcSerial;
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
    if (m_iHoverCell != -1 && !m_bMinimized && !alreadyShowingHover &&
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
    walkAppCells(reg.buttons, [&](size_t i, double y) {
        if (c.y >= y && c.y <= y + cellSize())
            hit = (int)i;
    });
    return hit;
}

// Nearest DRAGGABLE app slot to the cursor's Y (the reorder drop target) — the
// reorder is confined to the draggable group (surfer's tabs); -1 if none.
int CVtbDeco::appDropSlot(const Vector2D& c, const SVtbAppReg& reg) {
    int    best     = -1;
    double bestDist = 1e9;
    const int CELL  = cellSize();
    walkAppCells(reg.buttons, [&](size_t i, double y) {
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

// The clickable address-bar region: the outer column band from the title top
// down (where the stacked title texture is drawn).
bool CVtbDeco::inTitleRegion(const Vector2D& c) {
    return c.y >= titleTop() && c.x >= sysColX() && c.x <= sysColX() + cellSize();
}

void CVtbDeco::enterEdit() {
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW)
        return;
    m_editBuf       = PWINDOW->m_title; // seed with the current address (surfer sets title = URL)
    m_editCursor    = m_editBuf.size();
    m_editSelectAll = true;             // click-to-edit selects the whole field, like a browser
    m_bEditing      = true;
    m_pEditTex      = nullptr;
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
    m_editSelectAll = false;
    m_pEditTex      = nullptr;
    damageEntire();
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

    // whole-field selection drops on the first edit, replacing/collapsing it
    if (m_editSelectAll) {
        switch (sym) {
            case XKB_KEY_Left:
            case XKB_KEY_Home: m_editCursor = 0; m_editSelectAll = false; damageEntire(); return;
            case XKB_KEY_Right:
            case XKB_KEY_End: m_editCursor = m_editBuf.size(); m_editSelectAll = false; damageEntire(); return;
            case XKB_KEY_BackSpace:
            case XKB_KEY_Delete: m_editBuf.clear(); m_editCursor = 0; m_editSelectAll = false; m_pEditTex = nullptr; damageEntire(); return;
            default: break; // printable: replace the whole field
        }
        m_editBuf.clear();
        m_editCursor    = 0;
        m_editSelectAll = false;
        m_pEditTex      = nullptr;
    }

    switch (sym) {
        case XKB_KEY_Left: m_editCursor = prevCp(m_editBuf, m_editCursor); damageEntire(); return;
        case XKB_KEY_Right: m_editCursor = nextCp(m_editBuf, m_editCursor); damageEntire(); return;
        case XKB_KEY_Home: m_editCursor = 0; damageEntire(); return;
        case XKB_KEY_End: m_editCursor = m_editBuf.size(); damageEntire(); return;
        case XKB_KEY_BackSpace: {
            if (m_editCursor > 0) {
                const size_t p = prevCp(m_editBuf, m_editCursor);
                m_editBuf.erase(p, m_editCursor - p);
                m_editCursor = p;
                m_pEditTex   = nullptr;
                damageEntire();
            }
            return;
        }
        case XKB_KEY_Delete: {
            if (m_editCursor < m_editBuf.size()) {
                const size_t nx = nextCp(m_editBuf, m_editCursor);
                m_editBuf.erase(m_editCursor, nx - m_editCursor);
                m_pEditTex = nullptr;
                damageEntire();
            }
            return;
        }
        default: break;
    }

    if (printable) {
        m_editBuf.insert(m_editCursor, utf8, n);
        m_editCursor += n;
        m_pEditTex = nullptr;
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
            handleRolledUp(info);
            return;
        }
        handleUpEvent(info);
        return;
    }

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

    // App-button registrations change on the I/O thread, which can't touch the
    // renderer; this main-thread hook notices the bump and damages the bar so
    // new/changed buttons appear. (Most changes coincide with client-driven
    // damage anyway — this catches the stragglers.)
    const uint64_t IPCSERIAL = VtbIpc::serial.load(std::memory_order_relaxed);
    if (IPCSERIAL != m_lastIpcSerial) {
        m_lastIpcSerial = IPCSERIAL;
        damageEntire();
    }

    if (m_bEdgeResizing) {
        updateEdgeResize();
        return;
    }

    // shaded window: either drag its floating bar (relocating the hidden
    // window) or just hover-test it — no resize cursor.
    if (m_bRolledUp) {
        if (m_bRollDragPending || m_bRollDragging) {
            const auto DELTA = g_pInputManager->getMouseCoordsInternal() - m_rollDragMouseStart;
            if (!m_bRollDragging && (std::abs(DELTA.x) + std::abs(DELTA.y)) > 4)
                m_bRollDragging = true;
            if (m_bRollDragging) {
                const auto PWINDOW = m_pWindow.lock();
                g_pHyprRenderer->damageBox(m_rollBox); // clear the bar's old spot
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
                damageEntire();
            }
            return;
        }

        const auto LOCAL = g_pInputManager->getMouseCoordsInternal() - m_rollBox.pos();
        const int  cell  = VECINRECT(LOCAL, 0, 0, m_rollBox.w, m_rollBox.h) ? cellAt(LOCAL) : -1;
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

    if (Desktop::focusState()->window() != PWINDOW)
        Desktop::focusState()->fullWindowFocus(PWINDOW, Desktop::FOCUS_REASON_CLICK);

    if (PWINDOW->m_isFloating)
        g_pCompositor->changeWindowZOrder(PWINDOW, true);

    info.cancelled   = true;
    m_bCancelledDown = true;
    hideTooltip(); // a press dismisses the hover label

    // address editor already open: clicking the field re-selects the whole
    // address; a press anywhere else on the bar cancels the edit and proceeds.
    if (m_bEditing) {
        if (titleEditEnabled() && inTitleRegion(COORDS)) {
            m_editSelectAll = true;
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
    // here still moves the window (promoted on move), so just arm both.
    if (titleEditEnabled() && inTitleRegion(COORDS)) {
        m_bTitlePressPending = true;
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
    // address editor.
    if (m_bTitlePressPending) {
        const bool wasDrag   = m_bDraggingThis;
        m_bTitlePressPending = false;
        if (m_bDraggingThis) {
            g_pKeybindManager->changeMouseBindMode(MBIND_INVALID);
            m_bDraggingThis = false;
        }
        m_bDragPending = false;
        if (!wasDrag && !m_bEditing)
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

    const auto MOUSE = g_pInputManager->getMouseCoordsInternal();
    const auto LOCAL = MOUSE - m_rollBox.pos();
    if (!VECINRECT(LOCAL, 0, 0, m_rollBox.w, m_rollBox.h))
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
void CVtbDeco::toggleRollup() {
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW || !PWINDOW->m_isFloating || m_bMinimized || m_bMaximized)
        return;

    if (m_bRolledUp) {
        // un-shade in place
        m_bRolledUp        = false;
        m_iHoverCell       = -1;
        m_bRollDragPending = false;
        m_bRollDragging    = false;
        g_pHyprRenderer->damageBox(m_rollBox); // clear the floating bar
        PWINDOW->setHidden(false);
        g_pCompositor->changeWindowZOrder(PWINDOW, true);
        Desktop::focusState()->fullWindowFocus(PWINDOW, Desktop::FOCUS_REASON_CLICK);
        // the window's surface was hidden; nudge the client to repaint (QtWebEngine
        // presents black after its surface is un-hidden until it redraws)
        VtbIpc::sendWake(appPid());
        damageEntire();
        return;
    }

    // shade: remember where the bar sits (for render + hit-test while hidden),
    // clear the area the window occupied, then hide it
    m_rollBox          = assignedBoxGlobal();
    m_bRolledUp        = true;
    m_iHoverCell       = -1;
    m_bRollDragPending = false;
    m_bRollDragging    = false;

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

    damageEntire(); // draws the bar at m_rollBox
}

// Enqueue the shaded window's bar into the current frame's render pass. Called
// per-monitor from main.cpp's RENDER_POST_WINDOWS hook (a hidden window gets no
// draw() of its own). Skips monitors/workspaces the shade isn't showing on.
void CVtbDeco::renderShadeIfRolled(PHLMONITOR pMonitor) {
    if (!m_bRolledUp || !g_pGlobalState || !g_pGlobalState->config.enabled->value())
        return;

    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW || !pMonitor || PWINDOW->m_monitor.lock() != pMonitor)
        return;
    if (!PWINDOW->m_pinned && (!PWINDOW->m_workspace || !PWINDOW->m_workspace->isVisible()))
        return;

    auto data = CVtbPassElement::SVtbData{this, 1.F};
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
    // Declare the shadow's reach so a moving window's damage box includes it.
    info.desiredExtents = {{(double)VTB_SHADOW_SIZE, 0.0}, {0.0, (double)VTB_SHADOW_SIZE}};
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

    // no shadow on our custom-maximized windows (the sibling titlebar knows)
    for (auto& b : g_pGlobalState->bars) {
        if (b && b->getOwner() == PWINDOW) {
            if (b->isMaximized())
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

    // Window-sized rect offset down and left; NON_SOLID + BOTTOM layer means the
    // window covers its centre and only the sharp L-overhang shows.
    const double N = VTB_SHADOW_SIZE * SCALE;
    CBox         shadowBox = {local.x - N, local.y + N, local.w, local.h};
    shadowBox.round();

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
    const double N = VTB_SHADOW_SIZE;
    // window box grown by the shadow's left + bottom overhang
    g_pHyprRenderer->damageBox(CBox{g.x - N, g.y, g.w + N, g.h + N});
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

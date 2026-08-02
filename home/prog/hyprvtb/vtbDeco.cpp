#include "vtbDeco.hpp"

#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/helpers/MiscFunctions.hpp>
#include <hyprland/src/protocols/LayerShell.hpp>
#include <hyprland/src/event/EventBus.hpp>
#include <hyprland/src/config/shared/actions/ConfigActions.hpp>
#include <hyprland/src/config/ConfigValue.hpp>
#include <hyprland/src/layout/target/Target.hpp>
// The event loop itself is reached only through Hl:: (vtbCompat.hpp); this is
// just the fd type pasteIntoEdit names in its own paste context.
#include <hyprutils/os/FileDescriptor.hpp>

#include <pango/pangocairo.h>
#include <fontconfig/fontconfig.h> // FcInitReinitialize — see vtbRefreshFontMap
#include <xkbcommon/xkbcommon.h>
#include <xkbcommon/xkbcommon-keysyms.h>
#include <cmath>
#include <chrono>
#include <cstdio>
#include <format>
#include <algorithm>
#include <functional>
#include <cerrno>
#include <fcntl.h>
#include <unistd.h>

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
// roll-up, maximize, minimize, pin) with the stacked title under them, exactly
// as the single-wide bar did.
static constexpr int VTB_PAD      = 2; // inset from the bar edge
static constexpr int VTB_CELL_GAP = 2;
static constexpr int VTB_CELLS    = 5;
static constexpr int VTB_SEP_H    = 12;   // spacer height between app-button groups
static constexpr int VTB_APPCELL  = 1000; // m_iHoverCell base for app cells (0-4 = system)

// media scrub bar (viewer video): the vertical track's groove width, its thumb
// notch height, and the logical length reserved for it below the footer text.
static constexpr double VTB_PLAYBAR_W       = 4;
static constexpr double VTB_PLAYBAR_THUMB_H = 3;
static constexpr double VTB_PLAYBAR_RESERVE = 90;
static constexpr double VTB_PLAYBAR_MIN     = 14; // don't draw/hit a track shorter than this
// One wheel notch on the track, as a fraction of the whole. 3% was a hair too
// timid to skim with (~7s on a 4-minute song); 5% lands a notch on something
// you can hear the difference in without overshooting a verse.
static constexpr double VTB_PLAYBAR_SCROLL  = 0.05;
// ...and what "one notch" means in the two units an SAxisEvent can carry. These
// are facts about libinput, not taste, and all three sources agree:
//
//  * e.delta for a WHEEL is the angle the wheel turned, in DEGREES, and "the
//    default is 15 degrees per wheel click" (/usr/include/libinput.h:1607-1609
//    — the header the live compositor links).
//  * e.deltaDiscrete is libinput's v120 value, "normalized to the 0-±120 range"
//    (:1727-1749), the Microsoft WHEEL_DELTA convention. aquamarine fills it
//    from libinput_event_pointer_get_scroll_value_v120() and ONLY for WHEEL
//    (Session.cpp, byte-identical in both pinned aquamarines), which is why a
//    finger event always arrives with deltaDiscrete == 0 and takes the degree
//    path.
//  * Hyprland states the equivalence itself: the top pin backfills a missing
//    discrete with std::round(e.delta * 8.0) (InputManager.cpp:972) — and
//    15 x 8 = 120.
//
// So one detent = 15.0 delta = 120 deltaDiscrete = one VTB_PLAYBAR_SCROLL step,
// and the two paths below cannot drift apart. If the trackpad turns out to want
// a coarser feel, this is the one number to change.
static constexpr double VTB_PLAYBAR_DETENT    = 15.0;  // e.delta units per detent
static constexpr double VTB_PLAYBAR_DETENT120 = 120.0; // e.deltaDiscrete units per detent
// How long the bar keeps showing a seek we requested but the client hasn't
// echoed, and how close an echo has to be to count as agreement (a track
// pixel's worth on a normal bar). See m_playbarPendingFrac.
static constexpr long   VTB_PLAYBAR_ECHO_MS  = 1500;
static constexpr double VTB_PLAYBAR_ECHO_EPS = 0.004;

// How long a clicked cell stays inverted as activation feedback.
//
// DELIBERATELY NOT the desktop's slide, and deliberately still a literal. This
// is not travel between two rest states — it is the acknowledgement of a press,
// the compositor-side sibling of the panel's 90ms SetToggle knob (DESIGN.md
// §6.4: feedback belongs with the pointer). Stretching it to the slide's 260
// would leave the button lit well after the thing it triggered had happened.
// It shares 220 with nothing any more, which is the point of it being here.
static constexpr float VTB_FLASH_MS = 220.f;

// Hard (sharp, un-blurred) drop shadow cast to the bottom-left of a normal
// window: a solid rectangle offset this many logical px down and left, behind
// the window.
static constexpr int VTB_SHADOW_SIZE = 24;

// roll-up / roll-out animation timing: the whole two-beat animation runs over
// Cfg::slideDurationSec(), of which the drawer slide takes the first
// Cfg::rollSlideFrac() and the "set down" the rest (reversed for roll-out).
//
// THESE WERE `static constexpr` 0.26f / 0.55f UNTIL 2.89. They are now the
// config keys `plugin:hyprvtb:slide_duration_ms` and
// `plugin:hyprvtb:roll_slide_frac`, with those exact values as their defaults,
// because this animation is not just the roll: it is the REFERENCE every
// sliding animation on this desktop is matched to (DESIGN.md §6.2), and the
// panel and the six apps were hand-copying 260 out of this file. main.cpp
// publishes the resolved numbers to ~/.local/state/hyprvtb/motion.json so those
// runtimes track the key instead of a comment. Retune in hyprland.lua,
// `hyprctl reload`, and the whole desktop moves together.
//
// Read them through Cfg:: — never cache one in a member. The accessors clamp
// (a 0ms duration is a division by zero in the progress step below, and the
// inf/NaN that follows lands in an animated CBox, which is the degenerate rect
// Hyprland's renderRect ABORTS on), and a reload must be able to change the
// feel of an animation that is already on screen.

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
    return Cfg::barWidth();
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
    const auto KB = Hl::keyboard();
    return KB && (KB->getModifiers() & (1 << 6)); // bit 6 = LOGO/SUPER (modmask 64)
}


// Snap a window's position+size animations straight to their goal, stopping any
// in-flight move/size animation. Used at the open-reveal hand-off: Hyprland
// re-kicks the windowsIn open animation AFTER startOpenReveal's warp, so the
// real window is still scaling up (a couple px short of goal) when the snapshot
// is dropped — it then eased the last bit up over the animation's tail, which
// read as the window "settling a hair smaller" right after it opened. Warping
// here lands it at exactly the snapshot's geometry with no residual motion.
static void settleGeometryToGoal(PHLWINDOW w) {
    if (!w)
        return;
    Hl::warpToGoal(w);
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

    // Take an initial registration snapshot NOW, synchronously, instead of
    // waiting for the first 150ms heartbeat (mainThreadTick) to advance it. An
    // app whose window maps with its REGISTER already in g_regs — surfer seeds
    // its chrome+title_edit onto the socket ~1ms after launch, long before
    // QtWebEngine builds the window — otherwise draws the plugin's DEFAULT bar
    // (window title, no buttons, no address editor) for every frame between map
    // and that first tick: up to a full heartbeat, which is the residual
    // startup titlebar flash. Read the serial FIRST so a REGISTER landing
    // between here and the get() still leaves serial != m_lastIpcSerial and the
    // next tick re-snapshots. Thereafter the snapshot is advanced only by
    // mainThreadTick (nothing on the render path may read VtbIpc::get).
    m_lastIpcSerial = VtbIpc::serial.load(std::memory_order_relaxed);
    SVtbAppReg fresh;
    if (VtbIpc::get(appPid(), fresh)) {
        m_regSnap = std::move(fresh);
        m_bHasReg = true;
    }
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
    // Nothing deferred may outlive this object: the callbacks' code is in this
    // .so, and this destructor is also the path PLUGIN_EXIT's detachOurDecos()
    // takes on a hot swap. See m_pendingDoLater.
    cancelPendingDoLater();
    if (m_bCursorOverridden)
        Hl::clearCursorOverride();
    if (g_pGlobalState)
        std::erase(g_pGlobalState->bars, m_self);
}

// ---- deferred-callback bookkeeping ----------------------------------------
// See m_pendingDoLater in the header for why a deco may never hand an idle
// callback to the event loop without keeping its sequence.

void CVtbDeco::queueDoLater(std::function<void()> fn) {
    // The wrapper's only extra job is retiring the sequence once fn has
    // actually run — and that sequence doesn't exist until doLater() returns,
    // so pass it through a shared slot the wrapper captures (the same
    // self-referential idiom as pasteIntoEdit's pump). doLater never runs its
    // callback inline (it always goes through wl_event_loop_add_idle), so the
    // slot is always filled before anything can read it.
    auto           seqBox = makeShared<uint64_t>(0);
    CDecoRef       self   = m_self;
    const uint64_t SEQ    = Hl::doLater([self, seqBox, fn = std::move(fn)]() {
        // Retire before running: fn may queue the next beat of the animation,
        // and the sequence being retired is this one, not that one. CDecoRef:
        // alive() + operator->, no lock() to get wrong (globals.hpp). If the
        // deco died inside this same idle batch its list is gone with it —
        // fn's own guards then make the call a no-op.
        if (self.alive())
            self->retireDoLater(*seqBox);
        fn();
    });
    *seqBox = SEQ;
    m_pendingDoLater.push_back(SEQ);
}

void CVtbDeco::retireDoLater(uint64_t seq) {
    std::erase(m_pendingDoLater, seq);
}

void CVtbDeco::cancelPendingDoLater() {
    for (const uint64_t SEQ : m_pendingDoLater)
        Hl::removeDoLater(SEQ);
    m_pendingDoLater.clear();
}

SDecorationPositioningInfo CVtbDeco::getPositioningInfo() {
    const auto                 ENABLED = Cfg::enabled();

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
        const auto POS = Hl::posValue(PWINDOW);
        const auto SZ  = Hl::sizeValue(PWINDOW);
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
    const auto POS  = m_bMinimized ? m_minSavedPos : Hl::posGoal(PWINDOW);
    const auto SIZE = Hl::sizeGoal(PWINDOW);
    return {POS, SIZE};
}

void CVtbDeco::draw(PHLMONITOR pMonitor, const float& a) {
    if (!validMapped(m_pWindow) || !Cfg::enabled())
        return;

    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW->m_ruleApplicator->decorate().valueOrDefault())
        return;

    // While a roll animation is running the render-stage hook (renderShadeIfRolled)
    // owns ALL of our drawing — during the SLIDE the window is hidden so this
    // draw() isn't called, but during the reveal-HOLD the window is un-hidden
    // again while the hook keeps drawing, so letting draw() also fire here
    // enqueued a SECOND renderPass. The opaque bar/snapshot/border doubled
    // invisibly, but the 0.6-alpha drop shadow doubled to ~0.84 — a darker shadow
    // for the tail of the roll that snapped back to normal on finish (the "flash").
    if (m_rollAnim != ROLL_NONE)
        return;

    auto data = CVtbPassElement::SVtbData{this, a};
    Hl::addPass(makeUnique<CVtbPassElement>(data));
}

// ---- text rendering -------------------------------------------------------

// Drop the process-global PangoCairo default font map so the NEXT titlebar
// draw rebuilds it against a freshly-read fontconfig. Pango caches the default
// fcfontmap (and the FcConfig behind it) for the process lifetime, so a font
// installed after the compositor started — a new pixel face picked in Settings,
// then `fc-cache -f` — is otherwise invisible to the bars until relogin.
// Proven offscreen: `fc-cache -f` alone does nothing to a running process, and
// FcInitReinitialize() alone is not enough either — only resetting the pango
// default map picks the new family up. Called from PLUGIN_INIT, so every plugin
// hot-swap (`sudo rebuild-top && hyprctl reload`) also refreshes the font DB.
// Safe live: existing PangoLayouts are created fresh per draw (renderStackedTex
// builds its own), so nothing holds a stale map across the reset — new draws
// take the new default, anyone still holding the old one keeps it refcounted.
void vtbRefreshFontMap() {
    FcInitReinitialize();
    pango_cairo_font_map_set_default(nullptr);
}

// A string as a COLUMN of upright letters ("claude" -> c/l/a/u/d/e reading
// top-down): every UTF-8 codepoint on its own pango line, centered, with
// antialiasing off so the pixel font stays crisp. One column wide (colW) —
// used for the title (outer column) and the app footer (inner column).
//
// flatColon rotates ':' a quarter turn — two pips side by side instead of
// stacked — and gives it a short row of its own. In a column of upright
// letters an upright colon is two dots reading top-down, which is exactly the
// axis the text already runs in, so it reads as two more characters rather
// than a separator; laid flat it reads as one. It also costs a third of a cell
// instead of a whole one, which is why the player's "3:45/5:12" readout asks
// for it: two colons, two cells of the scrub column handed back.
SP<Render::ITexture> CVtbDeco::renderStackedTex(const std::string& text, int runLenPx, float scale, const CHyprColor& COLOR, int* outTextH, int* outLines,
                                                bool ellipsis, bool flatColon) {
    const auto FONT  = Cfg::font();
    const int  SIZE  = std::round(Cfg::fontSize() * scale);
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
    const bool               truncated = ellipsis && (int)cps.size() > maxLines;
    const int                shown     = truncated ? std::max(0, maxLines - 1) : (int)cps.size();
    std::vector<std::string> lines(cps.begin(), cps.begin() + shown); // spaces get their own (blank) cell
    if (truncated)
        lines.push_back("…");
    if (outLines)
        *outLines = lines.size();

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
    pango_layout_set_width(layout, BARW * PANGO_SCALE);
    pango_layout_set_alignment(layout, PANGO_ALIGN_CENTER);
    pango_layout_set_spacing(layout, 0);

    // Pin the per-cell pitch to the font size — kitty's cell, and the same
    // thing PixelText does in QML with lineHeightMode: FixedHeight. Pango
    // rounds ascent and descent UP separately (at 15px: 11.25→12 + 3.75→4 =
    // 17), so a stacked column would lead wider than a terminal row and drift
    // further off the grid with every glyph. Negative spacing pulls each line
    // back onto the cell; everything downstream (maxLines above, m_iEditLineH,
    // the caret/selection rows) already assumes a pitch of exactly SIZE.
    int natH = 0;
    pango_layout_set_text(layout, "M", -1);
    pango_layout_get_pixel_size(layout, nullptr, &natH);
    if (natH > 0 && natH != SIZE)
        pango_layout_set_spacing(layout, (SIZE - natH) * PANGO_SCALE);

    cairo_set_source_rgba(CR, COLOR.r, COLOR.g, COLOR.b, COLOR.a);

    // Flat colons force the column to be drawn in RUNS between them (a pango
    // layout has one line height for every line in it), so the cells above and
    // below a colon keep the exact typography of the single-layout path.
    const int DOT    = std::max(1, (int)std::round(SIZE / 7.0));
    const int PAD    = std::max(1, (int)std::round(SIZE / 8.0));
    const int COLONH = DOT + 2 * PAD;

    double    y = 0;
    for (size_t i = 0; i < lines.size();) {
        if (flatColon && lines[i] == ":") {
            const double cx = BARW / 2.0;
            cairo_rectangle(CR, std::round(cx - DOT - PAD / 2.0), std::round(y + PAD), DOT, DOT);
            cairo_rectangle(CR, std::round(cx + PAD / 2.0), std::round(y + PAD), DOT, DOT);
            cairo_fill(CR);
            y += COLONH;
            i++;
            continue;
        }
        std::string run;
        size_t      j = i;
        for (; j < lines.size() && !(flatColon && lines[j] == ":"); j++) {
            if (j > i)
                run += "\n";
            run += lines[j];
        }
        pango_layout_set_text(layout, run.c_str(), -1);
        cairo_move_to(CR, 0, y);
        pango_cairo_show_layout(CR, layout);

        // advance by whole cells, not by the run's ink height — the last line
        // of a run still carries its full (rounded-up) descent, which would
        // otherwise reintroduce the drift the pinned spacing just removed.
        y += (double)(j - i) * SIZE;
        i = j;
    }

    if (outTextH)
        *outTextH = (int)std::round(y);

    pango_font_description_free(fd);
    g_object_unref(layout);
    cairo_font_options_destroy(fo);
    cairo_surface_flush(SURF);

    auto tex = Hl::textureFromCairo(SURF);

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

    const auto FONT = Cfg::font();
    const int  SIZE = std::round(Cfg::fontSize() * scale);

    auto       tex = Hl::renderText(glyph, color, SIZE, false, FONT, 0);
    m_glyphCache[key] = tex;
    return tex;
}

// ---- drawing --------------------------------------------------------------

// Entry point (from CVtbPassElement). At rest / mid-roll the bar draws straight
// into the scene. But while the LONE bar is fading (open fade-in / close
// fade-out) each layer would otherwise blend over the desktop independently —
// the opaque black backing and the light glyphs/outlines fade at the same alpha
// but composite differently, so the light button parts wash out against the
// bright desktop until the backing is solid ("buttons lag the bar"). To fade the
// bar as ONE image, render it opaque into an offscreen buffer and composite that
// whole buffer once at the fade alpha. Confined to the fade: the direct path is
// unchanged at rest and during the roll (which draws the live snapshot/shadow/
// border that must blend against the real scene, not a flattened copy).
void CVtbDeco::renderPass(PHLMONITOR pMonitor, const float& a) {
    if (a >= 0.999f || m_rollAnim != ROLL_NONE || !pMonitor) {
        if (m_fadeFB) {
            // Fade is over: drop the offscreen buffer instead of pinning a
            // monitor-sized RGBA FB (~14M at 1440p) per window for its
            // lifetime. Through the seam: we are INSIDE a pass element here,
            // and releasing mid-frame needs a rebind on 0.55 (Hl::releaseFB).
            Hl::releaseFB(m_fadeFB);
        }
        renderBar(pMonitor, a);
        return;
    }

    const Vector2D PX = pMonitor->m_size * pMonitor->m_scale;
    if (PX.x < 1 || PX.y < 1) {
        renderBar(pMonitor, a);
        return;
    }
    const int FBW = (int)std::round(PX.x);
    const int FBH = (int)std::round(PX.y);
    if (!m_fadeFB)
        m_fadeFB = Hl::createFB("vtbFade");
    if (m_fadeFB && ((int)m_fadeFB->m_size.x != FBW || (int)m_fadeFB->m_size.y != FBH))
        m_fadeFB->alloc(FBW, FBH);
    if (!m_fadeFB || !m_fadeFB->isAllocated()) {
        renderBar(pMonitor, a); // couldn't get an offscreen buffer — fall back to direct (washes out a touch, but always draws)
        return;
    }

    // Draw the bar opaque into the offscreen buffer. It's monitor-sized with the
    // same projection, so renderBar's monitor-local device coords land unchanged.
    {
        const auto GUARD = Hl::bindTempFB(m_fadeFB); // restores the prior FB on scope exit
        glDisable(GL_SCISSOR_TEST);
        glClearColor(0.f, 0.f, 0.f, 0.f);
        glClear(GL_COLOR_BUFFER_BIT);
        renderBar(pMonitor, 1.f);
    }

    // Composite the whole flattened bar back into the scene at the fade alpha,
    // clipped to the bar's footprint (the rest of the buffer is transparent, but
    // clipping keeps the blend cheap). The texture is monitor-sized, so map it
    // 1:1 by drawing it at the monitor's full device box.
    CBox        full = {0.0, 0.0, (double)FBW, (double)FBH};
    const CBox  DECOBOX = effectiveBoxGlobal();
    CBox        footprint = {DECOBOX.x - pMonitor->m_position.x, DECOBOX.y - pMonitor->m_position.y, DECOBOX.w, DECOBOX.h};
    footprint.translate(m_pWindow.expired() ? Vector2D() : m_pWindow.lock()->m_floatingOffset).scale(pMonitor->m_scale);
    CHyprOpenGLImpl::STextureRenderData data;
    data.a          = a;
    // Expand past the bar box: the open-reveal outline (drawRollBorder) draws a few
    // px OUTSIDE barBox, and the buffer is transparent beyond the bar anyway, so a
    // generous clip just captures the outline without touching anything else.
    data.clipRegion = CBox{footprint}.expand(VTB_SHADOW_SIZE).round();
    Hl::texture(m_fadeFB->getTexture(), full.round(), data);
}

void CVtbDeco::renderBar(PHLMONITOR pMonitor, float a) {
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW)
        return;

    const auto SCALE   = pMonitor->m_scale;
    const bool FOCUSED = PWINDOW == Hl::focusedWindow();

    auto       bgColor       = configColor(Cfg::bgColor());
    auto       bgAltColor    = configColor(Cfg::bgAltColor());
    auto       borderColor   = configColor(Cfg::buttonBorderColor());
    auto       accentColor   = configColor(Cfg::accentColor());
    auto       critColor     = configColor(Cfg::critColor());
    auto       warnColor     = configColor(Cfg::warnColor());
    auto       inactiveColor = configColor(Cfg::inactiveColor());
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
    if (m_bOpening) {
        // Open reveal: the lone bar already faded in showing focused-accent labels,
        // so the window is coming up focused — hold accent through the whole reveal.
        // (Without this the ROLLANIM crossfade below restarts the tint at inactive
        // the instant the roll begins, flashing the accent labels dark then back.)
        textColor = accentColor;
    } else if (ROLLANIM) {
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
        if (Hl::posGoal(PWINDOW) != T.pos() || Hl::sizeGoal(PWINDOW) != T.size()) {
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

    // NB the roll animation's own drop shadow is NOT drawn here — the flat
    // shadow layer paints it (via rollShadowBoxDev) so it shares the one union
    // with every other window's, and so it can't double-darken where the two
    // cross. The bar and the sliding snapshot still occlude its centre; only
    // the bottom-left L-overhang shows, collapsing as the bar sets down.

    // background
    Hl::rect(barBox, bgColor, {});

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
            Hl::rect(localBox(x, y, CELL, CELL), fc, {});
            return;
        }
        const int bw = lit ? 2 : 1;
        auto      oc = lit ? hot : borderColor;
        oc.a *= a;
        Hl::rect(localBox(x, y, CELL, CELL), oc, {});
        Hl::rect(localBox(x + bw, y + bw, CELL - 2 * bw, CELL - 2 * bw), lit ? bgAltColor : bgColor, {});
    };

    auto drawGlyphXY = [&](double x, double y, const std::string& glyph, const CHyprColor& color) {
        auto tex = glyphTex(glyph, color, SCALE);
        if (!tex || tex->m_texID == 0)
            return;
        const auto TSZ  = tex->m_size;
        CBox       gbox = {barBox.x + (x + CELL / 2.0) * SCALE - TSZ.x / 2.0, barBox.y + (y + CELL / 2.0) * SCALE - TSZ.y / 2.0, TSZ.x, TSZ.y};
        Hl::texture(tex, gbox.round(), {.a = a});
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

    // roll-up — windowshade toggle: [>>] hides the window down to just this
    // bar; while shaded it shows [<<] to roll it back. Sits between close and
    // maximize, and carries the theme WARN (yellow) role the same way close
    // carries CRIT (red). Inverted while shaded — but NOT during the open/close
    // animations, which borrow the roll-up machinery (m_bRolledUp goes true
    // mid-animation) without the user having shaded anything.
    const bool SHADED = m_bRolledUp && !m_bOpening && !m_bClosing;
    drawCell(1, warnColor, SHADED);
    drawGlyph(1, SHADED ? "<<" : ">>", (SHADED || m_iHoverCell == 1) ? warnColor : textColor, SHADED);

    // maximize [=] — inverted while maximized (held), accent while hovered
    drawCell(2, accentColor, m_bMaximized);
    drawGlyph(2, "=", (m_bMaximized || m_iHoverCell == 2) ? accentColor : textColor, m_bMaximized);

    // minimize [>] — slides the window off to the right
    drawCell(3, accentColor, false);
    drawGlyph(3, ">", m_iHoverCell == 3 ? accentColor : textColor);

    // pin [o>] — Hyprland pin: keeps the window on top and on every
    // workspace. Inverted while pinned, like maximize while maximized.
    const bool PINNED = PWINDOW->m_pinned;
    drawCell(4, accentColor, PINNED);
    drawGlyph(4, "o>", (PINNED || m_iHoverCell == 4) ? accentColor : textColor, PINNED);

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
            m_iEditLineH = lines > 0 ? th / lines : std::round(Cfg::fontSize() * SCALE);
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
                    Hl::rect(block.round(), accentColor, {});
                }
            }
            CBox tbox = {TITLEX, TITLEY, TSZ.x, TSZ.y};
            Hl::texture(m_pEditTex, tbox.round(), {.a = a});
        }
        if (hasSel && m_pEditSelTex && m_pEditSelTex->m_texID != 0 && m_iEditLineH > 0) {
            const auto TSZ    = m_pEditSelTex->m_size;
            const int  selRow = std::max(0, loCp);
            CBox       sbox   = {TITLEX, TITLEY + selRow * (double)m_iEditLineH, TSZ.x, TSZ.y};
            Hl::texture(m_pEditSelTex, sbox.round(), {.a = a});
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
                Hl::rect(caret.round(), accentColor, {});
            }
            damageEntire(); // keep the blink ticking on a still cursor
        }
    } else if (!m_bHasReg || m_regSnap.titleText) { // == VtbIpc::titleTextEnabled(), off the snapshot
        // ...unless the app has declared its title region carries no text
        // (TITLETEXT 0 — goetia). [his, 2026-07-29] *"really for now there
        // should be no title text in the left side inner bar of goetia"*: its
        // title is only the program's own name, which DESIGN.md 12 says the bar
        // is not for. The xdg_toplevel title is untouched, so the taskbar and
        // alt-tab still name the window; an empty Window.title would not have
        // done this — Qt substitutes the application name and the bar would
        // have read "board" instead (measured in the sandbox).
        if (m_szLastTitle != PWINDOW->m_title || RUNLEN != m_iLastTitleRun || m_fLastScale != SCALE || !m_pTitleTex) {
            m_szLastTitle   = PWINDOW->m_title;
            m_iLastTitleRun = RUNLEN;
            renderTitleTex(RUNLEN, SCALE, textColor);
        }

        if (m_pTitleTex && m_pTitleTex->m_texID != 0) {
            const auto TSZ  = m_pTitleTex->m_size;
            CBox       tbox = {TITLEX, TITLEY, TSZ.x, TSZ.y};
            Hl::texture(m_pTitleTex, tbox.round(), {.a = a});
        }
    }
    m_fLastScale = SCALE;

    // page-loading spinner: in the slot titleTopEff() reserved (below roll-up,
    // above the address), cycle | \ - / ~8fps while the browser reports loading.
    {
        SVtbAppReg lreg;
        if (appReg(lreg) && lreg.titleEdit && lreg.loading) {
            static const char* FRAMES[4] = {"|", "\\", "-", "/"};
            const long         ms        = std::chrono::duration_cast<std::chrono::milliseconds>(Time::steadyNow().time_since_epoch()).count();
            drawGlyphXY(sysColX(), titleTop(), FRAMES[(ms / 120) % 4], FOCUSED ? accentColor : inactiveColor);
            damageEntire(); // keep it spinning
        }
    }

    // ---- inner column: app-registered buttons + stacked footer (vtbIpc) ----
    // The render path is a pure READER of the snapshot: it no longer stamps
    // m_lastIpcSerial. Stamping here was the second half of the titlebar text
    // flash — a frame drawn between an app's change and the next tick advanced
    // the serial past the bump, so mainThreadTick saw nothing to prewarm or
    // repaint and the new text could stay missing until something else damaged
    // the bar. docs/hyprvtb-titlebar-flash.md.
    SVtbAppReg reg;
    if (appReg(reg)) {
        const double CONTENTH  = DECOBOX.h;
        double       appBottom = VTB_PAD; // bottom of the TOP group (footer stays below it)

        walkAppLayout(reg.buttons, CONTENTH, [&](size_t i, double y) {
            const auto& b = reg.buttons[i];

            // separator ("-"): a thin divider line centred in the gap
            if (b.isSep()) {
                if (y + VTB_SEP_H <= CONTENTH - VTB_PAD) {
                    auto sc = textColor;
                    sc.a *= a;
                    Hl::rect(localBox(innerColX() + 2, y + VTB_SEP_H / 2.0, cellSize() - 4, 1), sc, {});
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

        // footer: short stacked text in the lower inner column (filer's dir-size
        // readout / viewer's position+name). Normally bottom-anchored, ABOVE any
        // bottom-anchored buttons. When a media scrub bar is shown it instead
        // TOP-anchors just under the top button group so the vertical track has
        // room below it (bounded run length reserves that track space).
        const double BH      = bottomGroupH(reg.buttons);
        const double lowerTop = appBottom + VTB_PAD;              // top of the lower area (logical)
        const double lowerBot = CONTENTH - BH - VTB_PAD;          // bottom (above the bottom group)
        const double lowerH   = lowerBot - lowerTop;
        const int    FRUNLEN = std::round((reg.playbar ? std::max(0.0, lowerH - VTB_PLAYBAR_RESERVE) : lowerH) * SCALE);
        if (reg.footer != m_szLastFooter || FRUNLEN != m_iLastFooterRun || !m_pFooterTex) {
            m_szLastFooter   = reg.footer;
            m_iLastFooterRun = FRUNLEN;
            m_iFooterTextH   = 0;
            // flatColon: the footer is where clock-style readouts live
            // ("3:45/5:12"), and a laid-flat colon both reads as a separator
            // and gives the scrub track back the cells it was eating.
            m_pFooterTex     = renderStackedTex(reg.footer, FRUNLEN, SCALE, textColor, &m_iFooterTextH, nullptr, /*ellipsis=*/true, /*flatColon=*/true);
        }
        if (m_pFooterTex && m_pFooterTex->m_texID != 0) {
            // the texture's glyphs start at its top; bottom-anchor using the real
            // pango text height so the readout hugs the bar's bottom edge (above
            // the bottom-anchored group, if any) — or top-anchor for the scrub bar
            // footerBottom flips the pair: the track takes the top of the lower
            // area and the readout bottom-anchors under it (player), instead of
            // the readout on top and the track below (viewer).
            const auto   TSZ  = m_pFooterTex->m_size;
            const bool   FTOP = reg.playbar && !reg.footerBottom;
            const double fy   = FTOP ? (barBox.y + lowerTop * SCALE)
                                     : (barBox.y + barBox.h - (VTB_PAD + BH) * SCALE - m_iFooterTextH);
            CBox         fbox = {barBox.x + footerTexX() * SCALE, fy, TSZ.x, TSZ.y};
            Hl::texture(m_pFooterTex, fbox.round(), {.a = a});
        }

        // media scrub bar: a vertical progress track filling top->bottom with the
        // playback fraction, drawn below the footer. Click/drag/scroll it seeks
        // (handled in the mouse hooks); while dragging the fill follows the cursor.
        CBox track;
        if (playbarTrackLocal(reg, CONTENTH, SCALE, track)) {
            const double frac  = playbarFrac(reg);
            const double cx    = innerColX() + CELL / 2.0;
            const double trkX  = cx - VTB_PLAYBAR_W / 2.0;
            const auto   fillC = FOCUSED ? accentColor : inactiveColor;
            auto         grooveC = borderColor;

            grooveC.a *= a;
            Hl::rect(localBox(trkX, track.y, VTB_PLAYBAR_W, track.h), grooveC, {});
            auto fc = fillC;
            fc.a *= a;
            // frac 0 (player paused at the very start of a track) makes this a
            // zero-height box, and renderRect ABORTS the compositor on a
            // degenerate rect — skip the fill until there is ≥1px to draw.
            if (track.h * frac >= 1.0)
                Hl::rect(localBox(trkX, track.y, VTB_PLAYBAR_W, track.h * frac), fc, {});
            // thumb: a wider notch at the fill boundary so the position reads and grabs
            const double thumbW = CELL * 0.55;
            double       thumbY = track.y + track.h * frac - VTB_PLAYBAR_THUMB_H / 2.0;
            thumbY = std::clamp(thumbY, track.y, track.y + track.h - VTB_PLAYBAR_THUMB_H);
            Hl::rect(localBox(cx - thumbW / 2.0, thumbY, thumbW, VTB_PLAYBAR_THUMB_H), fc, {});
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
                Hl::rect(localBox(innerColX(), tgtY - VTB_CELL_GAP / 2.0 - 1, CELL, 2), ac, {});
            }
            // lifted cell at the cursor's Y (clamped into the column)
            const auto   MOUSELOCAL = Hl::mouse() - assignedBoxGlobal().pos();
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

    // roll-OUT only: the emerging window's border, crossfading unfocused->focused
    // in step with the SLIDE, so unrolling looks like the window "coming to focus"
    // as it emerges. The snapshot is clipped to the bare client rect (no border in
    // it) and the hidden window draws none, so this is the only border shown for
    // the whole reveal — it hands off to the live window's own border as it lands.
    // NOT drawn on roll-UP: there the window ends hidden with no live border to
    // hand off to, so the last frame's outline had nothing to clear it and sat
    // stale until the bar was moved.
    if (m_bOpening) {
        // Open reveal: the outline is present the WHOLE reveal so it appears in step
        // with the accent labels instead of popping in only once the roll starts.
        // During the fade-in (ROLLANIM false) slideT is 1 → the border wraps just the
        // lone bar; as the content rolls out it expands to wrap content+bar. Always
        // accent (both endpoints accent → the crossfade is a no-op) since the window
        // is coming up focused, then it hands off to the live window's accent border.
        const float sT = ROLLANIM ? rollSlideT : 1.f;
        drawRollBorder(barBox, SCALE, sT, accentColor, accentColor, a);
    } else if (ROLLANIM && m_rollAnim == ROLL_OUT)
        drawRollBorder(barBox, SCALE, rollSlideT, accentColor, inactiveColor, a);

    // NOTE: the hover tooltip is NOT drawn here — this pass element is an
    // UNDER-layer decoration (drawn before the window surface), and the tooltip
    // overhangs the window to the left, so drawing it here would put it behind
    // the window. It's enqueued separately at RENDER_POST_WINDOWS; see
    // enqueueTooltip / drawTooltipPass.
}

// A window's box in this monitor's device pixels, carrying the same
// workspace-slide + floating-drag offsets the titlebar uses so anything drawn
// off it tracks the window through animations.
static CBox vtbWindowLocalBox(PHLMONITOR pMonitor, PHLWINDOW w) {
    CBox       g   = Hl::boxValue(w);
    const auto WS  = w->m_workspace;
    const auto OFF = (WS && !w->m_pinned) ? WS->m_renderOffset->value() : Vector2D();
    g.translate(OFF);
    CBox b = {g.x - pMonitor->m_position.x, g.y - pMonitor->m_position.y, g.w, g.h};
    return b.translate(w->m_floatingOffset).scale(pMonitor->m_scale).round();
}

// Does this window actually carry one of our titlebars?
//
// "Every window has a bar" is not true and never was: the scratchpad has none,
// and since the privilege prompt is bar-less too (vtbNeverDecorates in main.cpp)
// it is now a state a *centred, visible* window is in. Anything that widens a
// box by totalBarW() has to ask — otherwise the frame and the drop shadow run a
// full bar's width past the window's right edge with nothing drawn above them,
// which is what the scratchpad's shadow has been doing latently.
static bool vtbHasBar(PHLWINDOW w) {
    if (!w || !g_pGlobalState)
        return false;
    for (const auto& b : g_pGlobalState->bars) {
        if (b && b->getOwner() == w)
            return true;
    }
    return false;
}

// The visible frames of every window on this monitor — client box plus its
// reserved titlebar strip — in monitor-local device pixels. This is what
// occludes shadows: subtracting it is the "a shadow only ever falls on the
// desktop" rule, and BOTH shadow paths (the flat layer and the roll
// animation's own collapsing shadow) have to obey it.
static CRegion vtbWindowFrames(PHLMONITOR pMonitor) {
    CRegion frames;
    if (!pMonitor)
        return frames;

    const double BARW = totalBarW() * pMonitor->m_scale;

    for (const auto& w : Hl::windows()) {
        if (!w || !w->m_isMapped || w->isHidden())
            continue;
        if (w->m_monitor.lock() != pMonitor)
            continue;
        if (!w->m_pinned && (!w->m_workspace || !w->m_workspace->isVisible()))
            continue;

        const CBox L = vtbWindowLocalBox(pMonitor, w);
        if (L.w < 1 || L.h < 1)
            continue;

        const bool DECORATED = w->m_ruleApplicator->decorate().valueOrDefault();
        frames.add(CBox{L.x, L.y, L.w + (DECORATED && vtbHasBar(w) ? BARW : 0.0), L.h}.round());
    }

    return frames;
}

// The collapsing drop shadow of the visible composite (remaining client + bar),
// offset down+left by the current float height; at downT 1 the offset is 0, so
// the bar/snapshot sit flush over it and it vanishes ("set down").
//
// This only REPORTS the box — vtbRenderShadowLayer paints it, in the same union
// as every resting window's shadow. It used to paint itself, alongside the
// composite, and that cost two rules at once:
//
//  * it landed on whatever the composite was rising in front of, because a
//    roll-OUT (and the open reveal, which ends in one) is enqueued at
//    RENDER_POST_WINDOWS to animate OVER those windows. The strip only snapped
//    away when the animation landed and the window joined the flat layer.
//  * where it crossed another window's shadow, two 0.6-alpha blacks blended to
//    ~0.84 — the darker patch the flat layer's union was built to eliminate.
//    Hugging the neighbour's edge, it read as a shadow lying ON that window,
//    and it vanished the instant the animation ended and the two merged. The
//    more windows underneath, the more overlaps, which is why it got worse with
//    a deeper stack.
//
// Reporting the box instead fixes both by construction: one union, one
// subtraction of the window frames, every shadowed pixel painted exactly once.
// Drawing it before the windows rather than after is not a visual change — the
// rule already says a shadow never covers a window, so the only pixels it can
// reach are desktop either way.
//
// Reports the composite's shadow ONLY while a roll is in flight — the visible
// remnant (remaining client + bar) casts it, and it collapses to nothing as the
// bar sets down. A window at REST rolled up casts NO drop shadow of its own: a
// rolled-up window is chrome, not a window (his correction to 3.02, which had
// added a resting self-shadow). Other windows' shadows still fall ON a resting
// bar — that is the over-bars pass in vtbRenderShadowLayer, not this.
//
// False when there is nothing to draw: no animation (incl. fully set down at
// rest), or the lone bar is mid-fade (open fade-in / close fade-out), where the
// composite is translucent and a full-strength shadow in a flat union can't
// follow it.
bool CVtbDeco::rollShadowBoxDev(PHLMONITOR pMonitor, CBox& out) {
    if (!pMonitor || m_rollAnim == ROLL_NONE || m_bBarFading || m_bBarFadingIn)
        return false;

    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW || PWINDOW->m_monitor.lock() != pMonitor)
        return false;
    if (!PWINDOW->m_pinned && (!PWINDOW->m_workspace || !PWINDOW->m_workspace->isVisible()))
        return false;

    float slideT = 0.f, downT = 0.f;
    if (!rollAnimSubProgress(slideT, downT))
        return false;

    const double SCALE     = pMonitor->m_scale;
    const double shadowOff = VTB_SHADOW_SIZE * (1.f - downT) * SCALE;
    if (shadowOff <= 0.5)
        return false;

    // Same bar box renderBar draws into (effectiveBoxGlobal already carries the
    // set-down drop), in this monitor's device pixels.
    const CBox DECOBOX = effectiveBoxGlobal();
    CBox       barBox  = {DECOBOX.x - pMonitor->m_position.x, DECOBOX.y - pMonitor->m_position.y, DECOBOX.w, DECOBOX.h};
    barBox.translate(PWINDOW->m_floatingOffset).scale(SCALE).round();
    if (barBox.w < 1 || barBox.h < 1)
        return false;

    const double clientW  = m_rollWinBox.w * SCALE;
    const double barRight = barBox.x + barBox.w;
    // left edge of the still-visible content as it tucks right into the bar
    const double visLeft = barBox.x - clientW * (1.f - slideT);

    out = CBox{visLeft - shadowOff, barBox.y + shadowOff, barRight - visLeft, barBox.h}.round();
    return out.w >= 1 && out.h >= 1; // never hand renderRect a degenerate box
}

// The resting/set-down bar box of a rolled-up window in this monitor's device
// pixels — the same box renderBar draws into (effectiveBoxGlobal carries the
// set-down drop). vtbRenderShadowLayer's over-bars pass unions these to find
// where OTHER windows' shadows may fall on a rolled-up bar (his report: those
// shadows must appear ON TOP of a rolled-up window, not vanish behind its bar).
//
// False for a bar drawing OVER the windows this frame — roll-out, open reveal
// and the roll-up slide beat are all enqueued at RENDER_POST_WINDOWS and sit
// above everything, so a shadow must not be laid on them — and for a window
// that is not rolled up at all.
bool CVtbDeco::rollBarBoxDev(PHLMONITOR pMonitor, CBox& out) {
    if (!pMonitor || (!m_bRolledUp && m_rollAnim == ROLL_NONE))
        return false;
    if (isRollingOut() || isOpening() || isRollingUpSlide())
        return false;

    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW || PWINDOW->m_monitor.lock() != pMonitor)
        return false;
    if (!PWINDOW->m_pinned && (!PWINDOW->m_workspace || !PWINDOW->m_workspace->isVisible()))
        return false;

    const double SCALE   = pMonitor->m_scale;
    const CBox   DECOBOX = effectiveBoxGlobal();
    CBox         barBox  = {DECOBOX.x - pMonitor->m_position.x, DECOBOX.y - pMonitor->m_position.y, DECOBOX.w, DECOBOX.h};
    barBox.translate(PWINDOW->m_floatingOffset).scale(SCALE).round();
    out = barBox;
    return out.w >= 1 && out.h >= 1;
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
    Hl::texture(m_rollSnapTex, fullBox.round(), data);
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

    Hl::rect(CBox{cl - bs, ct - bs, fw + 2 * bs, bs}.round(), bc, {});   // top
    Hl::rect(CBox{cl - bs, ct + ch, fw + 2 * bs, bs}.round(), bc, {});   // bottom
    Hl::rect(CBox{cl - bs, ct - bs, bs, ch + 2 * bs}.round(), bc, {});   // left
    Hl::rect(CBox{cr, ct - bs, bs, ch + 2 * bs}.round(), bc, {});        // right (bar's outer edge)
}

// Hover text for a cell: fixed strings for the five system cells, the
// registered tooltip for app cells ("" = draw nothing).
std::string CVtbDeco::tooltipForCell(int cell) {
    switch (cell) {
        case 0: return "close";
        case 1: return m_bRolledUp ? "unroll" : "roll up";
        case 2: return m_bMaximized ? "unmaximize" : "maximize";
        case 3: return "minimize";
        case 4: return "pin";
        default: break;
    }
    if (cell >= VTB_APPCELL) {
        SVtbAppReg reg;
        if (appReg(reg)) {
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
        if (appReg(reg)) {
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
// OUT of the bar's left edge (OutCubic, the desktop's slide) like the quickshell hover
// widgets slide out of the screen edge, and retracts back into it. The label
// starts fully tucked behind the bar and is clipped to the bar's left edge, so
// the un-emerged part stays hidden behind the bar as it travels. Called each
// rendered frame from drawTooltipPass while m_bTooltipShown; advances the slide
// phase itself and re-damages until it settles, so it animates on a still cursor.
// The tooltip slide IS the desktop's slide — same key, no second number. It was
// a `static constexpr 220.f` whose comment said it existed "to match
// SlidePopup's 220ms card slide"; the panel's card has since moved to the
// canonical 260 (the roll's own duration), so matching it now means reading the
// same key the roll does rather than re-copying whatever it changed to.
static inline float vtbTooltipSlideMs() {
    return static_cast<float>(Cfg::slideDurationMs());
}

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
    const float step   = dt / vtbTooltipSlideMs();
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
            Hl::damage(b.expand(4));
            m_tooltipBox = {};
        }
        return;
    }

    const auto TEXT = tooltipForCell(m_ttCell);
    const double CY = cellCenterY(m_ttCell);
    if (TEXT.empty() || CY < 0)
        return;

    auto bgColor   = configColor(Cfg::bgColor());
    auto accent    = configColor(Cfg::accentColor());
    auto textCol   = configColor(Cfg::textColor());

    const float E = easeOutCubic(m_ttPhase); // eased slide amount (no fade — it emerges from behind the bar)
    bgColor.a *= a;
    accent.a *= a;

    const auto FONT = Cfg::font();
    const int  SIZE = std::round(Cfg::fontSize() * SCALE);
    const auto KEY  = TEXT + "|" + std::format("{:08x}", textCol.getAsHex());

    auto       it  = m_tooltipCache.find(KEY);
    auto       tex = (it != m_tooltipCache.end()) ? it->second : (m_tooltipCache[KEY] = Hl::renderText(TEXT, textCol, SIZE, false, FONT, 0));
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
    CRegion clip = Hl::renderDamage();
    clip.intersect(CBox{0.0, 0.0, barBox.x, (double)pMonitor->m_transformedSize.y});

    CBox box = {slideX, barBox.y + CY * SCALE - H / 2.0, W, H};
    box.round();

    Hl::rect(box, accent, {.damage = &clip});
    CBox inner = {box.x + SCALE, box.y + SCALE, box.w - 2 * SCALE, box.h - 2 * SCALE};
    Hl::rect(inner.round(), bgColor, {.damage = &clip});
    CBox tbox = {box.x + PADPX, box.y + PADPX, (double)tex->m_size.x, (double)tex->m_size.y};
    Hl::texture(tex, tbox.round(), {.damage = &clip, .a = a});

    // remember the GLOBAL logical box (covering the full slide range, up to the
    // bar edge) so a later damage clears every pixel the label could have touched
    const auto   DECOBOX = effectiveBoxGlobal();
    const double LW      = W / SCALE + 10;
    const double LH      = H / SCALE + 4;
    m_tooltipBox         = {DECOBOX.x - LW, DECOBOX.y + CY - LH / 2.0, LW + 2, LH};

    // keep frames coming until the slide settles (a motionless cursor emits no
    // events of its own; this self-sustains the animation)
    if (animating)
        Hl::damage(CBox{m_tooltipBox});
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
        Hl::damage(CBox{m_tooltipBox}.expand(4));
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
    if (!m_bTooltipShown || !g_pGlobalState || !Cfg::enabled())
        return;
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW || !pMonitor || PWINDOW->m_monitor.lock() != pMonitor)
        return;

    auto data        = CVtbPassElement::SVtbData{this, 1.F};
    data.tooltipOnly = true;
    Hl::addPass(makeUnique<CVtbPassElement>(data));
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
    //
    // The serial is GLOBAL, so it moves for every deco on the screen whenever
    // any app changes anything — player's PLAYBAR bumps it several times a
    // second. So the serial only says "somebody changed something": what
    // decides is whether THIS window's own registration differs from the
    // snapshot we are drawing. Refresh it here, off the render pass, and
    // prewarm + damage only on a real change to our own bar. Everyone else pays
    // one map lookup and a compare.
    if (ipcSerial != m_lastIpcSerial) {
        m_lastIpcSerial = ipcSerial;
        SVtbAppReg fresh;
        const bool have = VtbIpc::get(appPid(), fresh); // leaves `fresh` default on false
        if (have != m_bHasReg || (have && fresh != m_regSnap)) {
            m_regSnap = std::move(fresh);
            m_bHasReg = have;
            prewarmGlyphs(); // reads the snapshot we just advanced
            damageEntire();
        }
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
    const bool FOCUSED = m_pWindow.lock() == Hl::focusedWindow();
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
            Hl::damage(CBox{m_tooltipBox});
        }
        damageEntire();
    } else if (!FOCUSED && m_bTooltipShown && m_ttWantShown) {
        // Lost focus while a tooltip was out (focus can change without the
        // cursor leaving our bar) — retract it.
        hideTooltip();
    }
}

// The registration this bar draws and hit-tests, as of the last tick. Declared
// in vtbDeco.hpp; see mainThreadTick for who advances it and why nothing on the
// render path may read VtbIpc::get directly.
bool CVtbDeco::appReg(SVtbAppReg& out) const {
    if (!m_bHasReg)
        return false;
    out = m_regSnap;
    return true;
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

// The media scrub track in bar-local LOGICAL px (see the .hpp). Mirrors the
// renderPass layout: below the top button group, below the top-anchored footer
// text (its measured height carried in m_iFooterTextH, device px). The returned
// width is the full inner-column cell width — a fat, easy click/scroll target
// even though the drawn groove is thin. False if no scrub bar or too short.
bool CVtbDeco::playbarTrackLocal(const SVtbAppReg& reg, double contentH, double scale, CBox& out) {
    if (!reg.playbar)
        return false;
    double appBottom = VTB_PAD;
    walkAppLayout(reg.buttons, contentH, [&](size_t i, double y) {
        const auto& b = reg.buttons[i];
        if (b.bottom)
            return;
        appBottom = std::max(appBottom, y + (b.isSep() ? VTB_SEP_H : cellSize()));
    });
    const double lowerTop = appBottom + VTB_PAD;
    const double lowerBot = contentH - bottomGroupH(reg.buttons) - VTB_PAD;
    const double footerH  = scale > 0 ? m_iFooterTextH / scale : 0;
    // Footer above the track (default) or below it (reg.footerBottom): either
    // way the track gives up the same footerH + VTB_PAD, just off the other
    // end. The default expression is left exactly as it was so viewer's track
    // geometry is bit-identical to before this flag existed.
    const double trackTop = reg.footerBottom ? lowerTop : lowerTop + footerH + VTB_PAD;
    const double trackLen = (reg.footerBottom ? lowerBot - (footerH + VTB_PAD) : lowerBot) - trackTop;
    if (trackLen < VTB_PLAYBAR_MIN)
        return false;
    out = {(double)innerColX(), trackTop, (double)cellSize(), trackLen};
    return true;
}

// What the scrub bar shows, and what a scroll steps from. Priority: the live
// drag, then a seek we asked for but haven't seen echoed, then the client's own
// reported position. The pending value retires as soon as the echo lands within
// a track-pixel or so of it — or after VTB_PLAYBAR_ECHO_MS, so a client that
// ignores SEEK entirely (or seeks somewhere else, e.g. clamped to a chapter)
// can't leave a lie on screen.
double CVtbDeco::playbarFrac(const SVtbAppReg& reg) {
    const double POS = std::clamp((double)reg.playPos, 0.0, 1.0);

    if (m_bPlaybarDragging)
        return std::clamp(m_playbarDragFrac, 0.0, 1.0);

    if (m_playbarPendingFrac >= 0.0) {
        const long MS = std::chrono::duration_cast<std::chrono::milliseconds>(Time::steadyNow() - m_playbarPendingAt).count();
        if (std::abs(POS - m_playbarPendingFrac) <= VTB_PLAYBAR_ECHO_EPS || MS > VTB_PLAYBAR_ECHO_MS)
            m_playbarPendingFrac = -1.0; // the client caught up (or never will)
        else
            return m_playbarPendingFrac;
    }

    return POS;
}

// Scroll over the scrub track. DELTA-PROPORTIONAL: one wheel detent moves the
// seek by VTB_PLAYBAR_SCROLL, and a trackpad's stream of small deltas moves it
// by the same amount per detent's worth of motion.
//
// This used to key on the SIGN of e.delta alone and step a full 5% PER EVENT.
// A mouse wheel emits one event per detent, so that read correctly for years on
// `top`; a trackpad emits a burst of a hundred a second, and on book the
// trackpad is the only pointer there is — so one two-finger flick across the
// track threw the song forward by minutes. Same shape of bug as viewer's
// sign-only zoom and painter's per-event Spin: a handler that was written when
// every axis event meant one detent.
//
// The sub-detent remainder is CARRIED rather than rounded away, for the same
// reason the kinetic engine carries its fractional pixels: a trackpad's
// individual deltas are small, and dropping each one's remainder would make
// slow, careful scrubbing do nothing at all.
void CVtbDeco::playbarScrollBy(const SVtbAppReg& reg, const IPointer::SAxisEvent& e) {
    const double DETENTS = e.deltaDiscrete != 0 ? (double)e.deltaDiscrete / VTB_PLAYBAR_DETENT120 : e.delta / VTB_PLAYBAR_DETENT;
    m_playbarScrollAcc += DETENTS * VTB_PLAYBAR_SCROLL;

    // Accumulate against what the bar is actually SHOWING, which while a seek is
    // in flight is the pending value rather than the client's echoed position
    // (playbarFrac's whole job). That is what lets a burst add up instead of
    // every event re-deriving its step from a position two IPC ticks stale —
    // the second half of the same bug.
    const double BASE   = playbarFrac(reg);
    const double TARGET = std::clamp(BASE + m_playbarScrollAcc, 0.0, 1.0);

    // Whatever the rails swallowed is dropped, never banked: otherwise scrolling
    // back off the end of a track would first have to burn through everything
    // the clamp ate on the way there.
    m_playbarScrollAcc = TARGET - BASE;

    // Under one track pixel there is nothing to show and nothing worth putting
    // on the socket — keep carrying it.
    if (std::abs(m_playbarScrollAcc) < VTB_PLAYBAR_ECHO_EPS)
        return;

    m_playbarScrollAcc = 0.0;
    playbarSeekTo(TARGET);
    damageEntire(); // the fill moves now, not when the client answers
}

// Ask the client to seek, and remember what we asked for so the bar can show it
// until the answer arrives.
void CVtbDeco::playbarSeekTo(double frac) {
    frac                 = std::clamp(frac, 0.0, 1.0);
    m_playbarPendingFrac = frac;
    m_playbarPendingAt   = Time::steadyNow();
    VtbIpc::sendSeek(appPid(), (float)frac);
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
    const bool  FOCUSED = PWINDOW == Hl::focusedWindow();

    const auto accentColor   = configColor(Cfg::accentColor());
    const auto inactiveColor = configColor(Cfg::inactiveColor());
    const auto bgColor       = configColor(Cfg::bgColor());
    const auto textColor     = FOCUSED ? accentColor : inactiveColor;

    SVtbAppReg reg;
    if (!appReg(reg))
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
    return appReg(reg) && reg.titleEdit;
}

// titleTop() plus a one-cell spinner slot reserved while a browser window's page
// is loading (renderPass draws the | \ - / spinner in that slot). Both the title
// texture and the address-editor hit-testing use this, so they shift down
// together while loading and stay in sync.
int CVtbDeco::titleTopEff() {
    SVtbAppReg reg;
    const bool spin = appReg(reg) && reg.titleEdit && reg.loading;
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

// Insert clipboard/typed text at the caret, replacing any selection. Newlines
// and control bytes are stripped — an address bar is a single line, and pasting
// a copied URL that trailed a newline shouldn't submit or wrap it.
void CVtbDeco::insertEditText(const std::string& text) {
    std::string clean;
    clean.reserve(text.size());
    for (unsigned char c : text) {
        if (c == '\n' || c == '\r' || c == '\t')
            continue;            // collapse whitespace that would break a URL line
        if (c < 0x20 || c == 0x7f)
            continue;            // drop other C0 controls / DEL (keep UTF-8 high bytes)
        clean.push_back((char)c);
    }
    if (clean.empty())
        return;
    deleteEditSelection();       // paste replaces any selection, like typing
    m_editBuf.insert(m_editCursor, clean);
    m_editCursor    += clean.size();
    m_editSelAnchor  = m_editCursor;
    m_pEditTex       = nullptr;
    damageEntire();
}

// Ctrl+V / Shift+Insert: pull the current wl_data_device selection (the
// clipboard) and drop it into the field at the caret. The owning client writes
// the data to a pipe asynchronously, so we hand the read end to the event loop
// (doOnReadable) and accumulate until EOF rather than blocking the compositor.
// A weak self-ref guards the deferred insert against the deco/window dying while
// the read is in flight.
void CVtbDeco::pasteIntoEdit() {
    const auto SOURCE = Hl::selectionSource();
    if (!SOURCE)
        return; // empty clipboard

    // pick the best text mime the source advertises (prefer explicit UTF-8)
    const auto MIMES = SOURCE->mimes();
    std::string mime;
    for (const char* want : {"text/plain;charset=utf-8", "UTF8_STRING", "text/plain", "TEXT", "STRING"}) {
        if (std::find(MIMES.begin(), MIMES.end(), want) != MIMES.end()) {
            mime = want;
            break;
        }
    }
    if (mime.empty()) // no text flavour on offer (e.g. an image-only clipboard)
        return;

    int fds[2];
    if (pipe2(fds, O_CLOEXEC | O_NONBLOCK) != 0)
        return;
    Hyprutils::OS::CFileDescriptor readFd{fds[0]};
    // hand the write end to the source; it forwards to the owning client, which
    // writes then closes — giving us readable data and eventually EOF.
    SOURCE->send(mime, Hyprutils::OS::CFileDescriptor{fds[1]});

    // shared context carried across the (possibly repeated) readable callbacks
    struct SPasteCtx {
        CDecoRef                       self;
        Hyprutils::OS::CFileDescriptor fd;
        std::string                    acc;
    };
    auto ctx  = makeShared<SPasteCtx>();
    ctx->self = m_self;
    ctx->fd   = std::move(readFd);

    auto pump = makeShared<std::function<void()>>();
    *pump     = [ctx, pump]() {
        char buf[4096];
        while (true) {
            const ssize_t n = read(ctx->fd.get(), buf, sizeof(buf));
            if (n > 0) {
                ctx->acc.append(buf, n);
                continue;
            }
            if (n < 0 && errno == EINTR)
                continue;
            if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
                // nothing more yet — re-arm on the same pipe (dup, since the
                // waiter takes ownership of the fd it polls) and wait again.
                Hl::doOnReadable(ctx->fd.duplicate(), [pump]() { (*pump)(); });
                return;
            }
            // EOF (n == 0) or a hard error: commit whatever we got, if the deco
            // is still alive and still editing this field. CDecoRef has no
            // lock() to reach for (see globals.hpp) — alive() + operator-> is
            // the whole vocabulary.
            if (ctx->self.alive() && ctx->self->m_bEditing && !ctx->acc.empty())
                ctx->self->insertEditText(ctx->acc);
            return;
        }
    };
    // seed the first wait with a dup so the master fd in ctx stays ours to read.
    Hl::doOnReadable(ctx->fd.duplicate(), [pump]() { (*pump)(); });
}

// Map a bar-local Y (logical px) to a byte offset on a codepoint boundary — the
// row under the cursor in the vertically-stacked address text. Used for
// click-to-place-caret and click-drag selection.
size_t CVtbDeco::editByteAtLocalY(double localY) {
    const double scale = m_fLastScale > 0 ? m_fLastScale : 1.0;
    const double lineH = (m_iEditLineH > 0) ? m_iEditLineH / scale
                                            : (double)Cfg::fontSize();
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
                                          : (Cfg::fontSize() * scale);
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

// Would this titlebar eat a vertical wheel event at this cursor position?
//
// Factored out of onMouseAxis so vtbKinetic can ask the same question BEFORE
// starting a fling (and again on every tick of one) — a momentum tail poured
// into the PLAYBAR would scrub a song by minutes, and into an open address
// editor would scroll the URL instead of the page. It has to be a separate
// predicate rather than a reading of `info.cancelled`, because hyprutils calls
// every listener on a signal unconditionally and the kinetic listener is
// registered first: it would always see `false` no matter what a deco does
// afterwards.
//
// The two branches below are the ORIGINAL gates, moved verbatim; the handler
// now calls this and then does exactly what it did before. Not const: it runs
// through appPid()/assignedBoxGlobal()/playbarTrackLocal()/shadeOccludedAt(),
// which cache and would each have to be const-qualified in turn.
bool CVtbDeco::consumesAxisAt(const Vector2D& mouse) {
    // Scroll over the media scrub bar seeks it (viewer video). Only the deco
    // whose track actually sits under the cursor acts; everyone else passes the
    // wheel through untouched.
    if (!m_bEditing) {
        // Same predicates as before, in a cheaper ORDER: a momentum fling asks
        // this of every bar on every tick, so the map lookup that rules out
        // every window without a scrub bar (i.e. all but viewer/player) has to
        // come before the hit test, not after it. All of these are
        // side-effect-free — appPid() only fills its own cache — so reordering
        // cannot change the answer.
        const auto PW = m_pWindow.lock();
        if (!PW)
            return false;
        SVtbAppReg reg;
        if (!appReg(reg) || !reg.playbar)
            return false;
        const auto   MON = PW->m_monitor.lock();
        const double scl = MON ? MON->m_scale : 1.0;
        CBox         track;
        if (!playbarTrackLocal(reg, assignedBoxGlobal().h, scl, track) || !track.containsPoint(mouse - assignedBoxGlobal().pos()))
            return false;
        // ...and only when the track is the topmost thing at the cursor: a
        // shaded bar draws under every window, and an unshaded bar can have
        // another window stacked over it — either way the wheel belongs to
        // what's on top, not the track underneath.
        return !(m_bRolledUp ? shadeOccludedAt(mouse) : Hl::windowAtCursorProps(mouse) != PW);
    }

    // Editing: this deco owns the wheel, but only while it is also the focused
    // window (focus can slip away before renderPass cancels the edit).
    const auto PWINDOW = m_pWindow.lock();
    return PWINDOW && PWINDOW == Hl::focusedWindow();
}

// Does ANY titlebar consume a vertical wheel at this point? Declared in
// globals.hpp so vtbKinetic.cpp can call it without naming a decoration type.
bool vtbAxisConsumerAtCursor(const Vector2D& mouse) {
    if (!g_pGlobalState)
        return false;
    for (auto& b : g_pGlobalState->bars) {
        if (b && b->consumesAxisAt(mouse))
            return true;
    }
    return false;
}

// Wheel while the address editor is open scrolls the stacked URL instead of the
// page (we own the keyboard grab; owning the wheel too keeps a long URL
// navigable). Only the focused/editing window's deco consumes it.
void CVtbDeco::onMouseAxis(Event::SCallbackInfo& info, const IPointer::SAxisEvent& e) {
    if (e.axis != WL_POINTER_AXIS_VERTICAL_SCROLL || e.delta == 0.0)
        return;
    if (!consumesAxisAt(Hl::mouse()))
        return;

    if (!m_bEditing) {
        SVtbAppReg reg;
        if (!appReg(reg))
            return;
        // Cancelled unconditionally, even when the accumulated remainder is too
        // small to move anything yet: the track owns this wheel either way, and
        // letting a sub-pixel leftover through would scroll the app underneath.
        info.cancelled = true; // scrub, don't hand the wheel to the app
        playbarScrollBy(reg, e);
        return;
    }

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
    if (!PWINDOW || PWINDOW != Hl::focusedWindow()) {
        exitEdit(false);
        return;
    }

    const auto KB = Hl::keyboard();
    if (!KB || !KB->m_xkbState)
        return;

    const uint32_t     xkbcode = e.keycode + 8; // libinput -> xkb
    const xkb_keysym_t sym     = xkb_state_key_get_one_sym(KB->m_xkbState, xkbcode);
    const uint32_t     mods    = KB->getModifiers();

    // editing Ctrl combos we handle ourselves: Ctrl+A selects the whole field,
    // Ctrl+V pastes the clipboard. Everything else with Ctrl/Alt/Super falls
    // through to global keybinds below.
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
    if ((mods & HL_MODIFIER_CTRL) && !(mods & (HL_MODIFIER_ALT | HL_MODIFIER_META))
        && (sym == XKB_KEY_v || sym == XKB_KEY_V)) {
        info.cancelled = true;
        if (e.state == WL_KEYBOARD_KEY_STATE_PRESSED) {
            m_editBlinkAt = Time::steadyNow();
            pasteIntoEdit();
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
        case XKB_KEY_Insert: ours = (mods & HL_MODIFIER_SHIFT); break; // Shift+Insert = paste
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

    if (sym == XKB_KEY_Insert) { // reached only with Shift held (see the `ours` switch)
        pasteIntoEdit();
        return;
    }

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
    if (!Cfg::enabled())
        return false;

    if (!m_pWindow->m_workspace || !m_pWindow->m_workspace->isVisible() || Hl::inputExclusive() ||
        Hl::seatGrabRejects(m_pWindow->wlSurface()->resource()))
        return false;

    const auto WINDOWATCURSOR = Hl::windowAtCursorProps(Hl::mouse());


    // Accept only when the cursor is over US, or over EMPTY space while we're
    // focused (the resize halo just outside our frame). The old test also
    // accepted "we're focused" when the cursor sat over ANOTHER window — so a
    // focused window hidden BEHIND another still grabbed presses aimed at the
    // window on top, then moved/resized itself and cancelled the event (e.g.
    // dragging filer's inner bar moved the focused window behind it, and filer
    // never got the press). If something else occupies the point, it occludes
    // us and must own the event.
    if (WINDOWATCURSOR != m_pWindow && (WINDOWATCURSOR || m_pWindow != Hl::focusedWindow()))
        return false;

    // don't fight top/overlay layer surfaces (launcher, lock, ...)
    auto     PMONITOR     = Hl::focusedMonitor();
    PHLLS    foundSurface = nullptr;
    Vector2D surfaceCoords;

    Hl::layerSurfaceAt(Hl::mouse(), Hl::monitorLayer(PMONITOR, ZWLR_LAYER_SHELL_V1_LAYER_TOP), &surfaceCoords, &foundSurface);
    if (foundSurface)
        return false;

    Hl::layerSurfaceAt(Hl::mouse(), Hl::monitorLayer(PMONITOR, ZWLR_LAYER_SHELL_V1_LAYER_OVERLAY), &surfaceCoords, &foundSurface);
    if (foundSurface)
        return false;

    return true;
}

// Whether the point over this SHADED bar is covered by something drawn above
// it. The shade bar renders at RENDER_PRE_WINDOWS — beneath every visible
// window and beneath top/overlay layer surfaces — so any of those at the
// cursor occludes it and owns the event; among overlapping shade bars, later
// entries in the bars list paint later (on top), so a later rolled bar
// covering the point wins too. Without this test a hidden bar accepted any
// press/hover inside its box: it ate clicks aimed at a webpage above it, and
// a grab on an overlap of two titlebars dragged both windows at once.
bool CVtbDeco::shadeOccludedAt(const Vector2D& mouse) {
    if (Hl::windowAtCursorProps(mouse))
        return true;

    const auto PMONITOR = Hl::monitorAt(mouse);
    if (PMONITOR) {
        PHLLS    foundSurface = nullptr;
        Vector2D surfaceCoords;
        Hl::layerSurfaceAt(mouse, Hl::monitorLayer(PMONITOR, ZWLR_LAYER_SHELL_V1_LAYER_TOP), &surfaceCoords, &foundSurface);
        if (foundSurface)
            return true;
        Hl::layerSurfaceAt(mouse, Hl::monitorLayer(PMONITOR, ZWLR_LAYER_SHELL_V1_LAYER_OVERLAY), &surfaceCoords, &foundSurface);
        if (foundSurface)
            return true;
    }

    bool after = false;
    for (auto& b : g_pGlobalState->bars) {
        if (!b)
            continue;
        if (b.get() == this) {
            after = true;
            continue;
        }
        if (!after || !b->m_bRolledUp || b->m_rollAnim != ROLL_NONE)
            continue;
        const auto PW = b->m_pWindow.lock();
        if (!PW || (!PW->m_pinned && (!PW->m_workspace || !PW->m_workspace->isVisible())))
            continue;
        const auto BAR   = b->effectiveBoxGlobal();
        const auto LOCAL = mouse - (BAR.pos() + PW->m_floatingOffset);
        if (VECINRECT(LOCAL, 0, 0, BAR.w, BAR.h))
            return true;
    }
    return false;
}

Vector2D CVtbDeco::cursorRelativeToBar() {
    return Hl::mouse() - assignedBoxGlobal().pos();
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
    CBox box = Hl::boxValue(w);
    if (Cfg::enabled())
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
    if (!validMapped(m_pWindow) || !PWINDOW->m_isFloating || Hl::isFullscreen(PWINDOW) || m_bMinimized || m_bMaximized || m_bRolledUp)
        return false;

    const auto MOUSE = Hl::mouse();
    uint32_t   edges = 0;

    if (e.button == VTB_BTN_RIGHT && superHeld())
        edges = interiorResizeZone(MOUSE);
    else if (e.button == VTB_BTN_LEFT)
        edges = borderResizeZone(MOUSE);

    if (!edges)
        return false;

    if (Hl::focusedWindow() != PWINDOW)
        Hl::focusWindow(PWINDOW);
    Hl::raise(PWINDOW);

    m_bEdgeResizing  = true;
    m_resizeEdges    = edges;
    m_resStartMouse  = MOUSE;
    m_resStartBox    = Hl::boxGoal(PWINDOW);
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

    const auto DELTA   = Hl::mouse() - m_resStartMouse;

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
            if (m_rollAnim == ROLL_NONE) {
                handleRolledUp(info);
                return;
            }
            // Mid-animation the click handlers are inert — but the press state
            // still has to be RETIRED here, because clicking [<<] rolls up
            // synchronously from the press (startRollAnim sets m_bRolledUp +
            // m_rollAnim before we ever see the release). This branch used to
            // just `return`, stranding m_bCancelledDown set for good, and one
            // leaked flag caused both halves of the "sticky mouse after a
            // roll" bug: the next press we DON'T cancel reaches the client
            // while its release is eaten by the stale flag, so (a) the client
            // sees press-with-no-release and acts click-and-held (errant
            // text highlighting), and (b) Hyprland bails out of onMouseButton
            // before erasing the button from m_currentlyHeldButtons, so its
            // "holding a button -> don't refocus" guard pins pointer focus to
            // the old surface — focus visibly moves, input doesn't follow,
            // until a click back on the old window balances the books.
            const bool CANCELLED = m_bCancelledDown;
            m_bCancelledDown     = false;
            m_bRollDragPending   = false;
            m_bRollDragging      = false;
            m_iRollPressCell     = -1;
            if (CANCELLED)
                info.cancelled = true; // we ate its press; don't hand the client a lone release
            return;
        }
        handleUpEvent(info);
        return;
    }

    // One flag, one press: a new press supersedes whatever the last one left
    // behind, so the release path can never consume a release whose press we
    // let through. Every site that cancels a press below re-sets this.
    m_bCancelledDown = false;

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

    // scrubbing the media bar: seek to the fraction under the cursor and keep the
    // fill following it (the client echoes PLAYBAR, but the local drag frac drives
    // the render so it never lags the pointer).
    if (m_bPlaybarDragging) {
        const auto   PWINDOW = m_pWindow.lock();
        const auto   MON     = PWINDOW ? PWINDOW->m_monitor.lock() : nullptr;
        const double scl     = MON ? MON->m_scale : 1.0;
        SVtbAppReg   reg;
        CBox         track;
        const auto   LOCAL = Hl::mouse() - assignedBoxGlobal().pos();
        if (PWINDOW && appReg(reg) && playbarTrackLocal(reg, assignedBoxGlobal().h, scl, track)) {
            const double f = std::clamp((LOCAL.y - track.y) / track.h, 0.0, 1.0);
            if (f != m_playbarDragFrac) {
                m_playbarDragFrac = f;
                playbarSeekTo(f);
                damageEntire();
            }
        }
        return;
    }

    // selecting in the address editor: drag the cursor end to the row under the
    // pointer (anchor stays at the press point), extending the highlight.
    if (m_bEditDragging) {
        const auto   BOX   = assignedBoxGlobal();
        const auto   LOCAL = Hl::mouse() - BOX.pos();
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
            const auto DELTA = Hl::mouse() - m_rollDragMouseStart;
            if (!m_bRollDragging && (std::abs(DELTA.x) + std::abs(DELTA.y)) > 4)
                m_bRollDragging = true;
            if (m_bRollDragging) {
                const auto PWINDOW = m_pWindow.lock();
                // Clear the bar's old spot at the box it was actually DRAWN in:
                // effectiveBoxGlobal() is m_rollBox dropped by VTB_SHADOW_SIZE, so
                // damaging raw m_rollBox left the bottom shadow-strip of the bar
                // un-repainted — a dark trail that read as a shadow smear behind
                // a moving rolled-up window.
                Hl::damage(CBox{effectiveBoxGlobal()}.expand(2));
                m_rollBox.x  = m_rollDragBoxStart.x + DELTA.x;
                m_rollBox.y  = m_rollDragBoxStart.y + DELTA.y;
                m_iHoverCell = -1;
                if (PWINDOW) {
                    // Move the hidden window so it reappears here on restore.
                    // warpPosLogical, NOT warpPos: the layout target owns the
                    // authoritative position and is what the next native drag
                    // seeds itself from, so warping the animation alone left the
                    // window filed at its pre-shade spot and the first frame of
                    // a post-unroll drag teleported it back there.
                    const Vector2D NEWPOS = m_rollDragWinStart + DELTA;
                    Hl::warpPosLogical(PWINDOW, NEWPOS);
                }
                Hl::damage(CBox{effectiveBoxGlobal()}.expand(2)); // new spot, same cushion
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
        const auto     MOUSE = Hl::mouse();
        const auto     LOCAL = MOUSE - (HIT.pos() + OFF);
        // no hover feedback through whatever's drawn over the bar (matches the
        // press path's occlusion test — the visible thing on top owns the point)
        const int      cell  = VECINRECT(LOCAL, 0, 0, HIT.w, HIT.h) && !shadeOccludedAt(MOUSE) ? cellAt(LOCAL) : -1;
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
        const auto   DELTA = Hl::mouse() - m_appDragMouseStart;
        const double dist  = std::abs(DELTA.x) + std::abs(DELTA.y);
        if (!m_bAppDragging && dist > 6) {
            if (m_appPressDraggable)
                m_bAppDragging = true;
            else
                m_bAppPressPending = false;
        }
        if (m_bAppDragging) {
            SVtbAppReg reg;
            if (appReg(reg)) {
                const auto LOCAL = Hl::mouse() - assignedBoxGlobal().pos();
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
        const auto LOCAL  = Hl::mouse() - BOX.pos();
        int        cell   = VECINRECT(LOCAL, 0, 0, BOX.w, BOX.h) ? cellAt(LOCAL) : -1;
        if (cell == -1 && VECINRECT(LOCAL, 0, 0, BOX.w, BOX.h)) {
            SVtbAppReg reg;
            if (appReg(reg)) {
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
        if (m_pWindow->m_isFloating && !m_bMaximized && !m_bEdgeResizing && Hl::noButtonsHeld()) {
            const auto MOUSE = Hl::mouse();
            // ...but only when our edge is actually the top-most thing here. If
            // another window is stacked over ours at this point, the edge is
            // occluded and can't be grabbed — offering the resize cursor there
            // was misleading (the press is already rejected by inputIsValid's
            // same window-at-cursor test). The compositor hit test honours z-order;
            // a null result is empty space, where a halo edge-grab is still valid.
            const auto WINDOWATCURSOR = Hl::windowAtCursorProps(MOUSE);
            const bool occluded = WINDOWATCURSOR && WINDOWATCURSOR != m_pWindow;
            const auto Z        = occluded ? 0u : borderResizeZone(MOUSE);
            if (Z & RS_EDGE_R) {
                const char* shape = (Z & RS_EDGE_T) ? "top_right_corner" : (Z & RS_EDGE_B) ? "bottom_right_corner" : "right_side";
                Hl::setCursorOverride(shape);
                m_bCursorOverridden = true;
            } else if (m_bCursorOverridden) {
                Hl::clearCursorOverride();
                m_bCursorOverridden = false;
            }
        }
    }

    if (!m_bDragPending || !validMapped(m_pWindow))
        return;

    m_bDragPending = false;
    Hl::mouseBindMode(MBIND_MOVE);
    m_bDraggingThis = true;
}

void CVtbDeco::handleDownEvent(Event::SCallbackInfo& info) {
    const auto PWINDOW = m_pWindow.lock();
    const auto COORDS  = cursorRelativeToBar();
    const auto BOX     = assignedBoxGlobal();

    if (!VECINRECT(COORDS, 0, 0, BOX.w, BOX.h - 1)) {
        if (m_bDraggingThis)
            Config::Actions::mouse("0movewindow"); // end the move-drag (was the dispatcher map)

        m_bDraggingThis = false;
        m_bDragPending  = false;
        return;
    }

    // Was this window already focused when the press landed? A click on an
    // UNFOCUSED window's address bar should only focus it (like every other
    // click-to-focus) — the edit opens on the NEXT click. Captured before we
    // steal focus just below.
    const bool WASFOCUSED = Hl::focusedWindow() == PWINDOW;

    if (!WASFOCUSED)
        Hl::focusWindow(PWINDOW);

    if (PWINDOW->m_isFloating)
        Hl::raise(PWINDOW);

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
        case 1: toggleRollup(); return;
        case 2: toggleMaximize(); return;
        case 3: minimizeWindow(); return;
        case 4: togglePin(); return;
        default: break;
    }

    // inner column: app-registered buttons. A press ARMS the button — the CLICK
    // fires on release (handleUpEvent), so a press+drag can instead reorder a
    // draggable button. Disabled cells are inert but still swallow the press.
    {
        SVtbAppReg reg;
        if (appReg(reg)) {
            const int AI = appCellAt(COORDS, reg);
            if (AI >= 0) {
                if (reg.buttons[AI].state == 2)
                    return; // disabled: inert
                m_bAppPressPending  = true;
                m_bAppDragging      = false;
                m_iAppPressIdx      = AI;
                m_appPressId        = reg.buttons[AI].id;
                m_appPressDraggable = reg.buttons[AI].draggable;
                m_appDragMouseStart = Hl::mouse();
                m_iAppDragTarget    = AI;
                return;
            }
        }
    }

    // inner column: media scrub bar. A press jumps the fill to the cursor and
    // begins a scrub-drag (onMouseMove tracks it, seeking live via SEEK).
    {
        SVtbAppReg   reg;
        CBox         track;
        const auto   MON = PWINDOW->m_monitor.lock();
        const double scl = MON ? MON->m_scale : 1.0;
        if (appReg(reg) && playbarTrackLocal(reg, BOX.h, scl, track) && track.containsPoint(COORDS)) {
            m_bPlaybarDragging = true;
            m_playbarScrollAcc = 0.0; // a grab supersedes any carried scroll remainder
            m_playbarDragFrac  = std::clamp((COORDS.y - track.y) / track.h, 0.0, 1.0);
            playbarSeekTo(m_playbarDragFrac);
            damageEntire();
            return;
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

    // finishing a media scrub-drag: the seek already fired on press/move; just
    // drop the drag so the render reverts to the client's echoed position.
    if (m_bPlaybarDragging) {
        m_bPlaybarDragging = false;
        m_bDragPending     = false;
        damageEntire();
        if (CANCELLED)
            info.cancelled = true;
        return;
    }

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
                if (appReg(reg) && tgt < (int)reg.buttons.size())
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
            Hl::mouseBindMode(MBIND_INVALID);
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
        Hl::mouseBindMode(MBIND_INVALID);
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
    const auto MOUSE = Hl::mouse();
    const auto LOCAL = MOUSE - (BAR.pos() + PWINDOW->m_floatingOffset);
    if (!VECINRECT(LOCAL, 0, 0, BAR.w, BAR.h))
        return; // not on the bar — let the click pass through to what's behind

    // On the bar's box, but the bar itself draws UNDER every visible window —
    // if one is stacked over this point (another titlebar, a webpage), it's
    // what the user sees and clicked; swallowing the press here co-dragged
    // both windows / stole the page's clicks. Same for a shade bar drawn over
    // ours. Decline and let the event reach the thing on top.
    if (shadeOccludedAt(MOUSE))
        return;

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
    m_rollDragWinStart   = Hl::posLogical(PWINDOW); // the layout's box — same origin a real drag reads
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
    if (WASPENDING && !WASDRAG && PRESSCELL == 1)
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
// (dispatch path), so Hl::snapshotFB is safe here (not mid render-stage).
void CVtbDeco::startOpenReveal() {
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW || !PWINDOW->m_isFloating || m_bRolledUp || m_rollAnim != ROLL_NONE)
        return;

    // A freshly-mapped window is still mid open-animation (value() != goal()), so
    // warp it straight to its settled geometry first — otherwise the snapshot
    // captures the half-animated frame and m_rollSnapOrigin (computed off goal())
    // wouldn't line up with where the pixels actually landed in the FB.
    Hl::warpToGoal(PWINDOW);

    CBox       g   = Hl::boxValue(PWINDOW);
    const auto WS  = PWINDOW->m_workspace;
    const auto OFF = (WS && !PWINDOW->m_pinned) ? WS->m_renderOffset->value() : Vector2D();
    g.translate(OFF);
    m_rollWinBox = g;

    // The decoration positioner hasn't run yet at window.open, so assignedBoxGlobal()
    // is still 0x0 here — build the bar box directly: it sits on the content's right
    // edge, totalBarW() wide and the window's full height (mirrors frameBox()).
    m_rollBox = {m_rollWinBox.x + m_rollWinBox.w, m_rollWinBox.y, (double)totalBarW(), m_rollWinBox.h};

    const auto SNAPFB = Hl::snapshotFB(PWINDOW);
    if (SNAPFB && SNAPFB->isAllocated())
        m_rollSnapTex = SNAPFB->getTexture();
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

    const auto GAP    = Cfg::maximizeGap();
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
        m_savedGeometry = Hl::boxGoal(PWINDOW);

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

    // Hyprland's own pin action, called directly. This used to go through the
    // keybind manager's internal dispatcher map, looked up by the string
    // "pin" and handed an address string — a map upstream has since deleted.
    // The typed Config::Actions entry is the supported way in and takes the
    // window itself.
    Config::Actions::pinWindow(Config::Actions::TOGGLE_ACTION_TOGGLE, PWINDOW);
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
    Hl::damage(stale);
    PWINDOW->setHidden(true);

    // hand focus to another visible, non-hidden window on this workspace
    PHLWINDOW next = nullptr;
    for (auto& w : Hl::windows()) {
        if (w == PWINDOW || !w->m_isMapped || w->isHidden() || w->m_workspace != PWINDOW->m_workspace)
            continue;
        // Skip minimized windows. A minimized window is still mapped and NOT
        // hidden — just slid off-screen — so it passes the filter above, but
        // focusing it here would trip its restore-on-focus (onFocusGained) and
        // pop it back on every roll-up. minimizeWindow's handoff skips them for
        // the same reason.
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
        Hl::focusWindow(next);
    else
        Hl::resetFocus();
}

// Shove a SHADED window's floating bar back inside a horizontal band on its own
// monitor, and return true if it actually moved.
//
// Why this has to live in the plugin at all. Everything else on screen can be
// pushed out from under a grown panel with a plain `hl.dsp.window.move` — but a
// rolled-up window can't, for three compounding reasons:
//   1. while shaded the bar is drawn at m_rollBox, a SNAPSHOT taken at roll-up
//      time (startRollAnim / startOpenReveal). Nothing recomputes it afterwards.
//   2. the window itself is setHidden(true), so the decoration positioner skips
//      it entirely — `updateWindowDecos()` early-returns on a hidden window, so
//      even a positioner run wouldn't refresh m_bAssignedBox, let alone m_rollBox.
//   3. therefore moving the underlying window from outside moves *nothing
//      visible*: the pixels keep being painted at the frozen m_rollBox, and the
//      only thing that changes is where the window will pop back out on unroll.
// So the mover has to be the one thing that owns m_rollBox — us.
//
// The body deliberately mirrors the rolled-bar DRAG path in onMouseMove
// (damage-old / shift m_rollBox.x / warpPos the hidden window / damage-new),
// because that path is the known-correct way to relocate a shaded bar: it is
// exercised every time the user drags one, and each of its four steps exists for
// a reason discovered there (in particular damaging effectiveBoxGlobal() and not
// raw m_rollBox — see the comment at the drag). Like the drag, this does NOT
// touch m_rollWinBox: that box is the roll-up snapshot's source rect, used to
// sample the frozen texture, and shifting it would slide the picture inside the
// bar. Staying consistent with the drag is the point.
bool CVtbDeco::pushRolledIntoBand(double reserve, bool edgeRight) {
    // Never touch one mid-animation: m_rollBox is being interpolated against by
    // the roll beats, and the window's position is mid-warp.
    if (!m_bRolledUp || m_rollAnim != ROLL_NONE)
        return false;
    if (!(reserve > 0.0)) // also rejects NaN
        return false;
    if (!validMapped(m_pWindow))
        return false;

    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW)
        return false;
    const auto PMONITOR = PWINDOW->m_monitor.lock();
    if (!PMONITOR)
        return false;

    // The band is the part of THIS window's monitor the panel doesn't cover.
    const double MONL  = PMONITOR->m_position.x;
    const double MONR  = MONL + PMONITOR->m_size.x;
    const double BANDL = edgeRight ? MONL : MONL + reserve;
    const double BANDR = edgeRight ? MONR - reserve : MONR;
    if (!(BANDR > BANDL)) // reserve swallowed the monitor — nowhere to push to
        return false;

    // Single dx: pull left until the bar ends flush with the band, then (if it
    // is wider than the band, or was already left of it) clamp at the left edge.
    // Doing it as one delta keeps this to exactly one damage/warp pair.
    const double BARL = m_rollBox.x;
    const double BARR = m_rollBox.x + m_rollBox.w;
    double       dx   = 0.0;
    if (BARR > BANDR)
        dx = BANDR - BARR;
    if (BARL + dx < BANDL)
        dx = BANDL - BARL;
    if (dx == 0.0)
        return false; // already inside — no damage, no warp, no work

    // Clear the bar's old spot at the box it is actually DRAWN in (see the drag:
    // effectiveBoxGlobal() is m_rollBox dropped by the set-down offset, and
    // damaging raw m_rollBox leaves the bottom shadow strip smeared behind).
    Hl::damage(CBox{effectiveBoxGlobal()}.expand(2));
    m_rollBox.x += dx;
    m_iHoverCell = -1; // the bar moved out from under the cursor
    // Move the hidden window too, so it reappears under its bar on unroll.
    // Through the layout target (warpPosLogical), for the same reason the drag
    // does: warping only the animation leaves the layout filed at the pre-push
    // spot, and the next native drag snaps the window back there.
    Hl::warpPosLogical(PWINDOW, Hl::posLogical(PWINDOW) + Vector2D{dx, 0.0});
    Hl::damage(CBox{effectiveBoxGlobal()}.expand(2)); // new spot, same cushion
    return true;
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
        slideT = rollEaseOutCubic(rollRemap(g, 0.f, Cfg::rollSlideFrac()));
        downT  = rollEaseInOut(rollRemap(g, Cfg::rollSlideFrac(), 1.f));
    } else {
        downT  = 1.f - rollEaseInOut(rollRemap(g, 0.f, 1.f - Cfg::rollSlideFrac()));
        slideT = 1.f - rollEaseOutCubic(rollRemap(g, 1.f - Cfg::rollSlideFrac(), 1.f));
    }
    return true;
}

// True while a roll-UP is still in its first beat, the drawer slide. The window
// being shaded is the one the user just acted on, so its composite must keep
// drawing OVER its neighbours until the content has fully tucked behind the bar;
// only for the set-down beat does it drop to the under-windows layer, where a
// rolled-up bar belongs. Without this it fell behind everything on the very
// first frame — hideRolledWindow hands focus away immediately, which raises
// another window over the one still visibly sliding.
bool CVtbDeco::isRollingUpSlide() const {
    return m_rollAnim == ROLL_UP && m_rollProgress < Cfg::rollSlideFrac();
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
            CBox       g   = Hl::boxValue(PWINDOW);
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
            const auto SNAPFB = Hl::snapshotFB(PWINDOW);
            if (SNAPFB && SNAPFB->isAllocated())
                m_rollSnapTex = SNAPFB->getTexture();
            // The snapshot is a MONITOR-sized framebuffer, so the window
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
        m_bRollReveal  = false;
        m_bRollRevived = false;
        if (const auto PWINDOW = m_pWindow.lock()) {
            Hl::focusWindow(PWINDOW);
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
    m_rollProgress += dt / Cfg::slideDurationSec();
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
                CDecoRef self = m_self;
                queueDoLater([self]() {
                    // CDecoRef: alive() + operator->, no lock() to get wrong.
                    if (self.alive())
                        self->beginRollReveal();
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
        CDecoRef self = m_self;
        queueDoLater([self]() {
            // CDecoRef: alive() + operator->, no lock() to get wrong.
            if (self.alive())
                self->finishRollAnim();
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
    settleGeometryToGoal(PWINDOW); // land at goal — kill the residual open-scale tail (see helper)
    Hl::raise(PWINDOW);
    Hl::focusWindow(PWINDOW);
    // Re-register Hyprland's own decorations (border/shadow) for the freshly
    // un-hidden window. Without this an INITIAL open reveal came up with no
    // window border at all until the first move (which repositions the decos and
    // re-adds them); a move is exactly what this call stands in for.
    PWINDOW->updateWindowDecos();
    warpBorderToFocused(PWINDOW);
    VtbIpc::sendWake(appPid());
    // Mark that the revival actually happened, so finishRollAnim knows it can
    // skip repeating these ops (repeating them is the post-unroll flash). If
    // this method never runs — its doLater `self` weak-ref is orphaned to null
    // for freshly-mapped open-reveal windows, same failure the mainThreadTick
    // finalize works around — the flag stays false and finishRollAnim does the
    // un-hide itself, so the window is never left hidden (transparent).
    m_bRollRevived = true;
    // paint the live window (still under the snapshot) as one full frame
    CBox full = PWINDOW->getFullWindowBoundingBox();
    full.expand(VTB_SHADOW_SIZE + 4);
    Hl::damage(full);
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
        // the window comes back to life at its original geometry. In the normal
        // path it was ALREADY fully revived during the reveal hold
        // (beginRollReveal un-hid it, refocused it, re-added its decos, woke the
        // client and let it repaint) — all UNDER the still-drawn snapshot. So the
        // only thing left is to drop the snapshot and let that already-settled
        // window show through.
        //
        // Repeating the revival here was the post-unroll flash: the moment the
        // snapshot is gone, a SECOND sendWake re-nudged the now-uncovered
        // WebEngineView (its `visible` binding blanks it for the nudge frame ->
        // the webpage flash), and a SECOND updateWindowDecos re-registered
        // Hyprland's border deco (-> the border-outline flash). Neither is needed:
        // the window has been alive and painting behind the snapshot for the whole
        // ~90ms hold. Only fall back to the full revival if beginRollReveal never
        // ACTUALLY ran — which is gated on m_bRollRevived (set INSIDE it), NOT on
        // m_bRollReveal: the latter is set when the hold is *armed*, before the
        // deferred beginRollReveal, whose orphan-prone `self` weak-ref may never
        // fire for freshly-mapped open-reveal windows. Gating on m_bRollReveal
        // here left those windows hidden (setHidden(true) never undone) →
        // completely transparent after the open animation. Gating on
        // m_bRollRevived guarantees the un-hide happens exactly once, either way.
        const bool revived = m_bRollRevived;
        m_bRolledUp        = false;
        m_bRollReveal      = false;
        m_bRollRevived     = false;
        m_iHoverCell       = -1;
        m_bRollDragPending = false;
        m_bRollDragging    = false;
        m_bOpening         = false; // open reveal (if any) is done
        m_rollSnapTex      = nullptr;
        if (PWINDOW) {
            if (!revived) {
                PWINDOW->setHidden(false);
                settleGeometryToGoal(PWINDOW); // land at goal — kill the residual open-scale tail (see helper)
                Hl::raise(PWINDOW);
                Hl::focusWindow(PWINDOW);
                PWINDOW->updateWindowDecos(); // re-add Hyprland's border/shadow (see beginRollReveal)
                warpBorderToFocused(PWINDOW);  // snap border straight to focused tint
                // the surface was hidden; nudge the client to repaint (QtWebEngine
                // presents black after its surface is un-hidden until it redraws)
                VtbIpc::sendWake(appPid());
            }
            // Damage the FULL frame as one region — client body, the right-edge
            // titlebar deco, the border wrapping both, and the drop shadow — so
            // every side repaints on the same frame as the snapshot is dropped.
            // Damaging only the bar box (m_rollBox) left the border/titlebar on
            // the wide right edge to repaint a frame or two late, so it flashed /
            // appeared after the other three sides.
            CBox full = PWINDOW->getFullWindowBoundingBox();
            full.expand(VTB_SHADOW_SIZE + 4);
            Hl::damage(full);
        }
    }
    // ROLL_UP: the window stays hidden; the bar simply settles into its dropped
    // resting state (downTNow() now reads 1 off m_bRolledUp). If this roll-up was
    // the first half of a close, start the tail bar fade-out now.
    if (dir == ROLL_UP && m_bClosing)
        startBarFade();

    // Clear the last animation frame's drawRollBorder outline: it sat bs px
    // OUTSIDE the bar box, so a plain damageEntire() (bar box only) left a stale
    // left/edge strip that trailed until the bar was moved. Damage the bar box
    // grown by the shadow + border reach.
    const double M = VTB_SHADOW_SIZE + (PWINDOW ? PWINDOW->getRealBorderSize() : 0) + 2;
    Hl::damage(CBox{effectiveBoxGlobal()}.expand(M));
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
        Hl::damage(m_rollBox);
        PWINDOW->setHidden(false);
        Hl::raise(PWINDOW);
        Hl::focusWindow(PWINDOW);
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
    if (!g_pGlobalState || !Cfg::enabled())
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
    // the slide + shadow + drawRollBorder overhang so the next frame repaints it.
    // The margin MUST include the border size: drawRollBorder frames the visible
    // frame bs px OUTSIDE effectiveBoxGlobal on every side, so a box that stopped
    // at the bar edges left the border's outer strip un-repainted — it trailed /
    // flashed and, on the final frame, sat as a stale outline until the next move.
    if (m_rollAnim != ROLL_NONE) {
        const double M = VTB_SHADOW_SIZE + PWINDOW->getRealBorderSize() + 2;
        const double L = std::min(m_rollWinBox.x, m_rollBox.x) - M;
        const double R = m_rollBox.x + m_rollBox.w + M;
        const double T = m_rollBox.y - M;
        const double B = m_rollBox.y + std::max(m_rollBox.h, m_rollWinBox.h) + M;
        Hl::damage(CBox{L, T, R - L, B - T});
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
            Hl::damage(CBox{m_rollBox}.expand(VTB_SHADOW_SIZE)); // keep frames coming
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
            Hl::damage(CBox{m_rollBox}.expand(VTB_SHADOW_SIZE)); // final clear of the bar
            PHLWINDOWREF w = m_pWindow;
            queueDoLater([w]() {
                if (auto win = w.lock())
                    win->sendClose();
            });
        }
    }

    auto data = CVtbPassElement::SVtbData{this, barA};
    Hl::addPass(makeUnique<CVtbPassElement>(data));
}

void CVtbDeco::minimizeWindow() {
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW || !PWINDOW->m_isFloating || m_bMinimized || m_bRolledUp)
        return;

    const auto PMONITOR = PWINDOW->m_monitor.lock();
    if (!PMONITOR)
        return;

    m_minSavedPos = Hl::posGoal(PWINDOW);
    m_bMinimized  = true;
    m_minimizedAt = Time::steadyNow();

    // slide fully past the right edge (Hyprland's move animation is the
    // "slide out" itself)
    const double X = PMONITOR->m_position.x + PMONITOR->m_size.x;
    Config::Actions::move(Vector2D(X, m_minSavedPos.y), false, PWINDOW);

    // hand focus to another window on the workspace; focusing the minimized
    // window again (e.g. via its panel icon) is the restore trigger
    PHLWINDOW next = nullptr;
    for (auto& w : Hl::windows()) {
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
        Hl::focusWindow(next);
    else
        Hl::resetFocus();

    // Focusing `next` raises it to the top of the floating stack, which would
    // otherwise pop it OVER the minimizing window before its slide-out finishes
    // (the window would appear to teleport instead of sliding away). Re-raise
    // the minimizing window so it stays visually on top for the whole slide;
    // once it's off-screen its z-order no longer matters, and restore re-raises
    // it anyway.
    if (PWINDOW->m_isFloating)
        Hl::raise(PWINDOW);
}

void CVtbDeco::restoreFromMinimize() {
    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW || !m_bMinimized)
        return;

    m_bMinimized = false;
    Config::Actions::move(m_minSavedPos, false, PWINDOW);
    if (PWINDOW->m_isFloating)
        Hl::raise(PWINDOW);
    damageEntire();
}

// Leave the window the way we found it (see the .hpp): un-park a minimized one,
// un-hide a rolled-up one, and cancel any animation in flight — synchronously,
// since this runs while the plugin is being unloaded and nothing deferred will
// ever get to run. Deliberately NOT the animated paths: those schedule work on
// timers and doLater callbacks whose code is about to be unmapped.
void CVtbDeco::restoreForUnload() {
    // Take back every queued idle callback FIRST, and before the no-window
    // early return — a deco whose window has already gone can still have one
    // in flight, and this is the pass that visits every bar the plugin owns
    // (detachOurDecos, which runs after, only reaches decos still attached to a
    // window in the compositor's list). The two halves together leave nothing
    // queued into an image that is about to be unmapped. See m_pendingDoLater.
    cancelPendingDoLater();

    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW)
        return;

    if (m_bMinimized)
        restoreFromMinimize();

    m_rollAnim    = ROLL_NONE;
    m_rollSnapTex = nullptr;
    if (m_bRolledUp || PWINDOW->isHidden()) {
        m_bRolledUp    = false;
        m_bRollReveal  = false;
        m_bRollRevived = false;
        PWINDOW->setHidden(false);
        settleGeometryToGoal(PWINDOW);
        PWINDOW->updateWindowDecos(); // visible again -> Hyprland re-adds its own border/shadow
    }
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
    Hl::damage(effectiveBoxGlobal());
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
    const double BARW = g_pGlobalState && Cfg::enabled() && vtbHasBar(m_pWindow.lock()) ? (double)totalBarW() : 0.0;
    info.desiredExtents = {{(double)VTB_SHADOW_SIZE, 0.0}, {BARW, (double)VTB_SHADOW_SIZE}};
    return info;
}

void CVtbShadowDeco::onPositioningReply(const SDecorationPositioningReply& reply) {
    m_bAssignedBox = reply.assignedGeometry; // empty for ABSOLUTE; we position off the window
}

// The deco no longer PAINTS anything — vtbRenderShadowLayer below draws every
// window's shadow in one flat pass before any window. What's left here is the
// half that has to be per-window: declaring the shadow's reach (getPositioningInfo)
// so Hyprland's damage box covers it, and self-damaging the footprint as it moves.
void CVtbShadowDeco::draw(PHLMONITOR, const float&) {
    if (!validMapped(m_pWindow) || !g_pGlobalState || !Cfg::enabled())
        return;

    const auto PWINDOW = m_pWindow.lock();
    if (!PWINDOW->m_ruleApplicator->decorate().valueOrDefault() || Hl::isFullscreen(PWINDOW))
        return;

    CBox       g   = Hl::boxValue(PWINDOW);
    const auto WS  = PWINDOW->m_workspace;
    const auto OFF = (WS && !PWINDOW->m_pinned) ? WS->m_renderOffset->value() : Vector2D();
    g.translate(OFF);

    // Self-damage on motion. Hyprland's per-frame drag/animation damage covers
    // the window + border but NOT the shadow's left+bottom overhang (the
    // now-disabled native drop shadow used to incidentally cover it), so a
    // moving window trailed the hard shadow's left edge. Whenever the footprint
    // moves, damage its old ∪ new (global-logical, incl. the drag's
    // floatingOffset) so the trailing edge repaints. Stable when the window is.
    const auto&  FO     = PWINDOW->m_floatingOffset;
    const double BARW   = vtbHasBar(PWINDOW) ? (double)totalBarW() : 0.0;
    CBox         coverG = {g.x + FO.x - VTB_SHADOW_SIZE, g.y + FO.y, g.w + VTB_SHADOW_SIZE + BARW, g.h + VTB_SHADOW_SIZE};
    if (coverG.x != m_lastCoverBox.x || coverG.y != m_lastCoverBox.y || coverG.w != m_lastCoverBox.w || coverG.h != m_lastCoverBox.h) {
        if (m_lastCoverBox.w > 0)
            Hl::damage(CBox{m_lastCoverBox}.expand(2));
        Hl::damage(CBox{coverG}.expand(2));
        m_lastCoverBox = coverG;
    }
}

// ---- the flat shadow layer ------------------------------------------------
//
// Every window's hard drop shadow, painted ONCE per monitor at
// RENDER_PRE_WINDOWS, instead of each shadow deco enqueueing its own rect
// alongside its window. Two properties fall out of that which per-window rects
// could not give:
//
//  * overlapping shadows stay ONE shadow. Two 0.6-alpha black rects blended
//    over each other come out at ~0.84, so wherever two windows' shadows met
//    there was a visibly darker patch. Here the boxes are unioned into a
//    CRegion first, and pixman hands back DISJOINT rects — every shadowed pixel
//    is painted exactly once, at exactly 0.6, however many windows cast there.
//  * a shadow never lands on another (unrolled) window. Drawing before all
//    windows already puts opaque windows over it, but a translucent one would
//    still have been tinted by the shadow of the window beneath it. So every
//    visible window's frame — client box plus its titlebar strip — is subtracted
//    from the region as well: the shadow only ever falls on the desktop.
//
// Called TWICE per monitor from main.cpp's RENDER_PRE_WINDOWS hook:
//  * overBars=false, BEFORE the shade bars: the flat layer above — every
//    unrolled window's shadow plus the in-flight roll composite's, on the
//    desktop.
//  * overBars=true, AFTER the shade bars: the parts of those same shadows that
//    fall on a RESTING rolled-up bar, drawn back over the (opaque) bar so other
//    windows' shadows appear ON TOP of a rolled-up window — his report. A
//    rolled-up bar is chrome, not a window: it does NOT occlude a shadow the way
//    an unrolled window does. Restricted to the bar union so the desktop share
//    the first pass already laid down is never doubled (0.6 over 0.6 -> ~0.84).
void vtbRenderShadowLayer(PHLMONITOR pMonitor, bool overBars) {
    if (!pMonitor || !g_pGlobalState || !Cfg::enabled())
        return;

    const float ALPHA = Cfg::shadowAlpha(); // default 0.6; 0 = no shadow at all
    if (ALPHA <= 0.f)
        return;

    const double SCALE = pMonitor->m_scale;
    const double N     = VTB_SHADOW_SIZE * SCALE;
    const double BARW  = totalBarW() * SCALE;

    // over-bars pass: the resting rolled-up bars are the ONLY region it may
    // paint. Nothing rolled up -> nothing to do.
    CRegion barRegion;
    if (overBars) {
        for (auto& b : g_pGlobalState->bars) {
            CBox bb;
            if (b && b->rollBarBoxDev(pMonitor, bb))
                barRegion.add(bb);
        }
        if (barRegion.empty())
            return;
    }

    // What occludes the shadows (see vtbWindowFrames — shared with the roll
    // animation's own shadow, which has to obey the same rule).
    CRegion shadow, frames = vtbWindowFrames(pMonitor);

    for (const auto& w : Hl::windows()) {
        if (!w || !w->m_isMapped || w->isHidden())
            continue;
        if (w->m_monitor.lock() != pMonitor)
            continue;
        if (!w->m_pinned && (!w->m_workspace || !w->m_workspace->isVisible()))
            continue;

        const CBox L = vtbWindowLocalBox(pMonitor, w);
        if (L.w < 1 || L.h < 1)
            continue;

        const bool DECORATED = w->m_ruleApplicator->decorate().valueOrDefault();

        if (!DECORATED || Hl::isFullscreen(w))
            continue;

        // No shadow on our custom-maximized windows, and none from THIS loop for
        // a rolled-up one (the sibling titlebar knows). isRolledUp() stays true
        // across the whole roll-up/roll-out animation too — a window mid-roll
        // contributes the composite's collapsing shadow instead (rollShadowBoxDev
        // pass below); a window at rest rolled up casts none of its own.
        bool skip = false;
        for (auto& b : g_pGlobalState->bars) {
            if (b && b->getOwner() == w) {
                skip = b->isMaximized() || b->isRolledUp();
                break;
            }
        }
        if (skip)
            continue;

        // Frame-sized rect offset down and left; only the sharp L-overhang ends
        // up visible once the frames are subtracted. The size animvar is the client
        // surface only — the titlebar is a reserved deco on the RIGHT edge, so
        // the visible frame is that much wider; widen the shadow to match or the
        // whole bar column casts nothing. A bar-less window (scratchpad,
        // privilege prompt) spans only its own frame.
        shadow.add(CBox{L.x - N, L.y + N, L.w + (vtbHasBar(w) ? BARW : 0.0), L.h}.round());
    }

    // In-flight roll composite's own collapsing shadow — desktop only, and it
    // sits UNDER its own bar, so it belongs to the pre-bars pass. Painting it in
    // the over-bars pass would lay it on top of that bar. A window at REST rolled
    // up casts none (rollShadowBoxDev returns false unless a roll is running).
    if (!overBars) {
        for (auto& b : g_pGlobalState->bars) {
            CBox rollShadow;
            if (b && b->rollShadowBoxDev(pMonitor, rollShadow))
                shadow.add(rollShadow);
        }
    }

    if (shadow.empty())
        return;

    shadow.subtract(frames);

    // Over-bars: keep only what lands on a resting rolled-up bar. The desktop
    // share was already painted by the pre-bars pass; the opaque bar hid its
    // portion, redrawn here at full alpha so it reads as lying ON the bar.
    if (overBars)
        shadow.intersect(barRegion);

    if (shadow.empty())
        return;

    // The shadow follows the theme (DESIGN §4): its tone is the palette's
    // darkest — the bar background wal-set writes — at the user's shadow_alpha,
    // not a hard-coded black.
    CHyprColor COLOR = configColor(Cfg::bgColor());
    COLOR.a          = ALPHA;
    for (const auto& r : shadow.getRects())
        Hl::rect(CBox{(double)r.x1, (double)r.y1, (double)(r.x2 - r.x1), (double)(r.y2 - r.y1)}, COLOR);
}

void CVtbShadowDeco::damageEntire() {
    if (!validMapped(m_pWindow))
        return;
    const auto PWINDOW = m_pWindow.lock();
    CBox       g = Hl::boxValue(PWINDOW);
    const double N    = VTB_SHADOW_SIZE;
    const double BARW = g_pGlobalState && Cfg::enabled() && vtbHasBar(PWINDOW) ? (double)totalBarW() : 0.0;
    // window box grown by the shadow's left + bottom overhang, plus the titlebar
    // strip on the right (the shadow now spans it too)
    Hl::damage(CBox{g.x - N, g.y, g.w + N + BARW, g.h + N});
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

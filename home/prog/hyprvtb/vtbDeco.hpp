#pragma once

#define WLR_USE_UNSTABLE

#include <hyprland/src/render/decorations/IHyprWindowDecoration.hpp>
#include <hyprland/src/render/OpenGL.hpp>
#include <hyprland/src/devices/IPointer.hpp>
#include <hyprland/src/helpers/signal/Signal.hpp>
#include <hyprland/src/helpers/time/Time.hpp>
#include "globals.hpp"
#include "vtbIpc.hpp"
// Every volatile Hyprland internal this plugin touches goes through here —
// see vtbCompat.hpp and PORTING.md.
#include "vtbCompat.hpp"

namespace Event {
    struct SCallbackInfo;
}

// Vertical titlebar drawn by the compositor on the RIGHT edge of every
// window — top to bottom: close [x], maximize [■] (fill-usable-area toggle,
// not fullscreen), minimize [»] (slides the window off the right edge;
// focusing it again — e.g. from the panel taskbar — slides it back), pin
// [o>] (Hyprland pin — window kept on top / shown on all workspaces),
// roll-up [>>] (windowshade — hides the whole window, leaving only this bar
// floating in place; click it again to restore. The window is genuinely
// hidden, not resized, so it works for every app regardless of min size and
// no client sliver is left over; the hidden window's bar is drawn by a
// render-stage hook in main.cpp since Hyprland no longer renders the window),
// then the title as a column of upright letters reading top-down. Rendered as a
// sticky window decoration with priority above the border and
// DECORATION_PART_OF_MAIN_WINDOW, so Hyprland's own active/inactive border
// wraps window + titlebar as one frame and the bar is locked to the window
// in the same rendered frame — the whole reason this is a plugin and not a
// layer-shell client.
class CVtbDeco : public IHyprWindowDecoration {
  public:
    CVtbDeco(PHLWINDOW);
    virtual ~CVtbDeco();

    virtual SDecorationPositioningInfo getPositioningInfo();
    virtual void                       onPositioningReply(const SDecorationPositioningReply& reply);
    virtual void                       draw(PHLMONITOR, float const& a);
    virtual eDecorationType            getDecorationType();
    virtual void                       updateWindow(PHLWINDOW);
    virtual void                       damageEntire();
    virtual eDecorationLayer           getDecorationLayer();
    virtual uint64_t                   getDecorationFlags();
    virtual std::string                getDisplayName();

    PHLWINDOW                          getOwner();
    void                               onConfigReloaded();
    bool                               isMaximized() const { return m_bMaximized; } // for the sibling shadow deco
    bool                               isRollingOut() const { return m_rollAnim == ROLL_OUT; } // slide-out draws OVER windows
    bool                               isOpening() const { return m_bOpening; }                // open reveal also draws OVER windows
    bool                               isRollingUpSlide() const;                               // roll-up's slide beat draws OVER windows too
    bool                               isMinimized() const { return m_bMinimized; } // for session snapshot
    bool                               isRolledUp() const { return m_bRolledUp; }   // for session snapshot

    // Shove this window's SHADED bar back inside the un-covered horizontal band
    // of its own monitor (`reserve` px taken off the right edge, or off the left
    // when edgeRight is false), returning true if it moved. Public because only
    // the plugin can do this at all: a rolled-up bar is drawn at the frozen
    // m_rollBox of a hidden window, so an outside `window.move` moves nothing
    // visible. Driven by hyprvtb.push_rolled() when the panel grows into a dock.
    bool                               pushRolledIntoBand(double reserve, bool edgeRight);

    // The mid-roll composite's drop shadow, in pMonitor's device pixels. False
    // when there is none to draw. vtbRenderShadowLayer calls this so the roll's
    // shadow joins the SAME union as every resting window's — see the
    // definition for what drawing it separately used to cost.
    bool                               rollShadowBoxDev(PHLMONITOR pMonitor, CBox& out);

    // The resting/set-down bar box of a rolled-up window, in pMonitor's device
    // pixels. False for a bar drawing over the windows this frame (roll-out /
    // open / roll-up slide) or a window not rolled up. vtbRenderShadowLayer's
    // over-bars pass unions these — other windows' shadows land on top of them.
    bool                               rollBarBoxDev(PHLMONITOR pMonitor, CBox& out);

    // Put this window back into a plain, visible state — no animation, no
    // deferred work. PLUGIN_EXIT calls it for every bar: the states this plugin
    // puts a window INTO (rolled up = setHidden, minimized = parked off-screen)
    // are states only this plugin knows how to leave, and the instance that
    // replaces us on a `hyprctl reload` hot swap does not inherit them. Without
    // it a swap strands every rolled/minimized window — invisible or
    // off-screen, with nothing left that could bring it back.
    void                               restoreForUnload();

    // Called from main.cpp's render-stage hook (RENDER_POST_WINDOWS): a shaded
    // window is hidden, so Hyprland won't render it or call our draw() — this
    // enqueues the bar's pass element for the shade to stay visible in place.
    void                               renderShadeIfRolled(PHLMONITOR);

    // Called from main.cpp's RENDER_POST_WINDOWS hook: enqueues the hover
    // tooltip as a pass element that draws OVER the window surface (the bar's
    // own UNDER-layer pass draws before the window, so a tooltip drawn there —
    // it overhangs the window to the left — is painted over and invisible).
    void                               enqueueTooltip(PHLMONITOR);

    // Public: also invoked through the hyprvtb.* lua functions / dispatchers
    // (panel icon click minimizes the active window, hyprvtb:rollup, etc.).
    void                               minimizeWindow();
    void                               toggleMaximize();
    void                               toggleRollup(bool animate = true);
    void                               closeWindow(); // titlebar [x] / hyprvtbclose dispatcher: roll-up + fade close animation
    void                               startOpenReveal(); // open animation: fade titlebar in, then roll out to reveal + focus

    // Called from main.cpp's window.active listener: focusing a minimized
    // window slides it back in.
    void                               onFocusGained();

    // Called from main.cpp's 150ms main-thread timer: damages the bar when
    // the app-button registration changed, and pops the hover tooltip once
    // its dwell has passed (a motionless cursor generates no move events).
    void                               mainThreadTick(uint64_t ipcSerial);

    // The geometry that should be remembered for this window (the restore
    // position if it's currently minimized, its live goal otherwise).
    CBox                               memorableGeometry();

    // Would this titlebar eat a vertical wheel event at this cursor position
    // (PLAYBAR scrub track / open address editor)? Public because vtbKinetic
    // has to ask before starting a momentum fling and on every tick of one —
    // reached through the free vtbAxisConsumerAtCursor() in globals.hpp, so the
    // kinetic module never names a decoration type.
    bool                               consumesAxisAt(const Vector2D& mouse);

    CDecoRef                           m_self;

  private:
    PHLWINDOWREF         m_pWindow;
    CBox                 m_bAssignedBox;

    SP<Render::ITexture> m_pTitleTex;
    std::map<std::string, SP<Render::ITexture>> m_glyphCache; // "glyph|rgbahex" -> tex
    std::string          m_szLastTitle;
    int                  m_iLastTitleRun = -1;
    float                m_fLastScale    = -1;
    uint64_t             m_lastTextColor = 0;
    bool                 m_bLastFocus    = false;

    // App-button column (the inner half of the double-wide bar) — buttons a
    // client registered for this window's PID over the vtbIpc socket.
    pid_t                m_appPid        = -1; // -1 = not resolved yet, 0 = none
    uint64_t             m_lastIpcSerial = 0;  // last global VtbIpc::serial this deco looked at
    // The registration this bar DRAWS and HIT-TESTS from. Only mainThreadTick
    // refreshes it — never the render path. See appReg().
    SVtbAppReg           m_regSnap;
    bool                 m_bHasReg = false;
    SP<Render::ITexture> m_pFooterTex;         // stacked footer text, bottom of the inner column
    std::string          m_szLastFooter;
    int                  m_iLastFooterRun = -1;
    int                  m_iFooterTextH   = 0; // real pango height, for bottom-anchoring

    bool                 m_bMaximized = false;
    CBox                 m_savedGeometry;

    bool                 m_bRolledUp = false;
    CBox                 m_rollBox; // raised (undropped) bar box captured when shaded (for render + hit-test while hidden)

    // ---- roll-up / roll-out slide+setdown animation ----
    // Rolling a window up plays as two beats: the window's content slides right
    // into the bar — a snapshot, clipped at the bar's left edge, so it vanishes
    // behind the bar like a closing drawer, its shadow trailing — then the bar
    // "sets down" into the desktop: it drops by the shadow offset while the drop
    // shadow collapses from its 24px float to nothing (swallowed by the bar) and
    // the tint crossfades focused->unfocused. Roll-out is the exact reverse. The
    // window is hidden for the whole animation; the snapshot captured at shade
    // time carries its pixels through both directions (it can't change while
    // hidden). The static rolled state is the end of roll-up: bar dropped by the
    // shadow offset, no shadow.
    enum eRollAnim { ROLL_NONE, ROLL_UP, ROLL_OUT };
    eRollAnim            m_rollAnim         = ROLL_NONE;
    float                m_rollProgress     = 0.f;            // 0..1 along the current direction
    bool                 m_rollFinishing    = false;          // progress hit 1; finalize deferred out of the render
    Time::steady_tp      m_rollAnimAt       = Time::steadyNow(); // last frame stamp (dt clock)
    SP<Render::ITexture> m_rollSnapTex;                       // window content, held across the shade
    SP<Render::IFramebuffer> m_fadeFB;                        // offscreen bar for the composited lone-bar fade (see renderPass)
    CBox                 m_rollWinBox;                        // client box (global logical) at shade time
    Vector2D             m_rollSnapOrigin;                    // window's top-left within the (monitor-sized) snapshot texture, device px
    bool                 m_bRollReveal   = false;             // roll-out slide landed; reveal hold ARMED (set before the deferred beginRollReveal — NOT proof it ran)
    bool                 m_bRollRevived  = false;             // beginRollReveal ACTUALLY ran (un-hid/refocused/re-decorated the window). Its doLater uses the orphan-prone `self` weak-ref, so for freshly-mapped (open-reveal) windows it may never fire — this flag, set INSIDE it, lets finishRollAnim know whether it still needs to do the revival itself
    Time::steady_tp      m_rollRevealAt  = Time::steadyNow(); // when the reveal hold began (client-repaint grace period)

    // Window-close animation: the [x] button rolls the window up, then fades the
    // lone bar out, and only THEN asks the client to close — so the whole thing
    // plays while the window (and this deco) are still alive. Client-initiated
    // closes bypass this and just vanish.
    bool                 m_bClosing        = false;
    bool                 m_bBarFading      = false; // tail fade-out phase active
    float                m_barFadeProgress = 0.f;   // 0 = opaque .. 1 = gone
    Time::steady_tp      m_barFadeAt       = Time::steadyNow();
    bool                 m_bCloseReady     = false; // fade done; sendClose() pending

    // Window-open animation: a freshly-mapped window is captured + hidden, its
    // lone titlebar fades IN, then it rolls OUT to reveal the content and takes
    // focus — the mirror image of the close animation.
    bool                 m_bOpening        = false;
    bool                 m_bBarFadingIn    = false; // opening: the initial bar fade-in phase

    bool                 m_bMinimized = false;
    Vector2D             m_minSavedPos;
    Time::steady_tp      m_minimizedAt = Time::steadyNow();

    int                  m_iHoverCell = -1; // 0-4 system cells, 1000+i app cells, -1 none

    // ---- title address editor (opt-in per app via TITLEEDIT; surfer's URL bar) ----
    // The stacked title under the system cells becomes an editable field: a
    // click enters edit mode, the compositor grabs the keyboard (swallowing keys
    // before keybinds/clients), draws a caret in the vertical text, and Enter
    // sends the result back as ADDR. Editing requires the window focused and is
    // cancelled if focus is lost.
    bool                 m_bEditing        = false;
    std::string          m_editBuf;                    // UTF-8 edit buffer
    size_t               m_editCursor      = 0;        // byte offset, codepoint boundary
    // selection is the range [min,max] of anchor..cursor; empty (no selection)
    // when anchor == cursor. Opening the editor selects the whole field
    // (anchor 0, cursor end); click places a caret, click-drag / Shift+move
    // extends. Both are byte offsets on codepoint boundaries.
    size_t               m_editSelAnchor   = 0;
    bool                 m_bEditDragging   = false;    // mouse selecting in the field
    int                  m_editScrollCp    = 0;        // first visible codepoint row (long-URL scroll)
    size_t               m_editLastCaret   = 0;        // caret pos last frame (to auto-scroll only on caret moves)
    SP<Render::ITexture> m_pEditTex;                   // full text (textColor); rebuilt on buffer/selection change
    SP<Render::ITexture> m_pEditSelTex;                // selected substring (bgColor) overlaid on the highlight
    int                  m_iEditLineH      = 0;        // device-px height of one stacked codepoint
    int                  m_iEditLines      = 0;        // codepoint lines currently drawn
    Time::steady_tp      m_editBlinkAt     = Time::steadyNow();
    bool                 m_bTitlePressPending = false; // press landed in the title region (click vs drag)
    bool                 m_bTitlePressFocusOnly = false; // that press only focused an unfocused window — don't edit
    CHyprSignalListener  m_pKeyboardKeyCallback;

    // ---- app-button drag-reorder (draggable buttons, e.g. surfer tabs) ----
    // App-button clicks fire on RELEASE now (so press+drag can reorder instead):
    // a press on an app cell arms this; a release without a drag is the click, a
    // drag past a threshold reorders (draggable buttons only) and sends REORDER.
    bool                 m_bAppPressPending  = false;
    bool                 m_bAppDragging      = false;
    int                  m_iAppPressIdx      = -1;     // reg index of the pressed button
    std::string          m_appPressId;                 // its id (for CLICK / REORDER)
    bool                 m_appPressDraggable = false;
    Vector2D             m_appDragMouseStart;
    int                  m_iAppDragTarget    = -1;     // reg index the drag currently hovers

    // ---- media scrub bar (viewer video; vtbIpc PLAYBAR/SEEK) ----
    // A vertical progress track drawn in the inner column below the footer while
    // a client (viewer) is playing a video. Pressing/dragging it scrubs (sends
    // SEEK with the fraction under the cursor); scrolling nudges. While dragging
    // the fill follows the cursor immediately (m_playbarDragFrac) instead of
    // waiting for the client's echoed PLAYBAR.
    // Hit-test the track with CBox::containsPoint, NOT VECINRECT: that macro
    // takes (x1, y1, x2, y2) corners, and feeding it the box's (x, y, w, h)
    // silently clipped the live target to the top slice of the drawn groove —
    // the taller the bar, the deader it got (player's 420px track responded
    // only in its first ~90px, which read as "the scrub bar does nothing").
    bool                 m_bPlaybarDragging = false;
    double               m_playbarDragFrac  = 0.0;

    // Where we last ASKED the client to seek to, held until its echo agrees.
    //
    // Releasing a scrub used to hand the fill straight back to reg.playPos, and
    // a media client cannot answer that fast: the player pushes PLAYBAR off a
    // 250ms timer reading mpv's clock, and mpv reports the PRE-seek position
    // for a tick or two after the seek. So the fill snapped back to where the
    // track was, jumped forward when the seek landed, and did it again for each
    // stale tick already in flight — the "bounces a few times before settling".
    // Rendering this pending value instead makes the bar answer the click
    // immediately and only defer to the client once it has caught up. It also
    // gives repeated scrolls a stable base to accumulate from, instead of each
    // notch re-deriving its step from a position two ticks out of date.
    double                                m_playbarPendingFrac = -1.0; // <0 = none pending
    std::chrono::steady_clock::time_point m_playbarPendingAt{};

    // Sub-detent scroll remainder, carried between axis events.
    //
    // The pending value above is the right BASE to accumulate from and always
    // was; what was missing is the other half — the per-event MAGNITUDE. A
    // trackpad delivers a detent's worth of motion as a burst of small deltas,
    // so each event's fraction of a VTB_PLAYBAR_SCROLL step lands here and is
    // committed once it adds up to something the bar can actually show. Kept as
    // a sibling of the pending value rather than folded into it: that one is a
    // POSITION the bar renders and the client's echo retires, this is an
    // uncommitted DELTA nothing else may see. See playbarScrollBy.
    double                                m_playbarScrollAcc = 0.0;

    // Click-activation flash: the clicked cell briefly inverts (fills with its
    // highlight colour, label drawn in the bar background) so a press reads as
    // "activated". Same cell-id space as m_iHoverCell.
    int                  m_flashCell = -1;
    Time::steady_tp      m_flashAt   = Time::steadyNow();

    // Hover tooltips: after a dwell on a cell (detected by the main-thread
    // timer, since a motionless cursor emits no move events), a themed label
    // pops out to the LEFT of the bar. Drawn as its OWN pass element at
    // RENDER_POST_WINDOWS (see enqueueTooltip) so it sits over the window
    // surface — the bar's UNDER-layer pass draws before the window and the
    // label overhangs the window's area.
    Time::steady_tp      m_hoverSince   = Time::steadyNow();
    bool                 m_bTooltipShown = false; // element active (visible OR still animating out)
    bool                 m_ttWantShown   = false; // slide target: 1 while dwelt+hovering, 0 to retract
    int                  m_ttCell        = -1;    // cell the current tooltip belongs to (survives hover change during slide-out)
    float                m_ttPhase       = 0.f;   // 0 fully retracted .. 1 fully out (eased slide+fade)
    Time::steady_tp      m_ttPhaseAt     = Time::steadyNow(); // last phase advance, for dt
    CBox                 m_tooltipBox;      // last drawn box, GLOBAL logical (for damage)
    std::map<std::string, SP<Render::ITexture>> m_tooltipCache; // "text|rgbahex" -> tex

    bool                 m_bDragPending   = false;
    bool                 m_bDraggingThis  = false;
    bool                 m_bCancelledDown = false;

    // Shade-drag: dragging a rolled-up window's floating bar relocates the
    // (still-hidden) window; a press that never moves is a click, and only a
    // click on the roll-up cell ([<<]) unrolls — a click elsewhere is inert.
    bool                 m_bRollDragPending = false;
    bool                 m_bRollDragging    = false;
    int                  m_iRollPressCell   = -1; // cell hit on the shaded-bar press (4 == unroll)
    Vector2D             m_rollDragMouseStart;
    CBox                 m_rollDragBoxStart;
    Vector2D             m_rollDragWinStart;

    // KDE-style resize engine: Hyprland's own resize (border or resizewindow)
    // is always corner-quadrant based — grabbing the middle of one side still
    // moves two edges. This engine resizes exactly the edges the grab point
    // implies (side handle -> one edge, corner zone -> two).
    bool                 m_bEdgeResizing = false;
    bool                 m_bCursorOverridden = false; // we set the WINDOW_EDGE cursor override
    uint32_t             m_resizeEdges   = 0; // RS_EDGE_* bitmask
    Vector2D             m_resStartMouse;
    CBox                 m_resStartBox;

    CHyprSignalListener  m_pMouseButtonCallback;
    CHyprSignalListener  m_pMouseMoveCallback;
    CHyprSignalListener  m_pMouseAxisCallback;

    // ---- deferred (idle) callbacks this deco has queued ----
    //
    // The roll animation and the close animation finalize themselves off the
    // render loop via Hl::doLater. Those lambdas guard the OBJECT's lifetime
    // (CDecoRef::alive(), PHLWINDOWREF::lock()) — but nothing guarded their
    // CODE, which lives in this .so: a callback still sitting in the
    // compositor's idle list when `hyprctl reload` dlclose()s this image runs
    // into unmapped memory. Same family as the timer PLUGIN_EXIT already
    // removes and the decorations it already detaches, just one event-loop turn
    // wide instead of 150ms — which is why it had never been seen, only
    // deduced. So every sequence goes in here and is cancelled on the way out
    // (~CVtbDeco and restoreForUnload). Callbacks retire their own sequence as
    // they fire, so this holds exactly the ones still in flight (0..3).
    std::vector<uint64_t> m_pendingDoLater;

    // Queue fn on the next event-loop turn, tracked in m_pendingDoLater. Use
    // this, never a bare Hl::doLater(), for anything queued from a deco.
    void                 queueDoLater(std::function<void()> fn);
    void                 retireDoLater(uint64_t seq); // fn ran: stop tracking it
    void                 cancelPendingDoLater();      // unload / destruction: drop them all

    void                 renderPass(PHLMONITOR, float const& a);
    void                 renderBar(PHLMONITOR, float a); // the actual bar drawing; renderPass wraps it (direct, or FBO-composited while fading)
    void                 renderTitleTex(int runLenPx, float scale, const CHyprColor& color);
    SP<Render::ITexture> renderStackedTex(const std::string& text, int runLenPx, float scale, const CHyprColor& color, int* outTextH = nullptr,
                                          int* outLines = nullptr, bool ellipsis = true, bool flatColon = false);
    SP<Render::ITexture> glyphTex(const std::string& glyph, const CHyprColor& color, float scale);

    // title address editor
    bool                 titleEditEnabled();
    int                  titleTopEff();  // titleTop() + a reserved spinner slot while the page loads
    bool                 inTitleRegion(const Vector2D& localCoords);
    void                 enterEdit();
    void                 exitEdit(bool submit);
    void                 onKeyboardKey(Event::SCallbackInfo& info, const IKeyboard::SKeyEvent& e);
    bool                 deleteEditSelection();          // erase the selected range; true if there was one
    void                 pasteIntoEdit();                // read the wl clipboard and insert it at the caret (async)
    void                 insertEditText(const std::string& text); // sanitize + insert text at the caret, replacing any selection
    size_t               editByteAtLocalY(double localY); // bar-local Y -> byte offset (codepoint boundary)
    int                  editVisibleRows();              // codepoint rows that fit in the editor
    void                 ensureEditCaretVisible();       // scroll so the caret row is on-screen

    pid_t                appPid();
    // This window's registration as of the last tick, or false if it has none.
    // Everything that draws or hit-tests the bar reads THIS, not VtbIpc::get —
    // the snapshot is only ever advanced by mainThreadTick, which prewarms the
    // glyphs for it first, so the render path can never draw text whose texture
    // is being created in the same tiler job (the flash-blank).
    bool                 appReg(SVtbAppReg& out) const;
    int                  appCellAt(const Vector2D& localCoords, const SVtbAppReg& reg);
    // The media scrub track, bar-local LOGICAL px (x,y = top of the track, w =
    // the full inner-column width used as the click/scroll hit region, h = track
    // length). False when no scrub bar is shown or the window is too short.
    bool                 playbarTrackLocal(const SVtbAppReg& reg, double contentH, double scale, CBox& out);
    // The fraction the scrub bar should DRAW, and the one a scroll should step
    // from: the live drag, else a pending seek the client hasn't echoed yet,
    // else the client's own position. Retires the pending value once the echo
    // agrees (or gives up on it) — see m_playbarPendingFrac.
    double               playbarFrac(const SVtbAppReg& reg);
    // A wheel/trackpad event over the track, delta-proportional: one detent's
    // worth of motion = one VTB_PLAYBAR_SCROLL step, sub-detent remainder
    // carried in m_playbarScrollAcc.
    void                 playbarScrollBy(const SVtbAppReg& reg, const IPointer::SAxisEvent& e);
    void                 playbarSeekTo(double frac);
    int                  appDropSlot(const Vector2D& localCoords, const SVtbAppReg& reg); // nearest draggable slot to cursor Y
    void                 prewarmGlyphs(); // upload app-button glyph textures ahead of the render (Asahi tiler race)
    std::string          tooltipForCell(int cell); // "" = none
    double               cellCenterY(int cell);    // bar-local logical y of a hover cell's centre
    void                 renderTooltip(PHLMONITOR, const CBox& barBox, float scale, float a);
    void                 drawTooltipPass(PHLMONITOR, float a); // computes barBox, then renderTooltip
    void                 hideTooltip();
    void                 flashCell(int cell); // start the click-activation flash on a cell

    bool                 inputIsValid();
    void                 onMouseButton(Event::SCallbackInfo& info, IPointer::SButtonEvent e);
    void                 onMouseMove(Vector2D coords);
    void                 onMouseAxis(Event::SCallbackInfo& info, const IPointer::SAxisEvent& e);
    void                 handleDownEvent(Event::SCallbackInfo& info);
    void                 handleUpEvent(Event::SCallbackInfo& info);
    void                 handleRolledDown(Event::SCallbackInfo& info); // press on a shaded window's floating bar
    void                 handleRolledUp(Event::SCallbackInfo& info);   // release: click un-shades, drag ends move
    bool                 shadeOccludedAt(const Vector2D& mouse);       // is anything drawn ABOVE the shade bar at this point?
    int                  cellAt(const Vector2D& localCoords);

    bool                 tryStartEdgeResize(Event::SCallbackInfo& info, const IPointer::SButtonEvent& e);
    uint32_t             borderResizeZone(const Vector2D& mouse);
    uint32_t             interiorResizeZone(const Vector2D& mouse);
    void                 updateEdgeResize();
    void                 endEdgeResize();

    void                 togglePin();
    void                 restoreFromMinimize();
    CBox                 maximizeTarget();

    // roll animation
    void                 startRollAnim(eRollAnim dir);
    void                 stepRollAnim();                       // advance progress by dt; finalize at 1
    void                 beginRollReveal();                    // roll-out landed: un-hide the window under the held snapshot
    void                 warpBorderToFocused(PHLWINDOW pWindow); // snap border to active on reveal (no post-unroll fade)
    void                 finishRollAnim();                     // commit the end state
    void                 startBarFade();                       // begin the close animation's tail bar fade-out
    void                 hideRolledWindow(PHLWINDOW);          // setHidden + focus handoff
    bool                 rollAnimSubProgress(float& slideT, float& downT); // eased pair; false when idle
    float                downTNow();                           // 0 raised (full shadow) .. 1 set down (no shadow)
    // The animation's two behind-the-bar pieces. The shadow is drawn BEFORE the
    // bar (so the bar/snapshot occlude its centre, leaving only the L-overhang);
    // the sliding snapshot AFTER (clipped at the bar's left edge). Both take the
    // bar's device-space box (already dropped by the set-down).
    void                 drawRollSnapshot(const CBox& barBoxDev, float scale, float slideT, float a);
    void                 drawRollBorder(const CBox& barBoxDev, float scale, float slideT, const CHyprColor& focused, const CHyprColor& unfocused, float a);

    Vector2D             cursorRelativeToBar();
    CBox                 assignedBoxGlobal();
    CBox                 effectiveBoxGlobal(); // m_rollBox while shaded, else assignedBoxGlobal()

    friend class CVtbPassElement;
};

// Paint every window's hard drop shadow on this monitor, as one flat layer of
// disjoint rects under all windows — see the definition in vtbDeco.cpp for why
// the shadows are not drawn per-window any more. Called TWICE from main.cpp's
// RENDER_PRE_WINDOWS hook: overBars=false before the shade bars (the desktop
// layer), overBars=true after them (the parts that fall on a resting rolled-up
// bar, drawn over it so other windows' shadows appear on top of it).
void vtbRenderShadowLayer(PHLMONITOR pMonitor, bool overBars = false);

// Reset the process-global PangoCairo font map so the next titlebar draw
// re-reads fontconfig — the only in-process way the bars pick up a font
// installed after the compositor started. Called from PLUGIN_INIT, so a plugin
// hot-swap doubles as a titlebar font-DB refresh. See the definition.
void vtbRefreshFontMap();

// The bottom-left hard drop shadow's per-window half: it declares the shadow's
// reach and damages it as the window moves, but the pixels are drawn by
// vtbRenderShadowLayer. It exists as its OWN decoration because the titlebar is
// a STICKY-right deco, so it can only ever declare a right-edge extent —
// Hyprland would never damage a bottom-left region as the window moves, which
// is what made the shadow trail. This is an ABSOLUTE, non-reserved, NON_SOLID
// deco that declares LEFT+BOTTOM extents, putting the shadow area inside the
// window's damage box.
class CVtbShadowDeco : public IHyprWindowDecoration {
  public:
    CVtbShadowDeco(PHLWINDOW);
    virtual ~CVtbShadowDeco();

    virtual SDecorationPositioningInfo getPositioningInfo();
    virtual void                       onPositioningReply(const SDecorationPositioningReply& reply);
    virtual void                       draw(PHLMONITOR, float const& a);
    virtual eDecorationType            getDecorationType();
    virtual void                       updateWindow(PHLWINDOW);
    virtual void                       damageEntire();
    virtual eDecorationLayer           getDecorationLayer();
    virtual uint64_t                   getDecorationFlags();
    virtual std::string                getDisplayName();

  private:
    PHLWINDOWREF m_pWindow;
    CBox         m_bAssignedBox;
    CBox         m_lastCoverBox; // last drawn footprint (global logical); self-damage its move so it doesn't trail
};

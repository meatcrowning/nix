#pragma once

#define WLR_USE_UNSTABLE

#include <hyprland/src/render/decorations/IHyprWindowDecoration.hpp>
#include <hyprland/src/render/OpenGL.hpp>
#include <hyprland/src/devices/IPointer.hpp>
#include <hyprland/src/helpers/signal/Signal.hpp>
#include <hyprland/src/helpers/time/Time.hpp>
#include "globals.hpp"
#include "vtbIpc.hpp"

// inputIsValid() pokes at InputManager internals, same as hyprbars does.
#define private public
#include <hyprland/src/managers/input/InputManager.hpp>
#undef private

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
    bool                               isMinimized() const { return m_bMinimized; } // for session snapshot
    bool                               isRolledUp() const { return m_bRolledUp; }   // for session snapshot

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
    void                               toggleRollup();

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

    WP<CVtbDeco>                       m_self;

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
    uint64_t             m_lastIpcSerial = 0;  // damage when VtbIpc::serial moves
    SP<Render::ITexture> m_pFooterTex;         // stacked footer text, bottom of the inner column
    std::string          m_szLastFooter;
    int                  m_iLastFooterRun = -1;
    int                  m_iFooterTextH   = 0; // real pango height, for bottom-anchoring

    bool                 m_bMaximized = false;
    CBox                 m_savedGeometry;

    bool                 m_bRolledUp = false;
    CBox                 m_rollBox; // on-screen bar box captured when shaded (for render + hit-test while hidden)

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
    bool                 m_editSelectAll   = false;    // whole field selected (initial state)
    SP<Render::ITexture> m_pEditTex;                   // rebuilt on every buffer/selection change
    int                  m_iEditLineH      = 0;        // device-px height of one stacked codepoint
    int                  m_iEditLines      = 0;        // codepoint lines currently drawn
    Time::steady_tp      m_editBlinkAt     = Time::steadyNow();
    bool                 m_bTitlePressPending = false; // press landed in the title region (click vs drag)
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

    void                 renderPass(PHLMONITOR, float const& a);
    void                 renderTitleTex(int runLenPx, float scale, const CHyprColor& color);
    SP<Render::ITexture> renderStackedTex(const std::string& text, int runLenPx, float scale, const CHyprColor& color, int* outTextH = nullptr,
                                          int* outLines = nullptr, bool ellipsis = true);
    SP<Render::ITexture> glyphTex(const std::string& glyph, const CHyprColor& color, float scale);

    // title address editor
    bool                 titleEditEnabled();
    bool                 inTitleRegion(const Vector2D& localCoords);
    void                 enterEdit();
    void                 exitEdit(bool submit);
    void                 onKeyboardKey(Event::SCallbackInfo& info, const IKeyboard::SKeyEvent& e);

    pid_t                appPid();
    int                  appCellAt(const Vector2D& localCoords, const SVtbAppReg& reg);
    int                  appDropSlot(const Vector2D& localCoords, const SVtbAppReg& reg); // nearest draggable slot to cursor Y
    std::string          tooltipForCell(int cell); // "" = none
    double               cellCenterY(int cell);    // bar-local logical y of a hover cell's centre
    void                 renderTooltip(PHLMONITOR, const CBox& barBox, float scale, float a);
    void                 drawTooltipPass(PHLMONITOR, float a); // computes barBox, then renderTooltip
    void                 hideTooltip();
    void                 flashCell(int cell); // start the click-activation flash on a cell

    bool                 inputIsValid();
    void                 onMouseButton(Event::SCallbackInfo& info, IPointer::SButtonEvent e);
    void                 onMouseMove(Vector2D coords);
    void                 handleDownEvent(Event::SCallbackInfo& info);
    void                 handleUpEvent(Event::SCallbackInfo& info);
    void                 handleRolledDown(Event::SCallbackInfo& info); // press on a shaded window's floating bar
    void                 handleRolledUp(Event::SCallbackInfo& info);   // release: click un-shades, drag ends move
    int                  cellAt(const Vector2D& localCoords);

    bool                 tryStartEdgeResize(Event::SCallbackInfo& info, const IPointer::SButtonEvent& e);
    uint32_t             borderResizeZone(const Vector2D& mouse);
    uint32_t             interiorResizeZone(const Vector2D& mouse);
    void                 updateEdgeResize();
    void                 endEdgeResize();

    void                 closeWindow();
    void                 togglePin();
    void                 restoreFromMinimize();
    CBox                 maximizeTarget();

    Vector2D             cursorRelativeToBar();
    CBox                 assignedBoxGlobal();
    CBox                 effectiveBoxGlobal(); // m_rollBox while shaded, else assignedBoxGlobal()

    friend class CVtbPassElement;
};

// The bottom-left hard drop shadow, as its OWN decoration rather than something
// the titlebar draws. The titlebar is a STICKY-right deco, so it can only ever
// declare a right-edge extent — Hyprland would never damage a bottom-left
// region as the window moves, which is what made the shadow trail. This is an
// ABSOLUTE, non-reserved, NON_SOLID deco that declares LEFT+BOTTOM extents (so
// the shadow area is part of the window's damage box) and renders a plain rect
// pass element (region-accurate occlusion behind the window — no flashing).
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
};

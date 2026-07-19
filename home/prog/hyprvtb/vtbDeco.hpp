#pragma once

#define WLR_USE_UNSTABLE

#include <hyprland/src/render/decorations/IHyprWindowDecoration.hpp>
#include <hyprland/src/render/OpenGL.hpp>
#include <hyprland/src/devices/IPointer.hpp>
#include <hyprland/src/helpers/signal/Signal.hpp>
#include <hyprland/src/helpers/time/Time.hpp>
#include "globals.hpp"

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
// focusing it again — e.g. from the panel taskbar — slides it back), then
// the title as a column of upright letters reading top-down. Rendered as a
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

    // Public: also invoked through the hyprvtb.* lua functions (panel icon
    // click minimizes the active window, etc.).
    void                               minimizeWindow();
    void                               toggleMaximize();

    // Called from main.cpp's window.active listener: focusing a minimized
    // window slides it back in.
    void                               onFocusGained();

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

    bool                 m_bMaximized = false;
    CBox                 m_savedGeometry;

    bool                 m_bMinimized = false;
    Vector2D             m_minSavedPos;
    Time::steady_tp      m_minimizedAt = Time::steadyNow();

    int                  m_iHoverCell = -1; // 0 close, 1 max, 2 min, -1 none

    bool                 m_bDragPending   = false;
    bool                 m_bDraggingThis  = false;
    bool                 m_bCancelledDown = false;

    CHyprSignalListener  m_pMouseButtonCallback;
    CHyprSignalListener  m_pMouseMoveCallback;

    void                 renderPass(PHLMONITOR, float const& a);
    void                 renderTitleTex(int runLenPx, float scale, const CHyprColor& color);
    SP<Render::ITexture> glyphTex(const std::string& glyph, const CHyprColor& color, float scale);

    bool                 inputIsValid();
    void                 onMouseButton(Event::SCallbackInfo& info, IPointer::SButtonEvent e);
    void                 onMouseMove(Vector2D coords);
    void                 handleDownEvent(Event::SCallbackInfo& info);
    void                 handleUpEvent(Event::SCallbackInfo& info);
    int                  cellAt(const Vector2D& localCoords);

    void                 closeWindow();
    void                 restoreFromMinimize();
    CBox                 maximizeTarget();

    Vector2D             cursorRelativeToBar();
    CBox                 assignedBoxGlobal();

    friend class CVtbPassElement;
};

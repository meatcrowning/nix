#pragma once

// App-button IPC ("the inner half of the double-wide titlebar"): a Unix socket
// at $XDG_RUNTIME_DIR/hyprvtb-buttons.sock where client apps register a column
// of program-specific buttons for their own windows, keyed by PID.
//
// Wire protocol (newline-terminated ASCII lines):
//   client -> server:
//     REGISTER <pid> <id>:<label>:<state>[:<tooltip>[:<drag>[:<bottom>]]]|...
//         Replaces the client's whole button set (re-send any time state
//         changes — labels and states are data, not fixed at startup).
//         state: 0 normal, 1 active/lit (toggles), 2 disabled (drawn dim,
//         clicks ignored). tooltip is optional hover text. drag ("1") marks the
//         button reorderable: dragging it up/down the column sends a REORDER
//         back (surfer's tabs). bottom ("1") anchors the button to the BOTTOM of
//         the inner column (stacked upward, below the top group and above the
//         footer) — surfer's settings button. Fields are percent-encoded by the
//         client (%3A ':', %7C '|', %0A newline) and decoded here, so a label
//         may be any glyph incl. "|" or ":". An entry with id "-" is a separator.
//     FOOTERPOS <0|1>  footer below the scrub bar instead of above it (player)
//     FOOTER <text>
//         Short text drawn as stacked upright characters at the bottom of the
//         inner column (filer's dir-size readout). Empty text clears it.
//     TITLEEDIT <0|1>
//         Mark this pid's title region (the stacked title under the system
//         cells) as an editable address bar: clicking it enters an in-bar text
//         editor (the compositor grabs the keyboard, draws a caret), and Enter
//         sends the edited text back as ADDR. surfer's URL bar.
//     TITLETEXT <0|1>
//         Draw the stacked window title for this pid's windows at all? Default
//         1. 0 leaves the title region empty — for a program whose title is
//         only its own name, which docs/DESIGN.md 12 says the bar is not for.
//         goetia. It does NOT touch the xdg_toplevel title: the taskbar and
//         alt-tab still name the window.
//     LOADING <0|1>
//         Page loading? While 1 (and titleEdit is on), an animated | \ - /
//         spinner is drawn in a reserved slot above the address bar. surfer.
//     ICON <name>
//         Icon name (or absolute path) for the titlebar's program-icon cell,
//         overriding the class -> .desktop -> Icon= lookup — for a program
//         whose window class is not its own to resolve through (Settings:
//         every Quickshell window is `org.quickshell`). Empty clears it.
//     PLAYBAR <0|1> <pos>
//         Media scrub bar. While 1, a VERTICAL progress track is drawn in the
//         inner column below the footer (position/name) readout; <pos> is the
//         playback fraction 0..1 (fill runs top->bottom). Clicking/dragging or
//         scrolling the track sends SEEK back. 0 hides it (viewer's images).
//   server -> client:
//     CLICK <id> <x> <y>        a button was clicked (fires on release);
//                               x/y are WINDOW-LOCAL logical px
//     RCLICK <id> <x> <y>       a button was right-clicked (fires on press);
//                               x/y are WINDOW-LOCAL logical px, the point the
//                               client should pop its context menu at
//     REORDER <srcId> <dstId>   draggable button srcId dropped onto dstId's slot
//     ADDR <text>               the title editor was submitted with <text>
//     SEEK <frac>               the media scrub bar was dragged/scrolled to frac
//                               (0..1); the client seeks and echoes a new PLAYBAR
//     WAKE                      the window was just un-hidden (roll-up restore);
//                               a cue to force a repaint (QtWebEngine goes black
//                               after its surface is hidden until it redraws)
//
// A client's registration dies with its connection — closing the app (or its
// crash) drops the buttons, nothing goes stale.
//
// Threading: ALL I/O runs on a dedicated thread that never touches compositor
// state (Hyprland's event-loop helpers — doLater/doOnReadable — are not
// thread-safe, verified against the 0.55.4 source). Renders/hit-tests copy the
// registration under a mutex; `serial` bumps on every change so decorations
// can damage themselves from safe main-thread hooks (mouse move / draw).

#include <atomic>
#include <cstdint>
#include <string>
#include <sys/types.h>
#include <vector>

struct SVtbAppButton {
    std::string id;
    std::string label;
    int         state     = 0;     // 0 normal, 1 active/lit, 2 disabled
    std::string tooltip;
    bool        draggable = false; // reorderable by dragging (surfer tabs)
    bool        bottom    = false; // anchored to the bottom of the column (settings)
    bool        isSep() const {
        return id == "-";
    }
    // Decos keep a snapshot of their own registration and compare against it to
    // tell a change to THIS window from a bump by any other (see CVtbDeco::mainThreadTick).
    bool operator==(const SVtbAppButton&) const = default;
};

struct SVtbAppReg {
    std::vector<SVtbAppButton> buttons;
    std::string                footer;
    bool                       titleEdit = false; // title region is an editable address bar
    // What the address editor opens WITH, when it must differ from the drawn
    // title (surfer: the bar shows the page title, but the editor opens the
    // real URL). Empty means seed the editor from the window title as before.
    std::string                editSeed;
    // Draw the stacked title at all? Default TRUE — a client that never sends
    // TITLETEXT keeps the bar it always had, so this cannot regress the six
    // apps that say nothing about it.
    bool                       titleText = true;
    bool                       loading   = false; // page loading (spinner above the address bar)
    // Program-icon override for the titlebar's icon cell; empty means resolve
    // from the window class as always (settings — see ICON above).
    std::string                icon;
    bool                       playbar   = false; // media scrub bar shown (viewer video)
    float                      playPos   = 0.f;   // playback fraction 0..1 (fill length)
    // Where the footer sits when a scrub bar is shown. Default false keeps the
    // original order (footer under the top button group, track below it), which
    // is what viewer wants: its readout names the file the track belongs to.
    // True swaps them — track first, footer beneath it, just above the
    // bottom-anchored buttons — so the player's position readout ends up
    // against its own scrub bar rather than at the far end of the column.
    bool                       footerBottom = false;

    bool operator==(const SVtbAppReg&) const = default;
};

namespace VtbIpc {
    void start();
    void stop();

    // Copy pid's registration (returns false if none). Safe from any thread.
    bool get(pid_t pid, SVtbAppReg& out);

    // Does pid want its stacked title drawn? True for an unregistered pid.
    // Separate from get() because the render pass asks it every frame and
    // copying the button vector to read one bool is not free.
    bool titleTextEnabled(pid_t pid);

    // Send CLICK <id> <x> <y> to whoever registered pid's buttons. Non-blocking;
    // a wedged client just misses clicks, it can never stall the compositor.
    void sendClick(pid_t pid, const std::string& id, double x, double y);

    // Send RCLICK <id> <x> <y> — a button was right-clicked, with the
    // window-local point of the press. Same non-blocking guarantees.
    void sendRClick(pid_t pid, const std::string& id, double x, double y);

    // Other server -> client notifications (all non-blocking, same guarantees
    // as sendClick): a draggable button was reordered, the title editor was
    // submitted, the window was un-hidden.
    void sendReorder(pid_t pid, const std::string& srcId, const std::string& dstId);
    void sendAddr(pid_t pid, const std::string& text);
    void sendSeek(pid_t pid, float frac);
    void sendWake(pid_t pid);

    // Bumped on every registration/footer/disconnect change.
    extern std::atomic<uint64_t> serial;

    // Diagnostic snapshot of the server: the socket path, whether it is bound
    // and still NAMED on disk, live connection count, and every registration
    // (pid -> button count + flags). JSON, one line. Published to
    // $HOME/.local/state/hyprvtb/ipc-dump.json by hyprvtb.ipc_dump() — there is
    // no other way to see whether an app's REGISTER actually landed, and
    // "the inner column is empty" has more than one cause.
    std::string dumpJson();
}

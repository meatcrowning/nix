#pragma once

// App-button IPC ("the inner half of the double-wide titlebar"): a Unix socket
// at $XDG_RUNTIME_DIR/hyprvtb-buttons.sock where client apps register a column
// of program-specific buttons for their own windows, keyed by PID.
//
// Wire protocol (newline-terminated ASCII lines):
//   client -> server:
//     REGISTER <pid> <id>:<label>:<state>[:<tooltip>[:<drag>]]|...
//         Replaces the client's whole button set (re-send any time state
//         changes — labels and states are data, not fixed at startup).
//         state: 0 normal, 1 active/lit (toggles), 2 disabled (drawn dim,
//         clicks ignored). tooltip is optional hover text. drag ("1") marks the
//         button reorderable: dragging it up/down the column sends a REORDER
//         back (surfer's tabs). Fields are percent-encoded by the client
//         (%3A ':', %7C '|', %0A newline) and decoded here, so a label may be
//         any glyph incl. "|" or ":". An entry with id "-" is a separator.
//     FOOTER <text>
//         Short text drawn as stacked upright characters at the bottom of the
//         inner column (filer's dir-size readout). Empty text clears it.
//     TITLEEDIT <0|1>
//         Mark this pid's title region (the stacked title under the system
//         cells) as an editable address bar: clicking it enters an in-bar text
//         editor (the compositor grabs the keyboard, draws a caret), and Enter
//         sends the edited text back as ADDR. surfer's URL bar.
//   server -> client:
//     CLICK <id>                a button was clicked (fires on release)
//     REORDER <srcId> <dstId>   draggable button srcId dropped onto dstId's slot
//     ADDR <text>               the title editor was submitted with <text>
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
    bool        isSep() const {
        return id == "-";
    }
};

struct SVtbAppReg {
    std::vector<SVtbAppButton> buttons;
    std::string                footer;
    bool                       titleEdit = false; // title region is an editable address bar
};

namespace VtbIpc {
    void start();
    void stop();

    // Copy pid's registration (returns false if none). Safe from any thread.
    bool get(pid_t pid, SVtbAppReg& out);

    // Send CLICK <id> to whoever registered pid's buttons. Non-blocking; a
    // wedged client just misses clicks, it can never stall the compositor.
    void sendClick(pid_t pid, const std::string& id);

    // Other server -> client notifications (all non-blocking, same guarantees
    // as sendClick): a draggable button was reordered, the title editor was
    // submitted, the window was un-hidden.
    void sendReorder(pid_t pid, const std::string& srcId, const std::string& dstId);
    void sendAddr(pid_t pid, const std::string& text);
    void sendWake(pid_t pid);

    // Bumped on every registration/footer/disconnect change.
    extern std::atomic<uint64_t> serial;
}

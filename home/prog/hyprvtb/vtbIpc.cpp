#include "vtbIpc.hpp"

#include <algorithm>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <mutex>
#include <thread>
#include <vector>

#include <fcntl.h>
#include <poll.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

std::atomic<uint64_t> VtbIpc::serial{1};

namespace {
    struct SClient {
        int         fd  = -1;
        pid_t       pid = 0; // set by the first REGISTER on this connection
        std::string buf;     // partial-line accumulator
    };

    std::mutex                                     g_lk; // guards g_regs and the fd map below
    std::map<pid_t, SVtbAppReg>                    g_regs;
    std::map<pid_t, int>                           g_regFd; // pid -> owning connection fd (for CLICK)

    std::thread                                    g_thread;
    std::atomic<bool>                              g_running{false};
    int                                            g_listenFd    = -1;
    int                                            g_wakePipe[2] = {-1, -1};
    std::string                                    g_sockPath;

    // Identity of the inode WE created with bind(). stop() unlinks the path
    // only if it still names this exact socket — during a `hyprctl reload`
    // hot-swap the incoming instance runs PLUGIN_INIT (and so bind(), which
    // creates a NEW inode at the same path) BEFORE the outgoing instance runs
    // PLUGIN_EXIT, so an unconditional unlink() there deletes the *successor's*
    // name. The listener survives headless — `ss -xl` still shows it LISTENing —
    // but no client can ever connect(), so nothing registers and every window
    // comes up without its inner column. Empirically observed at 2.84.
    //
    // That guard fixed the OUTGOING half only. The incoming half — start()
    // unlinking the real path before it knows it can bind — reproduced the same
    // state at 2.90 and is fixed there by binding to a temp name and renaming
    // it into place. Read both together: the name must only ever change hands
    // atomically, in either direction.
    dev_t                                          g_sockDev = 0;
    ino_t                                          g_sockIno = 0;

    std::atomic<int>                               g_nClients{0}; // dumpJson() only

    std::string socketPath() {
        const char* rt = std::getenv("XDG_RUNTIME_DIR");
        return std::string(rt ? rt : "/tmp") + "/hyprvtb-buttons.sock";
    }

    // Reverse of vtbclient.py's _enc: decode %XX byte escapes. Only the wire
    // separators (':' '|') and newlines are ever encoded, so a "|"/":" glyph
    // label round-trips; other bytes (incl. UTF-8 glyphs) pass through.
    std::string pctDecode(const std::string& s) {
        const auto hex = [](char c) -> int {
            if (c >= '0' && c <= '9')
                return c - '0';
            if (c >= 'a' && c <= 'f')
                return c - 'a' + 10;
            if (c >= 'A' && c <= 'F')
                return c - 'A' + 10;
            return -1;
        };
        std::string out;
        out.reserve(s.size());
        for (size_t i = 0; i < s.size(); i++) {
            if (s[i] == '%' && i + 2 < s.size()) {
                const int hi = hex(s[i + 1]), lo = hex(s[i + 2]);
                if (hi >= 0 && lo >= 0) {
                    out.push_back(static_cast<char>((hi << 4) | lo));
                    i += 2;
                    continue;
                }
            }
            out.push_back(s[i]);
        }
        return out;
    }

    std::vector<std::string> split(const std::string& s, char sep) {
        std::vector<std::string> out;
        size_t                   pos = 0;
        while (true) {
            const size_t next = s.find(sep, pos);
            out.push_back(s.substr(pos, next == std::string::npos ? next : next - pos));
            if (next == std::string::npos)
                break;
            pos = next + 1;
        }
        return out;
    }

    // "REGISTER <pid> id:label:state|..." — replaces pid's whole button set.
    void handleRegister(SClient& c, const std::string& args) {
        const size_t sp = args.find(' ');
        if (sp == std::string::npos)
            return;

        pid_t pid = 0;
        try {
            pid = std::stoi(args.substr(0, sp));
        } catch (...) { return; }
        if (pid <= 0)
            return;

        SVtbAppReg reg;
        for (const auto& ent : split(args.substr(sp + 1), '|')) {
            if (ent.empty())
                continue;
            const auto  f = split(ent, ':');
            SVtbAppButton b;
            b.id    = pctDecode(f[0]);
            b.label = f.size() > 1 ? pctDecode(f[1]) : "";
            if (f.size() > 2) {
                try {
                    b.state = std::clamp(std::stoi(f[2]), 0, 2);
                } catch (...) {}
            }
            if (f.size() > 3)
                b.tooltip = pctDecode(f[3]);
            if (f.size() > 4)
                b.draggable = (f[4] == "1");
            if (f.size() > 5)
                b.bottom = (f[5] == "1");
            if (!b.id.empty())
                reg.buttons.push_back(std::move(b));
        }

        std::lock_guard lk(g_lk);
        // keep an existing footer / title-edit flag / scrub bar across button
        // re-registrations (viewer re-registers its button set on every
        // image<->video switch, and again would clobber the live PLAYBAR)
        if (auto it = g_regs.find(pid); it != g_regs.end()) {
            reg.footer       = it->second.footer;
            reg.titleEdit    = it->second.titleEdit;
            reg.titleText    = it->second.titleText;
            reg.playbar      = it->second.playbar;
            reg.playPos      = it->second.playPos;
            reg.footerBottom = it->second.footerBottom;
        }
        c.pid          = pid;
        g_regs[pid]    = std::move(reg);
        g_regFd[pid]   = c.fd;
        VtbIpc::serial.fetch_add(1, std::memory_order_relaxed);
    }

    void handleFooter(SClient& c, const std::string& text) {
        if (c.pid <= 0)
            return;
        std::lock_guard lk(g_lk);
        const auto      it = g_regs.find(c.pid);
        if (it == g_regs.end() || g_regFd[c.pid] != c.fd)
            return;
        if (it->second.footer == text)
            return;
        it->second.footer = text;
        VtbIpc::serial.fetch_add(1, std::memory_order_relaxed);
    }

    void handleFooterPos(SClient& c, const std::string& arg) {
        if (c.pid <= 0)
            return;
        std::lock_guard lk(g_lk);
        const auto      it = g_regs.find(c.pid);
        if (it == g_regs.end() || g_regFd[c.pid] != c.fd)
            return;
        const bool BOTTOM = (arg == "1");
        if (it->second.footerBottom == BOTTOM)
            return;
        it->second.footerBottom = BOTTOM;
        VtbIpc::serial.fetch_add(1, std::memory_order_relaxed);
    }

    void handleTitleEdit(SClient& c, const std::string& arg) {
        if (c.pid <= 0)
            return;
        const bool      on = (arg == "1");
        std::lock_guard lk(g_lk);
        // g_regs[c.pid] rather than a find(): the entry is normally already
        // there, since `c.pid` is only learned FROM a REGISTER and this returns
        // above without one — a verb sent before the first REGISTER is dropped,
        // which is unreachable through `pylib/vtbclient.py` (its connect path
        // sends REGISTER first and re-sends every flag after it).
        auto& reg = g_regs[c.pid];
        if (g_regFd.find(c.pid) == g_regFd.end())
            g_regFd[c.pid] = c.fd;
        if (reg.titleEdit == on)
            return;
        reg.titleEdit = on;
        VtbIpc::serial.fetch_add(1, std::memory_order_relaxed);
    }

    // TITLETEXT <0|1>: does this pid's title region carry text at all? Same
    // shape as handleTitleEdit. It is declared ONCE at startup, so the thing
    // that has to hold is handleRegister carrying it — goetia re-registers its
    // button set every time the lit section cell changes, i.e. on every scroll.
    void handleTitleText(SClient& c, const std::string& arg) {
        if (c.pid <= 0)
            return;
        const bool      on = (arg == "1");
        std::lock_guard lk(g_lk);
        auto&           reg = g_regs[c.pid];
        if (g_regFd.find(c.pid) == g_regFd.end())
            g_regFd[c.pid] = c.fd;
        if (reg.titleText == on)
            return;
        reg.titleText = on;
        VtbIpc::serial.fetch_add(1, std::memory_order_relaxed);
    }

    void handlePlaybar(SClient& c, const std::string& args) {
        if (c.pid <= 0)
            return;
        // "<0|1> <pos>": scrub bar visibility + playback fraction
        const size_t sp    = args.find(' ');
        const bool   shown = args.substr(0, sp) == "1";
        float        pos   = 0.f;
        if (sp != std::string::npos) {
            try {
                pos = std::clamp(std::stof(args.substr(sp + 1)), 0.f, 1.f);
            } catch (...) {}
        }
        std::lock_guard lk(g_lk);
        auto&           reg = g_regs[c.pid];
        if (g_regFd.find(c.pid) == g_regFd.end())
            g_regFd[c.pid] = c.fd;
        if (reg.playbar == shown && reg.playPos == pos)
            return;
        reg.playbar = shown;
        reg.playPos = pos;
        VtbIpc::serial.fetch_add(1, std::memory_order_relaxed);
    }

    void handleLoading(SClient& c, const std::string& arg) {
        if (c.pid <= 0)
            return;
        const bool      on = (arg == "1");
        std::lock_guard lk(g_lk);
        auto&           reg = g_regs[c.pid];
        if (g_regFd.find(c.pid) == g_regFd.end())
            g_regFd[c.pid] = c.fd;
        if (reg.loading == on)
            return;
        reg.loading = on;
        VtbIpc::serial.fetch_add(1, std::memory_order_relaxed);
    }

    void handleLine(SClient& c, const std::string& line) {
        if (line.starts_with("REGISTER "))
            handleRegister(c, line.substr(9));
        else if (line.starts_with("FOOTERPOS "))
            handleFooterPos(c, line.substr(10));
        else if (line.starts_with("FOOTER "))
            handleFooter(c, line.substr(7));
        else if (line == "FOOTER")
            handleFooter(c, "");
        else if (line.starts_with("TITLEEDIT "))
            handleTitleEdit(c, line.substr(10));
        else if (line.starts_with("TITLETEXT "))
            handleTitleText(c, line.substr(10));
        else if (line.starts_with("LOADING "))
            handleLoading(c, line.substr(8));
        else if (line.starts_with("PLAYBAR "))
            handlePlaybar(c, line.substr(8));
    }

    void dropClient(SClient& c) {
        {
            std::lock_guard lk(g_lk);
            // only drop the registration if this connection still owns it (a
            // reconnect may have re-registered the same pid on a newer fd)
            if (c.pid > 0) {
                const auto it = g_regFd.find(c.pid);
                if (it != g_regFd.end() && it->second == c.fd) {
                    g_regFd.erase(it);
                    g_regs.erase(c.pid);
                    VtbIpc::serial.fetch_add(1, std::memory_order_relaxed);
                }
            }
        }
        close(c.fd);
        c.fd = -1;
    }

    // Bind a fresh listen socket and rename() it onto g_sockPath, atomically.
    // Returns the new fd, or -1 with the existing name left untouched. Shared by
    // start() and the name watchdog below — the name only ever changes hands via
    // a rename, never via an unlink-then-bind.
    int bindNamed() {
        const std::string TMPPATH = g_sockPath + "." + std::to_string(getpid()) + ".tmp";
        if (TMPPATH.size() >= sizeof(sockaddr_un::sun_path))
            return -1;
        unlink(TMPPATH.c_str());

        const int FD = socket(AF_UNIX, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
        if (FD < 0)
            return -1;

        sockaddr_un addr{};
        addr.sun_family = AF_UNIX;
        std::strncpy(addr.sun_path, TMPPATH.c_str(), sizeof(addr.sun_path) - 1);
        if (bind(FD, (sockaddr*)&addr, sizeof(addr)) < 0 || listen(FD, 8) < 0
            || rename(TMPPATH.c_str(), g_sockPath.c_str()) < 0) {
            unlink(TMPPATH.c_str());
            close(FD);
            return -1;
        }
        return FD;
    }

    // THE NAME WATCHDOG. A listening socket whose filesystem name is gone is
    // invisible: every already-connected client keeps working, so the desktop
    // looks fine, while every app launched afterwards gets ENOENT from connect()
    // and comes up with no inner titlebar column. It is the failure `ipc_dump()`'s
    // "named" field was added to detect (2.86) — and nothing acted on it.
    //
    // Binding atomically (bindNamed) closes the window where WE drop the name,
    // but it cannot close every one: `hyprctl reload` can run a plugin's stop()
    // AFTER the incoming instance decided it had nothing to do, and the reload
    // path is Hyprland's, not ours. Measured: with the atomic bind alone, the
    // name still went missing across the two back-to-back swaps in
    // tools/hotswap-test.sh.
    //
    // So the invariant is enforced rather than argued: once a second, check that
    // the path still names OUR inode, and re-take it if it does not. Existing
    // client connections are untouched (they are their own fds); only the
    // listener is replaced. Cheap — one stat() per second on a thread that is
    // otherwise asleep — and it is the difference between a self-correcting
    // desktop and one the user has to report.
    void checkName() {
        if (g_listenFd < 0 || g_sockPath.empty())
            return;
        struct stat st{};
        const bool OURS = g_sockIno && stat(g_sockPath.c_str(), &st) == 0 && st.st_dev == g_sockDev && st.st_ino == g_sockIno;
        if (OURS)
            return;

        const int FD = bindNamed();
        if (FD < 0)
            return; // try again next tick; the old listener stays as it was

        close(g_listenFd);
        g_listenFd = FD;
        struct stat ns{};
        if (stat(g_sockPath.c_str(), &ns) == 0) {
            g_sockDev = ns.st_dev;
            g_sockIno = ns.st_ino;
        }
    }

    // Dedicated I/O thread: poll on the listen socket, the wake pipe, and every
    // client. Compositor state is NEVER touched from here.
    void ioLoop() {
        std::vector<SClient> clients;

        while (g_running.load(std::memory_order_relaxed)) {
            checkName(); // before fds is built — it may replace g_listenFd

            std::vector<pollfd> fds;
            fds.push_back({g_listenFd, POLLIN, 0});
            fds.push_back({g_wakePipe[0], POLLIN, 0});
            for (const auto& c : clients)
                fds.push_back({c.fd, POLLIN, 0});

            // Bounded wait, so the watchdog above runs on an idle socket too.
            if (poll(fds.data(), fds.size(), 1000) < 0) {
                if (errno == EINTR)
                    continue;
                break;
            }

            if (!g_running.load(std::memory_order_relaxed))
                break;

            // service existing clients FIRST (fds[2+i] pairs with clients[i]);
            // accepting last keeps the two arrays in sync for this iteration
            for (size_t i = 0; i < clients.size(); i++) {
                const auto& pfd = fds[2 + i];
                if (!(pfd.revents & (POLLIN | POLLHUP | POLLERR)))
                    continue;

                auto& c    = clients[i];
                char  buf[4096];
                bool  dead = false;
                while (true) {
                    const ssize_t n = read(c.fd, buf, sizeof(buf));
                    if (n > 0) {
                        c.buf.append(buf, n);
                        continue;
                    }
                    if (n == 0)
                        dead = true; // EOF
                    else if (errno != EAGAIN && errno != EWOULDBLOCK)
                        dead = true;
                    break;
                }

                size_t nl;
                while ((nl = c.buf.find('\n')) != std::string::npos) {
                    std::string line = c.buf.substr(0, nl);
                    c.buf.erase(0, nl + 1);
                    if (!line.empty() && line.back() == '\r')
                        line.pop_back();
                    if (!line.empty() && line.size() < 8192)
                        handleLine(c, line);
                }
                if (c.buf.size() > 65536) // garbage client, no newline in 64k
                    dead = true;

                if (dead)
                    dropClient(c);
            }
            std::erase_if(clients, [](const SClient& c) { return c.fd < 0; });

            if (fds[0].revents & POLLIN) {
                const int fd = accept4(g_listenFd, nullptr, nullptr, SOCK_NONBLOCK | SOCK_CLOEXEC);
                if (fd >= 0)
                    clients.push_back(SClient{fd});
            }
            g_nClients.store((int)clients.size(), std::memory_order_relaxed); // dumpJson() only
        }

        for (auto& c : clients)
            close(c.fd);
        g_nClients.store(0, std::memory_order_relaxed);
    }
}

void VtbIpc::start() {
    if (g_running.load())
        return;

    g_sockPath = socketPath();

    // BIND TO A TEMP NAME, THEN rename() IT INTO PLACE. Never unlink() the real
    // path first.
    //
    // `unlink(); bind();` looks harmless — the incumbent is going away anyway —
    // but it opens a window in which the desktop has NO named socket, and it
    // hands that window to the one code path that can fail. If bind(), listen()
    // or pipe2() below errors, this function returns having deleted a name it
    // never managed to take over: the OUTGOING instance is still alive, still
    // holding its listen fd, still serving every client that had already
    // connected — and unreachable to every client that has not. `ss -xl` shows
    // it LISTENing on a path that `ls` says does not exist, existing apps keep
    // their inner column, and every app launched from then on comes up without
    // one. Observed live at 2.90 after a rebuild's hot-swap: four registrations
    // held, four inner columns drawn, and `connect()` returning ENOENT for
    // everything new. `ipc_dump()`'s "named" field is the detector for it (2.86)
    // and this is the cause it was added to find.
    //
    // rename() over an existing path is atomic: a client either connects to the
    // old socket or the new one, never to nothing. On any failure the incumbent
    // keeps its name and the desktop keeps working — a failed swap costs the new
    // features, not the button column. stop()'s inode guard is unaffected:
    // rename preserves the inode, and g_sockDev/g_sockIno are recorded from the
    // FINAL path below.
    g_listenFd = bindNamed();
    if (g_listenFd < 0)
        return; // the incumbent, if any, keeps its name and keeps working

    if (pipe2(g_wakePipe, O_CLOEXEC | O_NONBLOCK) < 0) {
        // The name is ours now, and we are about to drop the fd that answers
        // it. Leaving it behind would be worse than the pre-rename failure
        // above: a client would connect() successfully and then get
        // ECONNREFUSED forever, with `ls` showing a socket that looks fine.
        // Take the name down with the listener.
        struct stat st{};
        if (stat(g_sockPath.c_str(), &st) == 0)
            unlink(g_sockPath.c_str());
        close(g_listenFd);
        g_listenFd = -1;
        return;
    }

    // Remember which inode is ours, so stop() cannot unlink a successor's.
    struct stat st{};
    if (stat(g_sockPath.c_str(), &st) == 0) {
        g_sockDev = st.st_dev;
        g_sockIno = st.st_ino;
    } else
        g_sockDev = g_sockIno = 0;

    g_running.store(true);
    g_thread = std::thread(ioLoop);
}

void VtbIpc::stop() {
    if (!g_running.load())
        return;

    g_running.store(false);
    (void)!write(g_wakePipe[1], "x", 1); // wake the poll
    if (g_thread.joinable())
        g_thread.join();

    close(g_listenFd);
    close(g_wakePipe[0]);
    close(g_wakePipe[1]);
    g_listenFd = g_wakePipe[0] = g_wakePipe[1] = -1;

    // Only if the path still names the inode we bound (see g_sockDev above).
    struct stat st{};
    if (g_sockIno && stat(g_sockPath.c_str(), &st) == 0 && st.st_dev == g_sockDev && st.st_ino == g_sockIno)
        unlink(g_sockPath.c_str());
    g_sockDev = g_sockIno = 0;

    std::lock_guard lk(g_lk);
    g_regs.clear();
    g_regFd.clear();
}

std::string VtbIpc::dumpJson() {
    // "named" is the failure this exists for: the listener can be alive while
    // its filesystem name is gone (a swap-time unlink), in which case no client
    // can ever connect and every inner column stays empty.
    const std::string PATH = g_sockPath.empty() ? socketPath() : g_sockPath;
    struct stat       st{};
    const bool        NAMED = stat(PATH.c_str(), &st) == 0;

    std::string out = "{\"running\":" + std::string(g_running.load() ? "true" : "false") + ",\"listenFd\":" + std::to_string(g_listenFd) + ",\"path\":\"" + PATH +
        "\",\"named\":" + (NAMED ? "true" : "false") + ",\"clients\":" + std::to_string(g_nClients.load(std::memory_order_relaxed)) +
        ",\"serial\":" + std::to_string(VtbIpc::serial.load(std::memory_order_relaxed)) + ",\"regs\":[";

    std::lock_guard lk(g_lk);
    bool            first = true;
    for (const auto& [pid, reg] : g_regs) {
        if (!first)
            out += ",";
        first = false;
        out += "{\"pid\":" + std::to_string(pid) + ",\"buttons\":" + std::to_string(reg.buttons.size()) +
            ",\"titleEdit\":" + (reg.titleEdit ? "true" : "false") + ",\"titleText\":" + (reg.titleText ? "true" : "false") +
            ",\"loading\":" + (reg.loading ? "true" : "false") +
            ",\"playbar\":" + (reg.playbar ? "true" : "false") + ",\"footer\":" + (reg.footer.empty() ? "false" : "true") + "}";
    }
    out += "]}";
    return out;
}

bool VtbIpc::get(pid_t pid, SVtbAppReg& out) {
    if (pid <= 0)
        return false;
    std::lock_guard lk(g_lk);
    const auto      it = g_regs.find(pid);
    if (it == g_regs.end())
        return false;
    out = it->second;
    return true;
}

bool VtbIpc::titleTextEnabled(pid_t pid) {
    // One flag, no copy: this is asked once per window per FRAME, and `get()`
    // would deep-copy the whole button vector to answer it. Unregistered pids
    // say true — the default is the bar every window has always had.
    if (pid <= 0)
        return true;
    std::lock_guard lk(g_lk);
    const auto      it = g_regs.find(pid);
    return it == g_regs.end() || it->second.titleText;
}

namespace {
    // Non-blocking + NOSIGNAL send of one line to whoever owns pid's buttons: a
    // dead/wedged client can't stall or kill the compositor; its actual cleanup
    // happens on the I/O thread's next poll. Call with g_lk held.
    void sendLineLocked(pid_t pid, const std::string& line) {
        const auto it = g_regFd.find(pid);
        if (it == g_regFd.end())
            return;
        const std::string msg = line + "\n";
        (void)!::send(it->second, msg.data(), msg.size(), MSG_NOSIGNAL | MSG_DONTWAIT);
    }
}

void VtbIpc::sendClick(pid_t pid, const std::string& id) {
    std::lock_guard lk(g_lk);
    sendLineLocked(pid, "CLICK " + id);
}

void VtbIpc::sendReorder(pid_t pid, const std::string& srcId, const std::string& dstId) {
    std::lock_guard lk(g_lk);
    sendLineLocked(pid, "REORDER " + srcId + " " + dstId);
}

void VtbIpc::sendAddr(pid_t pid, const std::string& text) {
    std::lock_guard lk(g_lk);
    sendLineLocked(pid, "ADDR " + text); // text is the rest of the line (no newline inserted)
}

void VtbIpc::sendSeek(pid_t pid, float frac) {
    char buf[32];
    std::snprintf(buf, sizeof(buf), "%.5f", std::clamp(frac, 0.f, 1.f));
    std::lock_guard lk(g_lk);
    sendLineLocked(pid, std::string("SEEK ") + buf);
}

void VtbIpc::sendWake(pid_t pid) {
    std::lock_guard lk(g_lk);
    sendLineLocked(pid, "WAKE");
}

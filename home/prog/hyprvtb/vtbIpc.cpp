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
            reg.footer    = it->second.footer;
            reg.titleEdit = it->second.titleEdit;
            reg.playbar   = it->second.playbar;
            reg.playPos   = it->second.playPos;
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

    void handleTitleEdit(SClient& c, const std::string& arg) {
        if (c.pid <= 0)
            return;
        const bool      on = (arg == "1");
        std::lock_guard lk(g_lk);
        // the reg may not exist yet if TITLEEDIT arrives before the first
        // REGISTER — create a bare entry so the flag isn't lost
        auto& reg = g_regs[c.pid];
        if (g_regFd.find(c.pid) == g_regFd.end())
            g_regFd[c.pid] = c.fd;
        if (reg.titleEdit == on)
            return;
        reg.titleEdit = on;
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
        else if (line.starts_with("FOOTER "))
            handleFooter(c, line.substr(7));
        else if (line == "FOOTER")
            handleFooter(c, "");
        else if (line.starts_with("TITLEEDIT "))
            handleTitleEdit(c, line.substr(10));
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

    // Dedicated I/O thread: poll on the listen socket, the wake pipe, and every
    // client. Compositor state is NEVER touched from here.
    void ioLoop() {
        std::vector<SClient> clients;

        while (g_running.load(std::memory_order_relaxed)) {
            std::vector<pollfd> fds;
            fds.push_back({g_listenFd, POLLIN, 0});
            fds.push_back({g_wakePipe[0], POLLIN, 0});
            for (const auto& c : clients)
                fds.push_back({c.fd, POLLIN, 0});

            if (poll(fds.data(), fds.size(), -1) < 0) {
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
        }

        for (auto& c : clients)
            close(c.fd);
    }
}

void VtbIpc::start() {
    if (g_running.load())
        return;

    g_sockPath = socketPath();
    unlink(g_sockPath.c_str());

    g_listenFd = socket(AF_UNIX, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
    if (g_listenFd < 0)
        return;

    sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    std::strncpy(addr.sun_path, g_sockPath.c_str(), sizeof(addr.sun_path) - 1);
    if (bind(g_listenFd, (sockaddr*)&addr, sizeof(addr)) < 0 || listen(g_listenFd, 8) < 0) {
        close(g_listenFd);
        g_listenFd = -1;
        return;
    }

    if (pipe2(g_wakePipe, O_CLOEXEC | O_NONBLOCK) < 0) {
        close(g_listenFd);
        g_listenFd = -1;
        return;
    }

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
    unlink(g_sockPath.c_str());

    std::lock_guard lk(g_lk);
    g_regs.clear();
    g_regFd.clear();
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

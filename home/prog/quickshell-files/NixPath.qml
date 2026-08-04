pragma Singleton
import Quickshell
import Quickshell.Io
import QtQuick

// The one place that knows the panel cannot see the nix profile on book.
//
// `qs -d` is exec'd by Hyprland, and on book Hyprland is started by the FEDORA
// session, so the panel process runs with
// `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin` and nothing
// else — no nix profile at all (`tr '\0' '\n' < /proc/$(pgrep -x qs)/environ`).
// Every distro tool the panel uses (sh, hyprctl, pkill, wpctl, grim, wl-copy,
// notify-send, brightnessctl, ddcutil, kitty, xdg-open, the coreutils) is
// there, so this stays invisible until the panel reaches for something only
// nix provides — and then it fails SILENTLY, because `execDetached` has no
// stdout and no exit code. That is how hyprsunset (night light AND negative
// brightness) stayed dead on book for its whole life.
//
// APPEND, never prepend: the distro binary must keep winning wherever there is
// one, so this only ever fills gaps. It is a no-op on top, where both
// directories are already on PATH — which is also why it is unconditional
// rather than branched on `host`.
//
// The idiom predates this singleton in two hand-rolled copies (the cava
// spawns), and the user had even symlinked /usr/local/sbin/cava into the nix
// profile by hand. Route new launches through here instead of writing a third.
Singleton {
    id: root

    // sh prologue. Prefix any `sh -c` body that may name a nix-only binary.
    readonly property string sh:
        "PATH=\"$PATH:$HOME/.nix-profile/bin:/run/current-system/sw/bin\"; "

    // Drop-in for Quickshell.execDetached(argv) when argv[0] may be nix-only.
    // Goes through `sh -c '<prologue> exec "$0" "$@"' argv...`, so arguments
    // stay separate words — no quoting of paths with spaces in them.
    function run(argv) {
        if (!argv || argv.length === 0) return;
        Quickshell.execDetached(["sh", "-c", root.sh + "exec \"$0\" \"$@\""]
            .concat(argv));
    }

    // `run` for anything that OUTLIVES the click — a GUI application, not a
    // `pkill`/`hyprctl` one-shot. Use it for every long-lived program the panel
    // starts; `run` stays correct for fire-and-forget commands.
    //
    // execDetached detaches the PROCESS (double-fork, reparented to systemd)
    // but NOT the CGROUP, which is inherited and cannot be left by running.
    // So an app launched from the runner stayed inside
    // `quickshell-panel.service` for its whole life, and that is two bugs:
    //
    //   * The unit is `KillMode=control-group` + `Restart=always` (systemd's
    //     defaults), so ANY panel restart SIGTERMs the whole group — his
    //     browser and every dock-launched app die with the bar.
    //   * Their memory is charged to the panel. Measured on book 2026-08-03:
    //     `quickshell-panel.service` at 1.79 GB current / 3.36 GB peak while
    //     the `qs` process itself held 176 MB and was flat. The rest was
    //     surfer + its QtWebEngine renderers. A 3.4 GB "panel leak" in the
    //     journal was the browser, filed under the bar.
    //
    // `systemd-run --user --scope` is the escape: the app lands in its own
    // `run-p<pid>-i<n>.scope` as a SIBLING under `app.slice`, verified on book.
    // `--scope` (not `--unit`) is what keeps this a one-liner — a scope runs in
    // the CALLER's context, so WAYLAND_DISPLAY and the rest are inherited and
    // need no `--setenv` list (see the `settings` wrapper in quickshell.nix,
    // which pays exactly that price for using a service instead).
    // `--collect` reaps the scope when the app exits.
    //
    // If systemd-run is somehow absent the `&&` short-circuits to a plain exec,
    // i.e. today's behaviour — a launch that still works, just uncontained.
    // Never fail to start the program the user asked for.
    function launch(argv) {
        if (!argv || argv.length === 0) return;
        Quickshell.execDetached(["sh", "-c", root.sh
            + "command -v systemd-run >/dev/null 2>&1 && "
            + "exec systemd-run --user --quiet --collect --scope -- \"$0\" \"$@\"; "
            + "exec \"$0\" \"$@\""]
            .concat(argv));
    }

    // Every nix-only binary the panel launches. Probed once at startup so a
    // missing one shows up in `qs log` instead of as a dead button: silence,
    // not breakage, is what let this rot unnoticed on book.
    readonly property var launchTargets: [
        "hyprsunset",   // SettingsApply: night light + negative brightness
        "filer",        // DiskContent: click a mount
        "wf-recorder",  // Screenshot: record mode
        "cava",         // SysInfo/Media: VU meter + spectrum
        "kdeconnect-cli" // Notifications: name the phone a toast was relayed from
    ]

    Process {
        running: true
        command: ["sh", "-c",
            root.sh + "for b in \"$@\"; do command -v \"$b\" >/dev/null || echo \"$b\"; done",
            "_"].concat(root.launchTargets)
        stdout: StdioCollector {
            onStreamFinished: {
                const missing = this.text.trim();
                if (missing)
                    console.warn("NixPath: not resolvable, features that launch "
                        + "these do nothing: " + missing.split("\n").join(", "));
            }
        }
    }
}

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

    // Every nix-only binary the panel launches. Probed once at startup so a
    // missing one shows up in `qs log` instead of as a dead button: silence,
    // not breakage, is what let this rot unnoticed on book.
    readonly property var launchTargets: [
        "hyprsunset",   // SettingsApply: night light + negative brightness
        "filer",        // DiskContent: click a mount
        "wf-recorder",  // Screenshot: record mode
        "cava"          // SysInfo/Media: VU meter + spectrum
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

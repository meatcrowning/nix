{ pkgs, lib, host, ... }:

# ai-warden — the thing that stops chatter and painter taking the machine down
# between them.
#
# `top` has 31 GiB of RAM and 12 of VRAM, and two backends that each want most
# of it: ollama behind chatter (`apps/oracle`) and ComfyUI behind painter
# (`apps/painter`). Measured 2026-08-22 with nothing unusual running, ollama
# alone held 24.7 GiB for one `qwen3.6:35b-a3b`; a painter video render on top
# of that does not fail, it LIVELOCKS the box (the mechanism is in
# `sys/oomd.nix` — reclaim keeps inching forward so the kernel OOM killer never
# fires, and the compositor stops being scheduled, which under Wayland eats the
# Ctrl+Alt+F<n> escape hatch too).
#
# `tools/heavy-gate.sh` already arbitrates a REBUILD against these two. Nothing
# arbitrated them against EACH OTHER, which is the collision he actually hits.
# This does, by admission control rather than by reacting to pressure: both apps
# ask before they load or queue, and the warden frees the other backend's
# weights (never stopping either daemon, never interrupting work in flight) or
# refuses with a reason the app can draw. The whole design, the three rules he
# set, and why the cgroup rather than `/api/ps`, are in the script's docstring.
#
# `top` only, deliberately: it is the machine the backends run on. book reaches
# ollama over the tunnel to top, where top's own warden already governs it, and
# a second warden there would arbitrate a machine it cannot measure. The
# clients fail open when nothing answers, so book needs no branch of its own.
#
# Kill switch `~/.local/state/ai-warden/off`; log `~/.cache/ai-warden.log`;
# harness `tools/ai-warden-test.py`.
let
  wardenBin = pkgs.writeShellScriptBin "ai-warden" ''
    exec ${pkgs.python3}/bin/python3 "$HOME/.config/scripts/ai-warden.py" "$@"
  '';
in
lib.mkIf (host == "top") {
  home.packages = [ wardenBin ];

  xdg.configFile."scripts/ai-warden.py" = {
    source = ./ai-warden-files/ai-warden.py;
    executable = true;
  };

  systemd.user.services.ai-warden = {
    Unit = {
      Description = "Admission control for the ollama/ComfyUI memory collision";
      After = [ "graphical-session.target" ];
      PartOf = [ "graphical-session.target" ];
    };
    Service = {
      Type = "simple";
      Restart = "always";
      RestartSec = 5;
      ExecStart = "${pkgs.python3}/bin/python3 %h/.config/scripts/ai-warden.py serve";
      # Nothing the warden does may itself be a memory event worth watching.
      MemoryMax = "128M";
      CPUWeight = 20;
      Environment = [
        "PATH=${lib.makeBinPath [
          pkgs.coreutils
          pkgs.libnotify
          pkgs.systemd
        ]}:/run/current-system/sw/bin:/etc/profiles/per-user/lam/bin"
      ];
    };
    Install.WantedBy = [ "graphical-session.target" ];
  };
}

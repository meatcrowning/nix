{
  description = "NixOS configuration";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    home-manager = {
      url = "github:nix-community/home-manager/release-25.11";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    plasma-manager = {
      url = "github:nix-community/plasma-manager";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.home-manager.follows = "home-manager";
    };

    aerothemeplasma-nix = {
      url = "github:nyakase/aerothemeplasma-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    tuxmanager = {
      url = "github:benapetr/TuxManager";
      inputs.nixpkgs.follows = "nixpkgs"; # deduplicates, keeps it on your nixpkgs
  };

    # Hyprland itself, pinned to an exact upstream tag — NOT taken from
    # nixpkgs. Two reasons, both learned the hard way (see
    # home/prog/hyprvtb/PORTING.md):
    #
    #  1. hyprvtb is a compositor plugin built against Hyprland's *internal*
    #     headers, so every compositor bump is a porting job. Off nixpkgs,
    #     that bump rode in on any unrelated `nix flake update` (Firefox,
    #     whatever) and ambushed a working session. Pinned, the compositor
    #     only ever moves when this line is edited on purpose.
    #  2. nixpkgs bumps `hyprland` and `hyprutils` on independent schedules;
    #     that's how 0.56 + hyprutils 0.14.0 landed together as two unrelated
    #     breakages in one evening. The hyprwm flakes `follows`-pin their own
    #     hyprutils/aquamarine/hyprgraphics/hyprlang, so pinning here gets the
    #     tuple upstream actually tested, as a unit.
    #
    # Deliberately NOT `inputs.nixpkgs.follows`-ed: unmodified inputs are what
    # makes hyprland.cachix.org (added in sys/base.nix) hit, and overriding
    # them would also re-introduce exactly the independent-version-skew this
    # pin exists to remove. Bump with the ritual in PORTING.md.
    hyprland.url = "github:hyprwm/Hyprland/v0.56.0";

    # THE VERSION BRIDGE for `air`/book — TEMPORARY, delete when Fedora Asahi
    # ships Hyprland 0.56 (check: `dnf list --installed hyprland` on book vs
    # the pin above). book cannot run the nix hyprland (nixpkgs Mesa has no
    # Apple-Silicon GBM; it crashes on Asahi), so its compositor is Fedora's
    # rpm — currently 0.56.2 (plugin ABI 0.56) — and a plugin only loads into the exact version
    # it was built against. This second pin exists ONLY so hyprvtb.nix can
    # build book's plugin against the compositor book actually runs, while
    # `top` stays on the pin above. vtbCompat.hpp carries the matching
    # #if VTB_HL_056 branches. Full runbook: docs/book-hyprvtb-version-bridge.md.
    # Same no-follows rationale as `hyprland` above: keep the tuple upstream
    # actually shipped (hyprutils 0.13.1 etc. — mixing generations is silent
    # ABI corruption, see the tripwire static_asserts in vtbCompat.hpp).
    hyprland-air.url = "github:hyprwm/Hyprland/v0.56.0";

    # Quickshell, frozen the same way and for the same reason as Hyprland
    # above — it is the other half of this desktop (the panel, the lock
    # screen, the power menu, the screenshot overlay, the OSDs), and the QML
    # under home/prog/quickshell-files is written against a specific
    # Quickshell API. A minor release moves that API; upstream is pre-1.0 and
    # says so. Off unstable, a Firefox update could carry 0.3 -> 0.4 in and
    # leave the session with no shell at all.
    #
    # This is a whole *nixpkgs* pinned to one revision, not the upstream
    # quickshell flake, and the difference is deliberate:
    #
    #  * upstream's flake is a source build with no binary cache, and it
    #    `follows` nothing — so with `inputs.nixpkgs.follows = "nixpkgs"` the
    #    panel would still be rebuilt from source (and silently re-linked
    #    against a new Qt) on every unstable Qt bump. Freezing the package
    #    but not its Qt only half-solves it; Qt regressions break QML too.
    #  * pinned to the exact revision the running system was built from, this
    #    evaluates to the store path already installed. Zero rebuild, zero
    #    download, provably no behaviour change on the day it lands, and the
    #    shell's entire closure — Qt included — now moves only when this line
    #    is edited.
    #
    # Cost is ~2 GiB of store held at the frozen closure once the main
    # nixpkgs' Qt moves past it. Bump deliberately (`nix flake update
    # nixpkgs-quickshell`), then relog and check the panel.
    nixpkgs-quickshell.url = "github:NixOS/nixpkgs/e2587caef70cea85dd97d7daab492899902dbf5d";

    # Anthropic ships new Claude Code builds faster than they reach nixpkgs
    # (nixos-unstable lags by days). numtide/llm-agents.nix repackages the
    # official prebuilt binary, auto-updates daily, and has a binary cache
    # (cache.numtide.com). Deliberately NOT `follows`-ed onto our nixpkgs: it
    # ships a patchelf'd prebuilt, so pinning its nixpkgs would only forfeit
    # that cache hit. Bump with `nix flake update llm-agents`.
    llm-agents.url = "github:numtide/llm-agents.nix";

    # agenix — the one secret this desktop keeps in-repo: chatter's Tavily API
    # key (sys/ai/tavily-key.nix). ~/nix is PUBLIC, so the key is committed
    # ENCRYPTED (secrets/tavily-key.age, recipients in secrets/secrets.nix) and
    # decrypted at activation by top's ssh host key. It used to be an
    # unmanaged one-line file in ~/.config/oracle that nothing owned and that
    # silently went missing, taking web search with it.
    agenix = {
      url = "github:ryantm/agenix";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.home-manager.follows = "home-manager";
    };
  };

  outputs = { nixpkgs, home-manager, plasma-manager, aerothemeplasma-nix, ... }@inputs:
  let
    user = "lam";
    system = "x86_64-linux";

    vcv-rack-overlay = (final: prev: {
      vcv-rack = prev.vcv-rack.overrideAttrs (oldAttrs: {
        patches = builtins.filter (p: !(p ? name && p.name == "fix-segfault-on-linux.patch")) (oldAttrs.patches or []);
      });
    });

    # Square off Breeze: its widget corner radius is a hardcoded compile-time
    # constant (kstyle/breezemetrics.h), with no runtime/breezerc setting — so
    # the only way to get square corners while keeping Breeze (and its
    # kdeglobals-driven, wal-following colours) is to patch that constant to 0
    # and rebuild. CheckBox_Radius is defined as Frame_FrameRadius - 1, so it's
    # pinned to 0 explicitly rather than left at -1. Merge-override (not
    # overrideScope) so only breeze itself rebuilds, not the whole Plasma stack
    # that build-depends on it — the style is loaded at runtime, so the patched
    # top-level kdePackages.breeze that lands in systemPackages is what matters.
    breeze-square-overlay = (final: prev: {
      kdePackages = prev.kdePackages // {
        breeze = prev.kdePackages.breeze.overrideAttrs (old: {
          postPatch = (old.postPatch or "") + ''
            substituteInPlace kstyle/breezemetrics.h \
              --replace-fail "Frame_FrameRadius = 5" "Frame_FrameRadius = 0" \
              --replace-fail "CheckBox_Radius = Frame_FrameRadius - 1" "CheckBox_Radius = 0"
          '';
        });
      };
    });

    # Roll up ("shade") a window from its titlebar, in the Plasma session.
    # KWin removed shading, but only its own half of the seam: KDecoration3
    # still has DecorationButtonType::Shade, and Breeze and Oxygen both still
    # build the button, draw its icon and render a shaded frame. What is gone is
    # three stubs in src/decorations/decoratedwindow.cpp (isShadeable/isShaded/
    # requestToggleShade, answering false/false/nothing) and the 'L' character in
    # the two button tables, so the button cannot be placed or listed. The patch
    # restores exactly that: roll the frame down to the decoration's top border,
    # remember the height, roll back — a rolled-up window is an ordinary resized
    # window — plus 'L' and a "Roll up window" entry in the decoration KCM's
    # draggable palette. Costs a from-source kwin build on every nixpkgs bump,
    # and a patch refresh whenever upstream touches those files. Merge-override
    # for the same reason as breeze above: the session runs the kwin_wayland
    # binary the plasma6 module puts in systemPackages, so only kwin itself has
    # to rebuild, not the Plasma stack that build-depends on it.
    kwin-rollup-overlay = (final: prev: {
      kdePackages = prev.kdePackages // {
        kwin = prev.kdePackages.kwin.overrideAttrs (old: {
          patches = (old.patches or []) ++ [ ./sys/dsk/kwin-roll-up-button.patch ];
        });
      };
    });

    # (The easyeffects per-channel IPC backport that used to live here is gone:
    # easyeffects 8.2.8 ships wwmm/easyeffects 76a3f9a5 itself, so the patch
    # applied in reverse and failed the build on the 2026-08-18 nixpkgs roll.)

    # Backport nixpkgs 7990e968cb8d (2026-07-25; our pin is 2026-07-18, so it
    # is not in the tree): setup-cuda-hook's setupCUDAToolkit_ROOT builds
    # CUDAToolkit_ROOT from the marked redist paths (cudart, libcublas, cccl)
    # but never adds nvcc's dir, so any child cmake build that inherits the env
    # var and does find_package(CUDAToolkit) fails with "CUDA Toolkit not
    # found" at ggml-cuda/CMakeLists.txt:268 — which is exactly the ollama-cuda
    # failure (llama.cpp is a cmake ExternalProject child). Upstream appends
    # the nvcc dir to CUDAToolkit_ROOT in the hook itself; mirroring it at the
    # ollama level keeps the blast radius to this one package. Drop the overlay
    # when the nixpkgs input rolls past 2026-07-25 (the hook fix arrives in the
    # same bump).
    ollama-cuda-overlay = (final: prev: {
      ollama-cuda = prev.ollama-cuda.overrideAttrs (old: {
        preBuild = ''
          local nvccExe
          if nvccExe="$(type -P nvcc)"; then
            export CUDAToolkit_ROOT="''${nvccExe%/bin/nvcc}''${CUDAToolkit_ROOT:+;$CUDAToolkit_ROOT}"
          fi
        '' + (old.preBuild or "");
      });
    });

    overlays = [ vcv-rack-overlay breeze-square-overlay ollama-cuda-overlay kwin-rollup-overlay ];

    mkPkgs = system: overlays: import nixpkgs {
      inherit system overlays;
      config.allowUnfree = true;
      # config.allowInsecure = true;
    };

    # breeze-square-overlay's patched breeze has no cache hit on any
    # platform (it's a local patch) — plasma-manager pulls kdePackages.breeze
    # in transitively regardless of home.packages, so it always compiles
    # from source. Skipped for air (for now, see home/pkgs/desktop/kde.nix)
    # by leaving the overlay out of its pkgs entirely — corners just stay
    # round there until this gets added back.

    pkgsAir = mkPkgs "aarch64-linux" [ vcv-rack-overlay ];

  in
  {
    nixosConfigurations = {
      top = nixpkgs.lib.nixosSystem {
        specialArgs = { inherit inputs user; host = "top"; };
        modules = [
          ({ pkgs, ... }: {
            nixpkgs.overlays = overlays;
            environment.systemPackages = [
              #koboldcpp-latest
              inputs.tuxmanager.packages.${system}.default
            ];
          })
          ./hosts/top/configuration.nix
          home-manager.nixosModules.home-manager
          aerothemeplasma-nix.nixosModules.aerothemeplasma-nix
          {
            home-manager = {
              extraSpecialArgs = { inherit inputs user; host = "top"; };
              useGlobalPkgs = true;
              useUserPackages = true;
              backupFileExtension = "backup";
              sharedModules = [ plasma-manager.homeModules.plasma-manager ];
              users.${user} = import ./lam.nix;
            };
          }
        ];
      };
    };

    # `top`'s home is managed solely through the NixOS module above (see
    # home-manager.nixosModules.home-manager) — having a standalone
    # homeConfigurations entry for the SAME machine was the "dual wiring" that
    # let `home-manager switch` (rbhome) changes get clobbered on boot when the
    # system re-activated its own copy of ./lam.nix. `air` below has no NixOS
    # layer to collide with, so a standalone entry for it is safe.
    homeConfigurations = {
      air = home-manager.lib.homeManagerConfiguration {
        pkgs = pkgsAir;
        extraSpecialArgs = { inherit inputs user; host = "air"; };
        modules = [
          plasma-manager.homeModules.plasma-manager
          ./lam.nix
        ];
      };
    };
  };
}

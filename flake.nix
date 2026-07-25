{
  description = "NixOS configuration";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    home-manager = {
      url = "github:nix-community/home-manager/release-25.11";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    # ollama-src = {
    #  url = "github:ollama/ollama";
    #  flake = false;
    #};
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

    # Official hyprpaper, off nixpkgs' pinned 0.8.4: that build aborts
    # (SIGABRT in hyprtoolkit's CBackend::enterLoop, mid async image decode)
    # on live wallpaper swaps, and its `unload`/`listloaded` IPC verbs return
    # "invalid hyprpaper request" outright. Pull straight from hyprwm to get a
    # version where both are fixed. Follows our nixpkgs so hypr* deps dedupe.
    hyprpaper = {
      url = "github:hyprwm/hyprpaper";
      inputs.nixpkgs.follows = "nixpkgs";
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

    #ollama-overlay = (final: prev: {
    #  ollama-latest-cuda = (prev.ollama.override {
    #    acceleration = "cuda";
    #    buildGoModule = prev.buildGo126Module;
    #  }).overrideAttrs (oldAttrs: rec {
    #    version = "git";
    #    src = inputs.ollama-src;
    #    vendorHash = "sha256-lZdGzGb9xRjTm1Rm7/wHjqM490gLznLEndmb4mNbCX0=";
    #    doCheck = false;
    #  });
    #});

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

    # re add ollama-overlay im taking it out after updating lock and not backing up lole
    overlays = [ vcv-rack-overlay breeze-square-overlay ];

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

    #also readd ollama-overlay here 
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
              # pkgs.ollama-latest-cuda
              # ollama-qwen35-9b
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

{
  description = "NixOS configuration";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    home-manager = {
      url = "github:nix-community/home-manager/release-25.11";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    ollama-src = {
      url = "github:ollama/ollama";
      flake = false;
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

    # Official hyprpaper, off nixpkgs' pinned 0.8.4: that build aborts
    # (SIGABRT in hyprtoolkit's CBackend::enterLoop, mid async image decode)
    # on live wallpaper swaps, and its `unload`/`listloaded` IPC verbs return
    # "invalid hyprpaper request" outright. Pull straight from hyprwm to get a
    # version where both are fixed. Follows our nixpkgs so hypr* deps dedupe.
    hyprpaper = {
      url = "github:hyprwm/hyprpaper";
      inputs.nixpkgs.follows = "nixpkgs";
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

    ollama-overlay = (final: prev: {
      ollama-latest-cuda = (prev.ollama.override {
        acceleration = "cuda";
        buildGoModule = prev.buildGo126Module;
      }).overrideAttrs (oldAttrs: rec {
        version = "git";
        src = inputs.ollama-src;
        vendorHash = "sha256-lZdGzGb9xRjTm1Rm7/wHjqM490gLznLEndmb4mNbCX0=";
        doCheck = false;
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

    overlays = [ vcv-rack-overlay ollama-overlay breeze-square-overlay ];

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
    pkgsAir = mkPkgs "aarch64-linux" [ vcv-rack-overlay ollama-overlay ];

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
              pkgs.ollama-latest-cuda
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

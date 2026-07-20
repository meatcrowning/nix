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

    pkgs = import nixpkgs {
      inherit system;
      config.allowUnfree = true;
      overlays = [ vcv-rack-overlay ollama-overlay breeze-square-overlay ];
      # config.allowInsecure = true;
    };

  in
  {
    nixosConfigurations = {
      top = nixpkgs.lib.nixosSystem {
        specialArgs = { inherit inputs user; };
        modules = [
          ({ pkgs, ... }: {
            nixpkgs.overlays = [ vcv-rack-overlay ollama-overlay breeze-square-overlay ];
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
              extraSpecialArgs = { inherit inputs user; };
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

    # NOTE: there is deliberately NO standalone `homeConfigurations` output.
    # Home is managed solely through the NixOS module above (see
    # home-manager.nixosModules.home-manager). Having both was the "dual wiring"
    # that let `home-manager switch` (rbhome) changes get clobbered on boot when
    # the system re-activated its own copy of ./lam.nix. One source of truth now:
    # everything goes through `nixos-rebuild switch` (rbsys/rbhome/update), which
    # is passwordless via sys/nixos-rebuild.nix.
  };
}

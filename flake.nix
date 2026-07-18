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

  outputs = { nixpkgs, home-manager, plasma-manager, aerothemeplasma-nix, ollama-src, ... }@inputs:
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

    pkgs = import nixpkgs {
      inherit system;
      config.allowUnfree = true;
      overlays = [ vcv-rack-overlay ollama-overlay ];
      # config.allowInsecure = true;
    };

  in
  {
    nixosConfigurations = {
      top = nixpkgs.lib.nixosSystem {
        specialArgs = { inherit inputs user; };
        modules = [
          ({ pkgs, ... }: {
            nixpkgs.overlays = [ vcv-rack-overlay ollama-overlay ];
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

    homeConfigurations = {
      "${user}" = home-manager.lib.homeManagerConfiguration {
        inherit pkgs;
        extraSpecialArgs = { inherit inputs user; };
        modules = [
          ./lam.nix
          plasma-manager.homeModules.plasma-manager
        ];
      };
    };
  };
}

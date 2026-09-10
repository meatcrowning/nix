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
      inputs.nixpkgs.follows = "nixpkgs";
    };

    # Exact pin: hyprvtb uses internal headers. Keep upstream's dependency
    # tuple and bump via home/prog/hyprvtb/PORTING.md.
    hyprland.url = "github:hyprwm/Hyprland/v0.56.0";

    # Temporary book ABI bridge for Fedora Asahi's Hyprland; keep upstream's
    # dependency tuple. See docs/book-hyprvtb-version-bridge.md.
    hyprland-air.url = "github:hyprwm/Hyprland/v0.56.2";

    # Freeze Quickshell with its Qt closure; bump deliberately, then relog and
    # check the panel. See docs/flake-lock-update.md.
    nixpkgs-quickshell.url = "github:NixOS/nixpkgs/e2587caef70cea85dd97d7daab492899902dbf5d";

    # Keep its own nixpkgs input for the prebuilt binary cache.
    llm-agents.url = "github:numtide/llm-agents.nix";

    # Decrypts the in-repo Tavily secret with top's SSH host key.
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
    vcv-rack-overlay = import ./overlays/vcv-rack.nix;

    breeze-square-overlay = import ./overlays/breeze-square.nix;

    kwin-rollup-overlay = import ./overlays/kwin-rollup.nix;

    konsole-style-background-overlay = import ./overlays/konsole-style-background.nix;

    ollama-cuda-overlay = import ./overlays/ollama-cuda.nix;

    overlays = [ vcv-rack-overlay breeze-square-overlay ollama-cuda-overlay kwin-rollup-overlay konsole-style-background-overlay ];

    mkPkgs = system: overlays: import nixpkgs {
      inherit system overlays;
      config.allowUnfree = true;
    };

    # book skips the uncached Breeze patch but keeps the Konsole renderer patch.
    pkgsAirBase = mkPkgs "aarch64-linux" [ vcv-rack-overlay konsole-style-background-overlay ];
    airOffload = import ./lib/air-offload.nix {
      inherit inputs;
      arm = pkgsAirBase;
      native = mkPkgs "x86_64-linux" [];
    };
    pkgsAir = pkgsAirBase.extend (final: prev: {
      kdePackages = prev.kdePackages // {
        inherit (airOffload) konsole oxygen;
      };
    });

  in
  {
    packages.x86_64-linux = {
      air-hyprvtb = airOffload.hyprvtb;
      air-konsole = airOffload.konsole;
      air-oxygen = airOffload.oxygen;
    };
    nixosConfigurations = {
      top = nixpkgs.lib.nixosSystem {
        specialArgs = {
          inherit inputs user;
          host = "top";
          hostProfile = import ./lib/host-profile.nix { host = "top"; };
        };
        modules = [
          ({ pkgs, ... }: {
            nixpkgs.overlays = overlays;
            environment.systemPackages = [
              inputs.tuxmanager.packages.${system}.default
            ];
          })
          ./hosts/top/configuration.nix
          home-manager.nixosModules.home-manager
          aerothemeplasma-nix.nixosModules.aerothemeplasma-nix
          {
            home-manager = {
              extraSpecialArgs = {
                inherit inputs user;
                host = "top";
                hostProfile = import ./lib/host-profile.nix { host = "top"; };
              };
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

    # top uses the NixOS module above; only book has a standalone home config.
    homeConfigurations = {
      air = home-manager.lib.homeManagerConfiguration {
        pkgs = pkgsAir;
        extraSpecialArgs = {
          inherit inputs user;
          inherit airOffload;
          host = "air";
          hostProfile = import ./lib/host-profile.nix { host = "air"; };
        };
        modules = [
          plasma-manager.homeModules.plasma-manager
          ./lam.nix
        ];
      };
    };
  };
}

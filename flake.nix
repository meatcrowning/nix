{
  description = "NixOS configuration";

  inputs = {
    # Personal settings are supplied locally by the rebuild wrappers.
    private-config = {
      url = "path:./lib/private-defaults";
      flake = false;
    };

    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    # Packages held back while nixpkgs rolls: ollama, firefox, and pad's
    # nixpkgs Hyprland. Same revision they were built from, so no rebuild.
    # See overlays/hold.nix.
    nixpkgs-hold.url = "github:NixOS/nixpkgs/7fd4004d0511991fff3a0524856a9be09e28c5f0";

    # master tracks nixos-unstable; release branches stop matching it.
    home-manager = {
      url = "github:nix-community/home-manager";
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

    # book's kernel, m1n1 and U-Boot as NixOS. No upstream cache: top
    # cross-builds them (hosts/air/configuration.nix).
    apple-silicon = {
      # Exact pin; move together with nixpkgs.
      url = "github:nix-community/nixos-apple-silicon/193fc37ecc8793da8b6bb5dd6d16a1746c9c44ac";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    # Saves, the social-media gallery (home/prog/saves.nix). A private repo:
    # the first fetch on each host needs the user's GitHub SSH key.
    saves = {
      url = "git+ssh://git@github.com/meatcrowning/saves";
      flake = false;
    };

    # Decrypts the in-repo Tavily secret with top's SSH host key.
    agenix = {
      url = "github:ryantm/agenix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { nixpkgs, home-manager, plasma-manager, aerothemeplasma-nix, ... }@inputs:
  let
    user = "lam";
    privateConfig = import inputs.private-config;
    system = "x86_64-linux";
    vcv-rack-overlay = import ./overlays/vcv-rack.nix;

    breeze-square-overlay = import ./overlays/breeze-square.nix;

    kwin-rollup-overlay = import ./overlays/kwin-rollup.nix;

    konsole-style-background-overlay = import ./overlays/konsole-style-background.nix;

    hold-overlay = import ./overlays/hold.nix { inherit inputs; };

    oxygen-icons-overlay = import ./overlays/oxygen-icons-names.nix;

    overlays = [ vcv-rack-overlay breeze-square-overlay hold-overlay kwin-rollup-overlay konsole-style-background-overlay oxygen-icons-overlay ];

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
    airOffloadOverlay = final: prev: {
      kdePackages = prev.kdePackages // {
        inherit (airOffload) konsole oxygen;
      };
    };

    airArgs = {
      inherit inputs user privateConfig airOffload;
      host = "air";
      hostProfile = import ./lib/host-profile.nix { host = "air"; };
    };

  in
  {
    # Termux:X11 uses the last Plasma series with an X11 session.
    packages.aarch64-linux.phone-desktop = import ./hosts/phone/desktop.nix {
      pkgs = import inputs.nixpkgs-hold { system = "aarch64-linux"; };
    };

    packages.x86_64-linux = {
      air-hyprvtb = airOffload.hyprvtb;
      air-konsole = airOffload.konsole;
      air-oxygen = airOffload.oxygen;
      air-libplasma = airOffload.libplasma;
      air-plasma-desktop = airOffload.plasma-desktop;
    };
    nixosConfigurations = {
      # Deliberately standalone: sys/ and home/ import top's complete desktop.
      pad = nixpkgs.lib.nixosSystem {
        specialArgs = { inherit user; };
        modules = [
          { nixpkgs.overlays = [ hold-overlay ]; }
          ./hosts/pad/configuration.nix
        ];
      };
      air = nixpkgs.lib.nixosSystem {
        specialArgs = airArgs;
        modules = [
          {
            nixpkgs.hostPlatform = "aarch64-linux";
            nixpkgs.overlays = [ vcv-rack-overlay konsole-style-background-overlay hold-overlay oxygen-icons-overlay airOffloadOverlay ];
          }
          ./hosts/air/configuration.nix
          home-manager.nixosModules.home-manager
          {
            home-manager = {
              extraSpecialArgs = airArgs;
              useGlobalPkgs = true;
              useUserPackages = true;
              backupFileExtension = "backup";
              sharedModules = [ plasma-manager.homeModules.plasma-manager ];
              users.${user} = import ./lam.nix;
            };
          }
        ];
      };
      top = nixpkgs.lib.nixosSystem {
        specialArgs = {
          inherit inputs user privateConfig;
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
                inherit inputs user privateConfig;
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
  };
}

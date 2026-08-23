{ pkgs, inputs, user, ... }:

# chatter's Tavily API key, as managed state instead of a loose file.
#
# `apps/oracle` reads its web-search key from $TAVILY_API_KEY, else from
# ~/.config/oracle/tavily.key. That file was hand-written once (2026-08-09),
# owned by nothing, backed up by nothing — and by 2026-08-22 it was simply
# gone, so every search reported "no Tavily API key configured". Nothing had
# changed in the app; the state under it had evaporated.
#
# ~/nix is PUBLIC, so the key cannot be committed in the clear. agenix is the
# seam: `secrets/tavily-key.age` is committed ENCRYPTED to the recipients in
# `secrets/secrets.nix`, and `top` decrypts it at activation with its ssh HOST
# key into /run/agenix/tavily-key. home/prog/oracle.nix points
# ~/.config/oracle/tavily.key at that path, so the app is unchanged and needs
# no env var.
#
# NixOS-only, so `book` does not get it (see secrets/secrets.nix): it is
# home-manager over Fedora and is not yet a recipient. chatter there keeps
# reading its own hand-written ~/.config/oracle/tavily.key.
#
# Rotate the key:  cd ~/nix && agenix -e secrets/tavily-key.age
{
  imports = [ inputs.agenix.nixosModules.default ];

  # Explicit rather than inherited from services.openssh.hostKeys: the
  # decryption identity is the one thing here that must not change silently.
  age.identityPaths = [ "/etc/ssh/ssh_host_ed25519_key" ];

  age.secrets.tavily-key = {
    file = ../../secrets/tavily-key.age;
    owner = user;
    group = "users";
    mode = "0400";
  };

  # `agenix -e` / `-r`, for editing and re-keying the file above.
  environment.systemPackages = [ inputs.agenix.packages.${pkgs.system}.default ];
}

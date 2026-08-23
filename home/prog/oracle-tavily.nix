{ config, lib, host, ... }:

# chatter's Tavily key, on the user side: ~/.config/oracle/tavily.key as a
# symlink onto the agenix secret that sys/ai/tavily-key.nix decrypts.
#
# Why it is not in oracle.nix: that file's `home.file` is written as
# individual `home.file."…"` attributes, which cannot be merged with a
# conditional attrset in the same literal. Its own file also keeps the app
# packaging free of the secret entirely.
#
# Out-of-store on purpose (mkOutOfStoreSymlink): /nix/store is world-readable,
# so the plaintext key must never be copied into it — only pointed at.
#
# top only. `book` is Fedora + home-manager, has no NixOS activation to
# decrypt anything, and is not yet an agenix recipient (secrets/secrets.nix),
# so chatter there keeps reading its own hand-written file — which this must
# not claim out from under it.
lib.optionalAttrs (host != "air") {
  home.file.".config/oracle/tavily.key".source =
    config.lib.file.mkOutOfStoreSymlink "/run/agenix/tavily-key";
}

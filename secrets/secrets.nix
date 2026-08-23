# agenix recipients. `agenix -e <file>` reads this to know who a secret is
# encrypted TO; it is never imported by the NixOS evaluation.
#
# ~/nix is a PUBLIC repo — the .age files beside this one are safe to commit,
# the plaintext never is.
#
# `top` decrypts at activation with its ssh HOST key (age.identityPaths
# default); `lam` is here so the key can be re-edited from this account
# without root.
#
# BOOK IS NOT A RECIPIENT YET. It is Fedora + home-manager only, so it needs
# agenix's home-manager module and its own key added here, then a re-encrypt
# (`agenix -r`). Until then chatter on book keeps reading the hand-written
# ~/.config/oracle/tavily.key.
let
  lam = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFhZ7Jh/KClSqL3lU2KXHhtTcfDR74FAa7SoEC5rpUYZ";
  top = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHMUAkUeo64TjDSKp2t13ovJnoJceDo3m+J9xlOunPgo";
in
{
  "tavily-key.age".publicKeys = [ lam top ];
}

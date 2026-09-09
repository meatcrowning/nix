{ ... }:
{
  # book sends x86 build jobs that produce ARM binaries. No emulation.
  # This dedicated key can only speak the Nix store protocol, never a shell.
  nix.sshServe = {
    enable = true;
    protocol = "ssh";
    write = true;
    trusted = true;
    keys = [ "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHjIhMjqF0Kv6UWEj5W5oG0+gZ2NnKBbSFFdWV0IwdeY book-nix-builder" ];
  };
}

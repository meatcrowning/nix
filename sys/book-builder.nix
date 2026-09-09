{ ... }:
{
  # book sends x86 build jobs that produce ARM binaries. No emulation.
  # This dedicated key can only speak the Nix store protocol, never a shell.
  nix.sshServe = {
    enable = true;
    protocol = "ssh";
    write = true;
    trusted = true;
    keys = [ "REDACTED_PUBLIC_KEY" ];
  };
}

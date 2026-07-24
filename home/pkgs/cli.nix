{ pkgs, ... }:

# Net-new CLI tools that were only on Fedora (dnf) before — pure terminal
# utilities, no GPU, so nix owns them on both hosts with no Asahi/Mesa concern.
# Left off deliberately for now (easy adds later if wanted): the heavy LLVM/
# clang toolchain, and niche serial tools (minicom, lrzsz).
{
  home.packages = with pkgs; [
    # network diagnostics
    mtr           # my traceroute
    nmap          # also provides `ncat` (was dnf nmap-ncat)
    tcpdump
    traceroute
    whois
    dnsutils      # dig / nslookup (was dnf bind-utils)

    # general
    bc
    dos2unix
    lsof
    file
    ncdu
  ];
}

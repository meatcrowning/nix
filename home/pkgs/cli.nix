{ pkgs, ... }:

# pkgs on asahi that can be swapped with nix  

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

{ pkgs, ... }:

# pkgs on asahi that can be swapped with nix  

{
  home.packages = with pkgs; [
    # network diagnostics
    mtr           # my traceroute
    nmap          # also provides `ncat`
    tcpdump
    traceroute
    whois
    dnsutils      # dig / nslookup

    # general
    jq            # wal-prepare and the board tools parse JSON with it
    bc
    dos2unix
    lsof
    file
    ncdu
  ];
}

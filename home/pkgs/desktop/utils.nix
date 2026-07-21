{ pkgs, lib, host, ... }:

{
  home.packages = with pkgs; [
    qdirstat
    terminator
    ] ++ lib.optionals pkgs.stdenv.hostPlatform.isx86_64 [
    wineWow64Packages.staging
    # gimp/libreoffice aren't unavailable on aarch64, just among the
    # heaviest builds in the repo if the cache doesn't have this exact
    # variant — skip them on air's first bring-up, add back if wanted.
    ] ++ lib.optionals (host == "top") [
    gimp
    libreoffice-qt-fresh
    ];
}

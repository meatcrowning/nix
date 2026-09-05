{ pkgs, lib, ... }:

let
  dolphinCollage = pkgs.writeShellScriptBin "dolphin-collage" ''
    export PATH=${lib.makeBinPath [ pkgs.ffmpeg ]}:$PATH
    exec ${pkgs.python3}/bin/python3 \
      /home/lam/nix/apps/pylib/tools/konsole-collage.py "$@"
  '';
in
{
  home.packages = [ dolphinCollage ];

  # KIO passes every selected image as a separate argv item. Dolphin's
  # selection is one directory, so the helper writes collage.jpg there.
  home.file.".local/share/kio/servicemenus/dolphin-collage.desktop".text = ''
    [Desktop Entry]
    Type=Service
    MimeType=image/*;
    X-KDE-ServiceTypes=KonqPopupMenu/Plugin
    X-KDE-Priority=TopLevel
    Actions=makeCollage;

    [Desktop Action makeCollage]
    Name=make collage
    Icon=view-grid
    Exec=${dolphinCollage}/bin/dolphin-collage %F
  '';
}

{ config, ... }:

# Codex's official six-lobed terminal mark, redrawn with Oxygen's cobalt glass,
# silver rim, upper-left highlight and dark keyline.  It stays a full-colour
# application icon rather than joining appSeals: those monochrome sigils are
# palette-tinted by the panel and hyprvtb, which would erase this icon's Oxygen
# materials.  hicolor is every icon theme's final fallback, so `Icon=codex`
# resolves under oxygen-live on both hosts without duplicating the bitmap into
# every generated accent theme.
{
  home.file.".local/share/icons/hicolor/16x16/apps/codex.png".source = ./app-icons/codex/16.png;
  home.file.".local/share/icons/hicolor/22x22/apps/codex.png".source = ./app-icons/codex/22.png;
  home.file.".local/share/icons/hicolor/32x32/apps/codex.png".source = ./app-icons/codex/32.png;
  home.file.".local/share/icons/hicolor/48x48/apps/codex.png".source = ./app-icons/codex/48.png;
  home.file.".local/share/icons/hicolor/64x64/apps/codex.png".source = ./app-icons/codex/64.png;
  home.file.".local/share/icons/hicolor/128x128/apps/codex.png".source = ./app-icons/codex/128.png;
  home.file.".local/share/icons/hicolor/256x256/apps/codex.png".source = ./app-icons/codex/256.png;
  home.file.".local/share/icons/hicolor/512x512/apps/codex.png".source = ./app-icons/codex/512.png;

  home.file.".local/share/applications/codex.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=codex
    GenericName=codex
    Comment=start codex in the nix checkout
    Exec=${config.home.profileDirectory}/bin/konsole --workdir /home/lam/nix -e codex
    Icon=codex
    Terminal=false
    Categories=Development;Utility;
    Keywords=codex;openai;agent;nix;
  '';
}

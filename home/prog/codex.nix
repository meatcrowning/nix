{ ... }:

# `utilities-terminal` is Oxygen's own terminal icon. Keeping the desktop entry
# on that icon-theme name lets the launcher follow the active Oxygen palette on
# both hosts instead of freezing a one-off bitmap or SVG beside the entry.
{
  home.file.".local/share/applications/codex.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=codex
    GenericName=codex
    Comment=start codex in the nix checkout
    Exec=konsole --workdir /home/lam/nix -e codex
    Icon=utilities-terminal
    Terminal=false
    Categories=Development;Utility;
    Keywords=codex;openai;agent;nix;
  '';
}

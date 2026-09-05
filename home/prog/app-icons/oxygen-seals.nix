{ pkgs, lib, config, ... }:

# The Oxygen face of every bespoke program seal.
#
# The seals in `seals.nix` are currentColor sigils installed into **hicolor**,
# which is the icon spec's last-resort theme: nothing can override a name only
# hicolor defines, so picking Oxygen in System Settings left every one of our
# apps still wearing its sigil while the rest of the desktop went glassy.
#
# An icon theme's directories are merged across every XDG data dir, not taken
# from one — measured on `top` 2026-09-05: a file dropped at
# `~/.local/share/icons/oxygen/base/64x64/apps/<name>.png` resolves through
# `QIcon.fromTheme` under theme `oxygen` even though the theme's own
# `index.theme` lives in the profile. So this installs Oxygen's own artwork a
# SECOND time under our seal names, in Oxygen's own layout. `Icon=filer` then
# means Oxygen's file-manager icon while that theme is selected and falls back
# to the sigil the moment it is not, with no app code and no desktop-entry
# rewrite.
#
# hyprvtb is deliberately untouched: its `iconFileForName` searches two
# directory levels under a theme root, and Oxygen's tree is three
# (`base/<size>/<category>`), so the Hyprland titlebar keeps drawing the sigil
# it can tint whatever `kdeglobals [Icons] Theme=` says.
#
# PNG only, 16–256px — Oxygen ships no scalable `base/` art (its 720 SVGs are
# all in `applets/`, the symbolic panel set).

let
  # seal name -> the Oxygen icon it wears, as `<category>/<name>` under
  # oxygen's `base/<size>/`. One entry per seal; the assertion below is what
  # stops a new app from quietly missing out.
  #
  # Prefer Oxygen's OWN vocabulary — a `categories/`, `devices/` or `status/`
  # icon — over another program's logo. `apps/krita` and `apps/juk` are Krita's
  # and JuK's brands, and painter and player are neither. An `apps/` entry here
  # is only for a name that is generic in spirit (`system-file-manager`,
  # `internet-web-browser`) or where Oxygen ships no honest generic at all —
  # which is the case for a chat window, a Soulseek client, a decision board
  # and a markdown reader, so those four keep a borrowed logo on purpose.
  sealIcons = {
    filer = "apps/system-file-manager";
    viewer = "apps/gwenview";
    player = "categories/applications-multimedia";
    painter = "categories/applications-graphics";
    surfer = "apps/internet-web-browser";
    reader = "apps/okular";
    bespoke-editor = "apps/accessories-text-editor";
    oracle = "apps/konversation";
    slsk = "apps/ktorrent";
    goetia = "apps/knotes";
    vista-askpass = "status/dialog-password";
    updater = "apps/system-software-update";
    settings = "categories/preferences-desktop";
    quickshell = "apps/plasma";
    # not an app seal — the repo-updates toast's icon (home/srvs/repo-updates.nix)
    repo-updates = "apps/system-software-update";
  };

  sizes = [ "16x16" "22x22" "32x32" "48x48" "64x64" "128x128" "256x256" ];

  tree = pkgs.runCommand "oxygen-app-seals" { } ''
    src=${pkgs.kdePackages.oxygen-icons}/share/icons/oxygen/base
    ${lib.concatStringsSep "\n" (lib.mapAttrsToList (seal: from: ''
      for s in ${lib.concatStringsSep " " sizes}; do
        f="$src/$s/${from}.png"
        [ -f "$f" ] || continue
        mkdir -p "$out/base/$s/apps"
        ln -s "$f" "$out/base/$s/apps/${seal}.png"
      done
    '') sealIcons)}
    # An Oxygen release that renamed everything we point at would otherwise
    # deploy an empty directory and look like a theme that simply does nothing.
    [ -d "$out" ] || { echo "no Oxygen icon in sealIcons resolved"; exit 1; }
  '';

  missing = lib.subtractLists (lib.attrNames sealIcons) config.my.appSeals;
in
{
  assertions = [{
    assertion = missing == [ ];
    message = "app seals with no Oxygen counterpart in oxygen-seals.nix: "
      + lib.concatStringsSep ", " missing;
  }];

  home.file.".local/share/icons/oxygen".source = tree;
}

# oxygen-icons 6.32 ships stray "go-first copy.svg" files under
# simbolicActions/; the space makes gtk-update-icon-cache reject the theme,
# which fails the whole user profile build. Delete any such names; once
# upstream drops them this is a no-op and can go. Merge-override so only the
# icon package rebuilds.
final: prev: {
  kdePackages = prev.kdePackages // {
    oxygen-icons = prev.kdePackages.oxygen-icons.overrideAttrs (old: {
      postInstall = (old.postInstall or "") + ''
        find "$out/share/icons" -name '* *' -print -delete
      '';
    });
  };
}

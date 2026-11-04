{ config, pkgs, lib, host, ... }:

let
  # Vivaldi's proprietary H.264/AAC codecs (`vivaldi-ffmpeg-codecs`) and the
  # Widevine CDM (`enableWidevine`) are prebuilt x86_64-only blobs — the codec
  # pkg's src is a hardcoded x86_64 snapcraft snap, and Google ships no desktop
  # aarch64 Widevine — so both fail to build on `air` (Asahi/aarch64) even
  # though their meta.platforms wrongly claims aarch64. Ship them only on
  # x86_64.
  isx86 = pkgs.stdenv.hostPlatform.isx86_64;
in
{
  # Existing Plasma pins and host-local browser choices keep the Flatpak ID.
  # Redirect that ID without exposing a second browser in the application menu.
  xdg.desktopEntries."com.vivaldi.Vivaldi" = lib.mkIf (host == "air") {
    name = "Vivaldi";
    exec = "${config.home.profileDirectory}/bin/vivaldi %U";
    icon = "vivaldi";
    noDisplay = true;
    terminal = false;
    type = "Application";
  };

  home.packages = with pkgs; [
	lynx
  ] ++ lib.optionals isx86 [
        vivaldi-ffmpeg-codecs
        google-chrome
  # firefox/qutebrowser are GUI browsers with GPU-accelerated rendering
  # (QtWebEngine / gfx): nixpkgs' Mesa lacks Asahi (Honeykrisp) support, so
  # keep them on Fedora's native, hardware-accelerated build on `air`.
  ] ++ lib.optionals (host != "air") [
        qutebrowser
        firefox
  ] ++ [
        ((vivaldi.override {
          proprietaryCodecs = isx86;
          enableWidevine = isx86;
          # Pin the password store instead of letting Chromium guess it.
          #
          # Chromium keeps the key it encrypts cookies and saved passwords
          # with in the desktop keyring, and picks WHICH keyring slot from
          # $XDG_CURRENT_DESKTOP: a KDE session -> kwallet, folder
          # `Chrome Keys`, entry `Chrome Safe Storage`; an unknown desktop
          # (Hyprland is one) -> libsecret, or the hardcoded `peanuts` key if
          # nothing answers. A slot it finds EMPTY gets a fresh random key
          # written into it, and every blob written under the old one is then
          # undecryptable and deleted on the next start
          # (`clearing_undecryptable_passwords`).
          #
          # That is not hypothetical: on 2026-08-31 a Hyprland launch minted a
          # brand-new key at `Secret Service/Chrome Safe Storage` while 490 of
          # 685 cookies and 27 of 31 logins were still `v11` under the January
          # kwallet key. Verified by test-decryption
          # (`apps/pylib/tools/chromium-key-recover.py`): the real key is the
          # kwallet one, so name that backend and the session stops mattering.
          commandLineArgs = "--password-store=kwallet6"
            + lib.optionalString (host == "air") " --use-gl=angle --use-angle=vulkan";
        }).overrideAttrs (old: {
          # Fedora has no /run/opengl-driver. Use Nix's tested Honeykrisp ICD
          # explicitly so ANGLE does not fall back to software rendering.
          postFixup = (old.postFixup or "") + lib.optionalString (host == "air") ''
            wrapProgram "$out/bin/vivaldi" \
              --set VK_DRIVER_FILES "${pkgs.mesa}/share/vulkan/icd.d/asahi_icd.aarch64.json"
          '';
          postInstall = (old.postInstall or "") + ''
            ui="$out/opt/vivaldi/resources/vivaldi"
            cp ${../../../apps/pylib/vivaldi-sidebar.js} "$ui/desktop-sidebar.js"
            cp ${../../../apps/pylib/vivaldi-global-menu.js} "$ui/desktop-global-menu.js"
            substituteInPlace "$ui/main.html" --replace-fail '<script src="bundle.js"></script>' \
              '<script src="desktop-global-menu.js"></script><script src="bundle.js"></script>'
            # Fail the package build if an upstream update changes this seam.
            substituteInPlace "$ui/bundle.js" --replace-fail \
              'getBrowserClasses=(e,t)=>{' \
              'getBrowserClasses=(e,t)=>{globalThis.desktopVivaldiMenu?.(this.context,this._onMacMenuAction,Te.Z,Ze.Z,t);'

            substituteInPlace "$ui/window.html" --replace-fail '</body>' \
              '<script src="desktop-sidebar.js"></script></body>'
            # The upstream bookmark component sums horizontal widths. In our
            # vertical layout every item must remain mounted in the scroller.
            substituteInPlace "$ui/bundle.js" --replace-fail \
              'maxWidth:Math.floor(t.clientWidth)' \
              'maxWidth:t.closest(".bookmark-bar")&&t.ownerDocument.documentElement.classList.contains("desktop-sidebar-splitter")?1e9:Math.floor(t.clientWidth)'
          '';
        }))
  ];
}

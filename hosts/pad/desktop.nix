{ pkgs, ... }:
{
  programs.hyprland = { enable = true; withUWSM = true; };
  programs.thunar.enable = true;
  security.pam.services.swaylock = {};
  security.polkit.enable = true;
  services.greetd = {
    enable = true;
    settings.default_session = {
      user = "greeter";
      command = "${pkgs.tuigreet}/bin/tuigreet --time --cmd 'uwsm start -- Hyprland --config /etc/pad/hyprland.lua'";
    };
  };
  environment.sessionVariables.NIXOS_OZONE_WL = "1";
  environment.systemPackages = with pkgs; [
    vivaldi foot mousepad fuzzel mako waybar swayidle swaylock
    brightnessctl wireplumber pavucontrol networkmanagerapplet
    wl-clipboard grim slurp mpv lxqt.lxqt-policykit
  ];
  fonts.packages = with pkgs; [ dejavu_fonts noto-fonts-color-emoji ];
  environment.etc."pad/hyprland.lua".source = ./hyprland.lua;
  environment.etc."xdg/waybar/config".text = builtins.toJSON {
    layer = "top";
    height = 24;
    modules-left = [ "custom/launcher" ];
    modules-right = [ "network" "pulseaudio" "battery" "clock" ];
    "custom/launcher" = { format = "Apps"; on-click = "fuzzel"; };
    network = { format-wifi = "Wi-Fi {signalStrength}%"; format-ethernet = "Ethernet"; format-disconnected = "Offline"; on-click = "foot nmtui"; };
    pulseaudio = { format = "Vol {volume}%"; format-muted = "Muted"; on-click = "pavucontrol"; };
    battery = { format = "Bat {capacity}%"; format-charging = "Charging {capacity}%"; states = { warning = 20; critical = 10; }; };
    clock = { format = "{:%a %H:%M}"; tooltip-format = "{:%Y-%m-%d}"; };
  };
  environment.etc."xdg/waybar/style.css".text = ''
    * { font-family: DejaVu Sans; font-size: 12px; }
    window#waybar { background: #202020; color: #eeeeee; }
    #custom-launcher, #network, #pulseaudio, #battery, #clock { padding: 0 8px; }
    #battery.warning { color: #ffcc66; }
    #battery.critical { color: #ff6666; }
  '';
  environment.etc."xdg/mimeapps.list".text = ''
    [Default Applications]
    text/html=vivaldi-stable.desktop
    x-scheme-handler/http=vivaldi-stable.desktop
    x-scheme-handler/https=vivaldi-stable.desktop
    text/plain=org.xfce.mousepad.desktop
    inode/directory=thunar.desktop
  '';
}

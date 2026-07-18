{ config, pkgs, ... }:

{
  # programs.slskd = {
    #enable = true;
    home.file.".local/share/slskd/slskd.yml".text = ''
    web:
      authentication:
        api_keys:
          soul_sync:
            key: "REDACTED"
            role: Administrator
  '';
}

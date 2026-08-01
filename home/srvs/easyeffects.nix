{ config, pkgs, ... }:

{
  # The EasyEffects that runs here is PATCHED via the `easyeffects-overlay` in
  # flake.nix (see that comment): the ~15-line upstream per-channel IPC backport
  # (wwmm/easyeffects 76a3f9a5) applied by home/srvs/easyeffects-perchannel.patch.
  # It lets the panel EQ set per-band gains over the local socket:
  #
  #   set_property:output:equalizer:0:left:band2Gain:-3.0
  #
  # The panel probes for this before enabling live-edit, so without this patch
  # the panel EQ just draws read-only. Reversible: drop the overlay + patch and
  # rebuild — no live state depended on it.
  services.easyeffects.enable = true;
}

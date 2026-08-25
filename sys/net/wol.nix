{ ... }:

# Wake-on-LAN for `top`'s wired NIC.
#
# What it is FOR, and what it is not. `top` never suspends itself (hypridle
# only blanks the screen), so this does nothing while the machine is merely
# idle — it is for the states where the box is genuinely OFF: a clean shutdown,
# or a power cut it did not come back from. A WEDGED machine is not one of
# them: a livelock leaves the NIC up and the kernel unable to act on anything
# it receives, so no magic packet reaches anything. Nothing short of a hardware
# watchdog or a switched plug recovers that one.
#
# WHO SENDS THE PACKET is the other half, and it is a LAN question, not a
# tailnet one: a magic packet is a broadcast on `top`'s own segment, and
# Tailscale carries unicast between nodes, not broadcasts onto a network whose
# only member is asleep. So waking `top` from away needs something at home that
# is on the tailnet AND on that LAN — `book` when it is at home, a router that
# can send one from its own admin page, a phone on the wifi. With everything
# out of the house this is a convenience for when he IS home, and honest to say
# so.
#
# THE BIOS HAS THE LAST WORD. The NIC is a Realtek r8169, which supports the
# magic-packet mode this arms, but the board still has to keep the PHY powered
# in S5 — on MSI that is "Resume By PCI-E Device" ON and ErP/Deep Sleep OFF.
# Neither is settable from here; a NixOS switch cannot check it either, so the
# test is the one below.
#
#   ethtool enp12s0 | grep Wake-on          # "Wake-on: g" once this is live
#   wol 34:5a:60:be:3b:3b                   # …from a machine on the same LAN
#                                           #   (or: wakeonlan / etherwake)
{
  # The interface is named for its PCI slot, and it is the same one every hole
  # in `share.nix` is scoped to — see AGENTS.md "Off-LAN: the tailnet" for why
  # nothing here is ever opened on every interface.
  networking.interfaces.enp12s0.wakeOnLan.enable = true;
}

# Disable kernel memory-alloc profiling (CONFIG_MEM_ALLOC_PROFILING=y, on by
# default on 7.2.0). Dedicated module so the knob has a named home and its
# why lives with it.
#
# Why: on 2026-08-22 the box hard-froze three times in two hours (boots -3,
# -2, -1, all ending with no clean shutdown). Boots -2 and -1 died on the same
# kernel oops — a DRM atomic mode-set from the compositor's DP-5 output crashed
# inside `__alloc_tagging_slab_alloc_hook` with a NULL pointer deref at 0x38.
# That function only runs when alloc profiling is active, so turning it off
# removes the faulting instruction entirely; the oops also took the session
# with it (no journal flush, manual power-cycle), so there was no trace left to
# chase in boot -1.
#
# Cost: no `/proc/allocinfo` allocation-site profiling — nothing here uses it.
#
# HOW THIS KNOB IS SET — a warning to the next reader. The original fix used
# `boot.kernelParams = [ "mem_alloc_profiling=off" ]`, which LOOKS right but
# did NOTHING. The kernel does not recognize `mem_alloc_profiling` as a
# command-line parameter — every boot it logs
#   Unknown kernel command line parameters "mem_alloc_profiling=off", ...
# and `vm.mem_profiling` stays 1, so the profiling crash path stayed live and
# the screen freezes kept coming. That is why the fix "didn't stick". Set the
# SYSCTL instead (below): NixOS writes it into /etc/sysctl.d/60-nixos.conf and
# systemd-sysctl applies it every boot. That is the mechanism that actually
# takes effect.
#
# Runtime toggle without a reboot (keeps the crash path off until next boot):
#   sudo sysctl vm.mem_profiling=0
{
  boot.kernel.sysctl."vm.mem_profiling" = 0;
}

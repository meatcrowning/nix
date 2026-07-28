{ pkgs, ... }:

{
  # Motherboard fan/temperature sensors on `top` (MSI PRO B650-VC WIFI,
  # MS-7D78). Out of the box there is no `fan*_input` anywhere under
  # /sys/class/hwmon — only nvme/spd5118/k10temp/amdgpu — so anything that
  # wants to show fan speeds (the Quickshell dock's fan bar) has nothing to
  # read and hides itself.
  #
  # The chip is a Nuvoton **NCT6687D**, not one of the NCT677x parts, so the
  # driver is `nct6683` — *not* `nct6775`, which is the answer you find first
  # and which does not probe this EC at all. Autoload does not happen because
  # it is an ISA/Super-I/O device with no bus to enumerate it; it has to be
  # named explicitly.
  #
  # No `acpi_enforce_resources=lax` needed, and deliberately not set. That
  # workaround exists for boards (classically Asus, via ATK0110) whose DSDT
  # declares an OperationRegion over the Super-I/O ports, which makes the
  # kernel's strict conflict check refuse the driver. nct6683 claims only the
  # 4-byte *secondary* EC window (0xa24-0xa27 here), which MSI's firmware does
  # not claim, so it loads clean under the default strict policy — verified on
  # this machine. Keeping strict means we are not handing the driver ports the
  # firmware might also be poking, which is the whole of the risk here.
  #
  # Read-only by design and by the driver: mainline nct6683 marks pwm* 0444
  # for every customer ID except Mitac's, so PWM writes fail with -EACCES
  # before reaching the hardware. There is no fan control here, no fancontrol
  # unit, and none should be added — the writable path lives in the
  # out-of-tree Fred78290/nct6687d driver, which this deliberately is not.
  #
  # To back out: delete this file and rebuild. The module is loaded by
  # systemd-modules-load, which the switch restarts, so both adding and
  # removing it take effect without a reboot (`modprobe -r nct6683` to drop it
  # immediately).
  boot.kernelModules = [ "nct6683" ];

  # `sensors` / `sensors -u`, for reading the above by hand.
  environment.systemPackages = [ pkgs.lm_sensors ];
}

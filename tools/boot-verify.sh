#!/usr/bin/env bash
# boot-verify.sh — how much of "will this rebuild actually boot?" can be
# answered WITHOUT rebooting `top`.
#
# OPT-IN. Nothing calls this automatically; preflight.sh does not run it and
# `sudo rebuild-top` does not either, because the VM half costs minutes.
#
#   ./tools/boot-verify.sh              # static checks only (~1 min, mostly cached)
#   ./tools/boot-verify.sh --vm         # + boot the configuration in headless QEMU
#   ./tools/boot-verify.sh --vm --keep  # leave the VM disk image behind for inspection
#
# WHAT THE STATIC HALF PROVES
#   The new toplevel exists and is internally complete: a bootspec, a kernel, an
#   initrd and an init that all really exist; every module the initrd is told to
#   have is actually in its module closure (or built in); the root filesystem's
#   driver is among them; the NVIDIA modules were built against THIS kernel; the
#   ESP has room for the new kernel+initrd. Those are the realistic ways a
#   rebuild here stops booting — a kernel bump that leaves an out-of-tree module
#   behind, a lost initrd module for the nvme root, or an ESP too full to take
#   the new entry.
#
# WHAT IT CANNOT PROVE
#   Nothing here executes the real initrd against the real disks, so it cannot
#   catch a broken UUID, a firmware/NVRAM problem, or a driver that loads but
#   hangs on this hardware.
#
# WHAT --vm PROVES, AND DOES NOT
#   It boots THIS configuration's userland in QEMU on a scratch disk and waits
#   for multi-user.target. That is a real, honest test of systemd unit ordering,
#   activation scripts, /etc generation and anything that can deadlock or fail
#   the boot in userland. It is NOT a test of this machine's boot path: the VM
#   variant substitutes a virtio root disk and its own initrd for the real nvme
#   root, has no NVIDIA GPU, and never touches the ESP or the bootloader. A
#   green --vm run plus green static checks is a strong signal; it is not a
#   guarantee, and the last three known-good generations pinned in the boot menu
#   (sys/boot-known-good.nix) are the actual safety net.
#
# Runs entirely headless: no window, no display, no bootloader write, no reboot.
set -euo pipefail

cd "$(dirname "$0")/.."

ATTR=${BOOT_VERIFY_ATTR:-top}
WITH_VM=0
KEEP=0
for a in "$@"; do
  case "$a" in
    --vm)   WITH_VM=1 ;;
    --keep) KEEP=1 ;;
    -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
    *) echo "unknown argument: $a" >&2; exit 2 ;;
  esac
done

fail=0
ok()   { printf '  ok    %s\n' "$*"; }
bad()  { printf '  FAIL  %s\n' "$*"; fail=1; }
note() { printf '  --    %s\n' "$*"; }

# stderr dropped: the only thing nix prints here is the "Git tree is dirty"
# warning, and a real eval failure still aborts under set -e.
evalcfg() { nix eval --raw ".#nixosConfigurations.$ATTR.config.$1" 2>/dev/null; }
evaljson() { nix eval --json ".#nixosConfigurations.$ATTR.config.$1" 2>/dev/null; }

echo "== building the toplevel =="
top=$(nix build --no-link --print-out-paths \
        ".#nixosConfigurations.$ATTR.config.system.build.toplevel")
echo "  $top"
if [ "$top" = "$(readlink -f /run/current-system)" ]; then
  note "identical to the running system — nothing has changed"
fi

echo
echo "== the toplevel is complete =="
for f in boot.json init kernel initrd kernel-params; do
  [ -e "$top/$f" ] && ok "$f present" || bad "$f MISSING from the toplevel"
done
kernel=$(readlink -f "$top/kernel"  || true)
initrd=$(readlink -f "$top/initrd"  || true)
[ -s "$kernel" ] && ok "kernel is a real file ($(du -h "$kernel" | cut -f1))" \
                 || bad "kernel does not resolve to a file"
[ -s "$initrd" ] && ok "initrd is a real file ($(du -h "$initrd" | cut -f1))" \
                 || bad "initrd does not resolve to a file"
if [ -r "$top/boot.json" ]; then
  for k in init initrd kernel; do
    p=$(jq -r ".[\"org.nixos.bootspec.v1\"].$k" "$top/boot.json")
    [ -e "$p" ] && ok "bootspec $k resolves" || bad "bootspec $k points at a missing path: $p"
  done
fi

echo
echo "== the initrd can find the root filesystem =="
closure=$(nix build --no-link --print-out-paths \
            ".#nixosConfigurations.$ATTR.config.system.build.modulesClosure")
have() {   # module name -> present in the closure, or built into the kernel
  find -L "$closure" -name "$1.ko*" -print -quit 2>/dev/null | grep -q . && return 0
  find -L "$closure" -name modules.builtin -exec grep -qx ".*/$1\.ko" {} + 2>/dev/null
}
rootfs=$(evalcfg 'fileSystems."/".fsType')
rootdev=$(evalcfg 'fileSystems."/".device')
note "root is $rootdev ($rootfs)"
have "$rootfs" && ok "the $rootfs module is in the initrd closure" \
               || bad "the initrd has no $rootfs module — the root fs would not mount"
missing=()
while read -r m; do
  have "$m" || missing+=("$m")
done < <(evaljson 'boot.initrd.availableKernelModules' | jq -r '.[]')
if [ ${#missing[@]} -eq 0 ]; then
  ok "every boot.initrd.availableKernelModules entry exists in the closure"
else
  # availableKernelModules is best-effort by design, so this is a warning; a
  # missing storage driver is caught by the root-device check below.
  note "not in the closure (harmless unless one is your root controller): ${missing[*]}"
fi
# The driver actually carrying the running root device. Only meaningful when
# verifying a config for the machine we are on.
if [ "$ATTR" = "top" ] && [ "$(hostname)" = "top" ]; then
  src=$(findmnt -no SOURCE /)
  pk=$(lsblk -no PKNAME "$src" | head -n1)
  drv=$(basename "$(readlink -f "/sys/block/$pk/device/../driver" 2>/dev/null || echo none)")
  case "$src" in
    /dev/nvme*) drv=nvme ;;
  esac
  if [ "$drv" != "none" ]; then
    have "$drv" && ok "the root device driver ($drv) is in the initrd closure" \
                || bad "the initrd has no $drv module — the root disk would not appear"
  fi
fi

echo
echo "== out-of-tree modules were built against this kernel =="
kver=$(basename "$(dirname "$(find -L "$top/kernel-modules/lib/modules" -maxdepth 2 -name modules.dep -print -quit)")")
note "kernel $kver"
for m in nvidia nvidia-modeset nvidia-drm; do
  find -L "$top/kernel-modules/lib/modules/$kver" -name "$m.ko*" -print -quit | grep -q . \
    && ok "$m built for $kver" \
    || bad "$m is MISSING for $kver — the desktop would come up with no GPU driver"
done

echo
echo "== the ESP can take the new entry =="
esp=$(evalcfg 'boot.loader.efi.efiSysMountPoint' 2>/dev/null || echo /boot)
if mountpoint -q "$esp"; then
  free=$(df -Pm "$esp" | awk 'NR==2 {print $4}')
  need=$(( ( $(stat -Lc %s "$kernel") + $(stat -Lc %s "$initrd") ) / 1048576 ))
  note "$esp: ${free}M free, this generation needs ~${need}M"
  [ "$free" -gt $((need + 64)) ] && ok "room for the new kernel and initrd" \
                                 || bad "$esp is too full — the bootloader install would fail"
else
  bad "$esp is not mounted; the bootloader cannot be updated"
fi

echo
echo "== kernel command line =="
newparams=$(tr ' ' '\n' < "$top/kernel-params" | sort -u)
oldparams=$(tr ' ' '\n' < /proc/cmdline | sort -u)
dropped=$(comm -23 <(echo "$oldparams") <(echo "$newparams") | grep -v '^init=\|^initrd=\|^BOOT_IMAGE=\|^$' || true)
[ -z "$dropped" ] && ok "nothing the running kernel was given has been dropped" \
                  || note "no longer passed: $(echo "$dropped" | tr '\n' ' ')"

if [ "$WITH_VM" = 1 ]; then
  echo
  echo "== headless VM boot =="
  echo "  building a VM variant of this configuration (this is the slow part)"
  expr_file=$(mktemp /tmp/boot-verify-vm.XXXXXX.nix)
  vmdir=$(mktemp -d /tmp/boot-verify-vm.XXXXXX)
  cleanup() { rm -f "$expr_file"; [ "$KEEP" = 1 ] || rm -rf "$vmdir"; }
  trap cleanup EXIT
  cat > "$expr_file" <<NIXEOF
let
  flake = builtins.getFlake "$PWD";
  ext = flake.nixosConfigurations.$ATTR.extendModules {
    modules = [ ({ lib, pkgs, ... }: {
      virtualisation.vmVariant = {
        # graphics = false is what gives us console=ttyS0 and -nographic;
        # nothing here can open a window on his screen.
        virtualisation = {
          graphics = false;
          memorySize = 4096;
          cores = 4;
          diskSize = 4096;
        };
        # The real ESP is not present in the VM and has no nofail; without this
        # local-fs.target never completes and the test would fail for a reason
        # that has nothing to do with the configuration.
        fileSystems."/boot".options = lib.mkForce [ "noauto" "nofail" ];
        systemd.services.boot-verify-token = {
          wantedBy = [ "multi-user.target" ];
          after = [ "multi-user.target" ];
          serviceConfig.Type = "oneshot";
          script = ''
            echo "BOOT-VERIFY-REACHED-MULTI-USER" > /dev/console
            \${pkgs.systemd}/bin/systemctl --force poweroff
          '';
        };
      };
    }) ];
  };
in ext.config.system.build.vm
NIXEOF
  vm=$(nix build --impure --no-link --print-out-paths --file "$expr_file")
  # the runner is a symlink into the store, so match on name, not -type f
  runner=$(find -L "$vm/bin" -maxdepth 1 -name 'run-*-vm' -print -quit)
  echo "  runner: $runner"
  echo "  booting (no display, serial only, 10 minute cap)"
  set +e
  ( cd "$vmdir" && \
    QEMU_KERNEL_PARAMS="" \
    QEMU_NET_OPTS="" \
    QEMU_OPTS="-display none -serial mon:stdio -no-reboot" \
    timeout 600 "$runner" ) > "$vmdir/console.log" 2>&1
  rc=$?
  set -e
  if grep -q 'BOOT-VERIFY-REACHED-MULTI-USER' "$vmdir/console.log"; then
    ok "the configuration reached multi-user.target in a VM"
  else
    bad "the VM never reached multi-user.target (qemu exit $rc)"
    echo "  --- last 30 console lines ---"
    tail -n 30 "$vmdir/console.log" | sed 's/^/  | /'
  fi
  grep -iE 'Failed to start|dependency failed' "$vmdir/console.log" \
    | sed 's/^/  !  /' | sort -u | head -n 15 || true
  [ "$KEEP" = 1 ] && note "VM disk and console log kept in $vmdir"
fi

echo
if [ "$fail" = 0 ]; then
  echo "PASS — nothing found that would stop this configuration booting."
  [ "$WITH_VM" = 1 ] || echo "       (static checks only; add --vm to boot it headless)"
else
  echo "FAIL — see above. Do not switch to this configuration."
  exit 1
fi

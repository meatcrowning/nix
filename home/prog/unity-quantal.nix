{ config, lib, pkgs, host, ... }:

# The original Ubuntu 12.10 Unity desktop, run locally on top. The guest image
# is deliberately mutable host data rather than a Nix store input: it contains
# Ubuntu's historical binary payload and is maintained by the private runbook
# in docs/agents/unity-quantal-experiment/. The root itself is a read-only
# squashfs under a tmpfs overlay, so every launch starts clean.
let
  dataDir = "${config.xdg.dataHome}/unity-quantal";
  unityQuantal = pkgs.writeShellApplication {
    name = "unity-quantal";
    runtimeInputs = [ pkgs.coreutils pkgs.libnotify pkgs.qemu_kvm pkgs.util-linux pkgs.virt-viewer ];
    text = ''
      set -eu

      data_dir=${lib.escapeShellArg dataDir}
      runtime_dir="''${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/unity-quantal"
      mkdir -p "$runtime_dir"

      exec 9>"$runtime_dir/launch.lock"
      if ! flock -n 9; then
        notify-send 'unity is already open'
        exit 0
      fi

      for image_file in root.squashfs initrd.gz vmlinuz; do
        if [ ! -r "$data_dir/$image_file" ]; then
          notify-send 'unity image is missing'
          exit 1
        fi
      done

      render_node=
      for node in /dev/dri/renderD*; do
        [ -e "$node" ] || continue
        vendor_file="/sys/class/drm/$(basename "$node")/device/vendor"
        [ -r "$vendor_file" ] || continue
        if [ "$(<"$vendor_file")" = 0x1002 ]; then
          render_node=$node
          break
        fi
      done
      if [ -z "$render_node" ]; then
        notify-send 'unity could not find the amd gpu'
        exit 1
      fi

      rm -f "$runtime_dir/qmp.sock"
      qemu-system-x86_64 \
        -name unity-quantal \
        -machine q35,accel=kvm -cpu host -smp 4 -m 4096 \
        -kernel "$data_dir/vmlinuz" -initrd "$data_dir/initrd.gz" \
        -append 'console=ttyS0,115200 loglevel=4 panic=-1' \
        -drive "file=$data_dir/root.squashfs,format=raw,if=virtio,readonly=on" \
        -device virtio-vga-gl,xres=1920,yres=1080 \
        -display "egl-headless,rendernode=$render_node" \
        -spice addr=127.0.0.1,port=15930,disable-ticketing=on,gl=off,disable-copy-paste=on,disable-agent-file-xfer=on \
        -audiodev spice,id=audio -device ich9-intel-hda -device hda-output,audiodev=audio \
        -device qemu-xhci -device usb-tablet \
        -nic none -serial "file:$runtime_dir/serial.log" \
        -qmp "unix:$runtime_dir/qmp.sock,server=on,wait=off" \
        -monitor none -no-reboot >"$runtime_dir/qemu.log" 2>&1 &
      qemu_pid=$!
      cleanup() {
        kill "$qemu_pid" 2>/dev/null || true
        wait "$qemu_pid" 2>/dev/null || true
      }
      trap cleanup EXIT INT TERM

      ready=0
      for _ in $(seq 1 100); do
        if [ -S "$runtime_dir/qmp.sock" ]; then
          ready=1
          break
        fi
        kill -0 "$qemu_pid" 2>/dev/null || break
        sleep 0.1
      done
      if [ "$ready" != 1 ]; then
        notify-send 'unity did not start'
        exit 1
      fi

      remote-viewer --title='ubuntu 12.10' --auto-resize=never spice://127.0.0.1:15930
    '';
  };
in
lib.mkIf (host == "top") {
  home.packages = [ unityQuantal ];

  home.file.".local/share/applications/unity-quantal.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=ubuntu 12.10
    GenericName=Virtual Desktop
    Comment=Original Unity desktop
    Exec=${unityQuantal}/bin/unity-quantal
    Icon=computer
    Terminal=false
    Categories=System;Emulator;
    Keywords=ubuntu;unity;virtual machine;
  '';
}

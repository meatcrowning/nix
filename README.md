# `nixos/hyprland/qs/plasma/...`

monorepo for what is essentially my entire system. point an agent at this and ask it to explain. 

## Minimal laptop (`pad`)

`nixosConfigurations.pad` is a standalone ThinkPad 11e configuration: Hyprland,
Vivaldi, Foot, Mousepad, Thunar, a small Waybar, and laptop controls. Super+Enter
opens a terminal, Super+D the launcher, Super+B the browser, Super+N the editor,
Super+E files, Super+W Wi-Fi setup, Super+L locks, and Super+Shift+E logs out.
Super+Q closes a window; Super+arrow focuses a neighbor; Super+1 through Super+5
switch workspaces (add Shift to move a window). Volume/brightness keys
work directly. Idle locking starts after five minutes; suspend after twenty.

Build from a clean, committed checkout on `top`:

```sh
tools/deploy-pad.sh build
tools/deploy-pad.sh boot root@pad    # activate at next reboot
tools/deploy-pad.sh switch root@pad  # activate now
```

Evaluation and compilation both happen on top. The laptop receives the finished
closure over SSH. These commands update an installed NixOS system; they do not
partition disks or install over Arch. Provision a dedicated deployment public
key in pad's `/etc/ssh/authorized_keys.d/root` (root-owned, mode 0600), with its
private key in top's SSH configuration. Verify pad's SSH host key locally before
the first connection. Root password SSH is disabled.

For initial installation, boot an x86_64 NixOS USB in UEFI mode and mount the
chosen target at `/mnt`. The default hardware module expects an ext4 root labelled
`nixos` and a FAT ESP labelled `BOOT` at `/mnt/boot`; review or regenerate it for
the actual layout before building. Prefer a 1 GiB ESP on a freshly partitioned
disk. The config creates a 4 GiB swapfile plus zram. Do not format the current
Arch partitions without a backup and an explicit decision to replace them.

Build `result-pad` on top, transfer its closure to the live installer's store,
then run `nixos-install --root /mnt --system /nix/store/…-nixos-system-pad-…`
there, using the exact store path printed by the build. Set the `lam` user's
password with `nixos-enter --root /mnt -c 'passwd lam'`, provision the deployment
public key inside `/mnt/etc/ssh/authorized_keys.d/root`, and set the timezone
with `timedatectl set-timezone` after boot. The installer transport must be
configured separately; do not assume the live ISO has the installed SSH policy.

Vivaldi is selected without importing the custom desktop. Surfer uses QtWebEngine
and the shared app infrastructure; lower memory use has not been established.

screenshots of individual programs and hyprland setup below. all programs are native-styled in both hyprland and kde plasma. not shown; filer, player, reader, viewer, goetia, editor, and askpass:

<img width="1786" height="1353" alt="collage" src="https://github.com/user-attachments/assets/bd9e2457-fdce-43ac-ae21-eb1d24581442" />

<img width="1273" height="956" alt="Screenshot_20260906_155708" src="https://github.com/user-attachments/assets/bbef7106-e01f-4ec3-8991-212baca10bb6" />

<img width="1920" height="1080" alt="Screenshot_20260730_223852" src="https://github.com/user-attachments/assets/e7119d2f-d39a-4ae8-bf02-a5cbbb3e79fa" />

<img width="2560" height="1600" alt="Screenshot_20260728_001720" src="https://github.com/user-attachments/assets/1c1b5dce-7156-4d66-b38f-ea85366a657e" />

https://github.com/user-attachments/assets/fecfa97c-5697-407a-9291-020ac69e7bf4

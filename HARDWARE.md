# HARDWARE.md — what these two machines actually are

**Read this before you measure.** Every fact below is one an agent has already
had to rediscover from scratch at least once, and at least one of those
rediscoveries started from a *wrong* remembered fact and burned an hour. If
something here contradicts what you remember, this file is the one to trust —
and if it contradicts what the machine says, fix this file.

Each fact carries the command that establishes it. That is the point: this is a
re-verifiable snapshot, not a claim. Re-run the command rather than trusting the
number, and update the line if it moved.

**Nothing in here is a unique identifier.** This repo is public. Board *model*,
chip *model*, core *count*, GPU *model*, panel *model* are all class-level and
fine. Serial numbers, MACs, disk WWNs, filesystem UUIDs and IP addresses are
not — a monitor serial was committed here in a source comment once (`ee1d105`)
and survives in history. If a fact only becomes useful once you attach an
identifier to it, the identifier goes in the private `docs/` repo or a memory,
and this file says so instead of carrying it.

---

## Two machines, and they are not alike

| | `top` | `book` |
|---|---|---|
| what | desktop tower | MacBook Air |
| OS | **NixOS** 26.11 "Zokor" | **Fedora Asahi Remix** |
| arch | `x86_64-linux` | `aarch64-linux` |
| flake attr | `nixosConfigurations.top` | `homeConfigurations.air` |
| nix scope | full NixOS: `sys/` **and** `home/` | **`home/` only** — `sys/*` does not apply, and there is no `hosts/air/` |
| rebuild | `sudo rebuild-top` (NOPASSWD, no tty needed) | `home-manager switch --flake ~/nix#air` |
| compositor | nix Hyprland, pinned tag | Fedora's **rpm** Hyprland 0.55.4 — hence the `hyprland-air` pin and the `VTB_HL_056` seam |
| display scale | `1` | `1.67` (Hyprland), `2` (Xwayland under Plasma) |
| binary cache | yes, everything | **no aarch64 Hyprland cache** — a pin bump compiles it, ~7 min, cap the RAM |

`hostname` on the laptop is **`book`**; the flake attribute for it is **`air`**.
Both names are correct, for different things. **Run `hostname; uname -m` before
you assume which one you are on** — the two rebuild commands are not
interchangeable and neither exists on the other machine.

Per-host branching is the `host` module arg (`{ host, ... }:`, `"top" | "air"`),
never a new per-host file. x86_64-only packages are gated on
`pkgs.stdenv.hostPlatform.isx86_64`, because the real constraint is the
architecture, not the machine.

---

## `top` — the desktop

### CPU

**AMD Ryzen 7 9800X3D**, 8 physical cores / **16 threads**, 1 socket, boost
4.7 GHz.

```bash
lscpu | grep -E 'Model name|^CPU\(s\)|Core|Thread'
nproc            # 16 — this is the number a per-core UI must lay out for
```

16 is the figure any per-core visualisation (the panel's CPU column, a load
grid) has to fit. It is threads, not cores: the panel draws 16 lanes.

Process CPU% from `ps`/`top` is **Solaris mode by default** — already divided by
the thread count, so a fully-loaded machine reads ~100%, not ~1600%. If you want
Irix mode (per-core, up to 1600%), multiply by `nproc` yourself; the panel's
`proc-list.py` documents which convention it publishes.

### Memory

**30 GiB usable** (32 GB installed, minus what the iGPU carves out).

```bash
free -h
```

Swap is **zram (~15 GiB, priority 5)** plus a **16 GiB `/var/lib/swapfile`**
(priority -1, i.e. only after zram is exhausted). There is also an inactive swap
partition on an old SSD; it is not swapped on, so ignore it.

```bash
swapon --show
```

### GPU — there are two, and only one drives the screen

- **NVIDIA GeForce RTX 5070** (GB205, 12 GB), **proprietary** driver with
  `nvidia.open = true`. This is the one with the display attached.
- **AMD Radeon iGPU** (Granite Ridge, part of the 9800X3D package), `amdgpu`.
  Present, enumerated, has its own hwmon node — **but nothing is plugged into
  it.** Do not mistake its `edge` temperature or its `sclk` for the real GPU's.

```bash
lspci -nn | grep -Ei 'vga|3d'
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv
# which card actually has the connected output:
for c in /sys/class/drm/card*-*/; do [ "$(cat $c/status)" = connected ] && echo "$c"; done
```

The GPU **fan** is *not* an hwmon fan. It comes from `nvidia-smi` as a
percentage, and **0% at idle is a real reading**, not a broken sensor — the card
stops its fan when cool. This is a different sensor from the chassis fans below
and the two must not be merged into one readout.

Config: `sys/hw/nvidia.nix` (`modesetting.enable`, `nvidia-drm.modeset=1`,
`nvidia-drm.fbdev=1`).

### Motherboard, and the sensor chip

**MSI PRO B650-VC WIFI**, board code **MS-7D78**.

```bash
cat /sys/devices/virtual/dmi/id/board_{vendor,name} /sys/devices/virtual/dmi/id/bios_{version,date}
```

Its Super-I/O monitoring chip is a **Nuvoton NCT6687D**, and the driver for it
is **`nct6683`** — *not* `nct6775`. This matters more than it looks:

- `nct6775` does not probe this EC at all. The widely-cited
  "`nct6775` + `acpi_enforce_resources=lax`" fix that every forum thread offers
  **does nothing here**, and a stale note claiming otherwise sent an agent down
  it for an hour.
- **No `acpi_enforce_resources=lax` is needed, and it is deliberately not set.**
  `nct6683` claims only the secondary EC window (0xa24-0xa27), which MSI's DSDT
  does not declare, so it passes the *default strict* ACPI conflict check.
  `lax` is an Asus/ATK0110 workaround; strict policy is preserved on purpose.
- Being ISA / Super-I/O there is no bus to autoload from, so the module has to
  be named explicitly. It is: `boot.kernelModules = [ "nct6683" ]` in
  `sys/hw/sensors.nix`. **No reboot was required** — `modprobe` picks it up.

```bash
for d in /sys/class/hwmon/hwmon*; do echo "$d $(cat $d/name)"; done
sensors            # lm_sensors is in environment.systemPackages
```

### Fans and pwm — the real layout

The `nct6687` hwmon node exposes **10 `fan*_input` channels, of which 4 are
populated**:

| channel | header (per LibreHardwareMonitor, *unverified against the board*) | typical |
|---|---|---|
| `fan1` | CPU_FAN1 | few hundred RPM at idle |
| `fan2` | PUMP_FAN1 | ~3450 RPM, effectively fixed-speed |
| `fan3` | SYS_FAN1 | ~1300 |
| `fan4` | SYS_FAN2 | ~1100 |
| `fan5`–`fan10` | unpopulated | constant 0 |

```bash
grep . /sys/class/hwmon/hwmon*/fan*_input     # hwmonN varies across boots
```

Three consequences that have each bitten something already:

- **Mainline `nct6683` exposes no `fan*_label`.** The header names above come
  from LibreHardwareMonitor and are not confirmed by the chip. **Render whatever
  channels are nonzero; never hard-code an index to a name.**
- **`pwm*` is read-only, and not by our restraint.** Mainline marks `pwm1`–`pwm8`
  `0444` for every customer ID except Mitac's, so a write fails `-EACCES` before
  it reaches hardware. Fan *control* from this driver is impossible; it would
  need the out-of-tree `Fred78290/nct6687d`, which this deliberately is not.
  `pwm/255` is still a usable duty-cycle *percentage* — but it is what the chip
  **commands**, not a fraction of the fan's maximum, which sysfs never publishes.
- **A fan that never varies is not a fan that stopped.** The pump sits at a
  fixed speed by design; treating "unchanging" as "failed" produced a false
  critical alarm in the panel.

Voltages (`in*`) from this chip are **unreliable** — mainline applies a flat
16 mV/LSB heuristic while MSI uses per-rail multipliers. One temperature channel
reports ~83 °C constantly; bogus channels are a known NCT6687-on-mainline
failure mode. Sanity-check anything from this chip before drawing it.

Other hwmon nodes present: `k10temp` (CPU `Tctl` — the temperature to use),
`nvme`, two `spd5118` (DIMM temperature sensors), `amdgpu` (the *idle iGPU*, see
above), `mt7921_phy0` (Wi-Fi), `hidpp_battery_0` (a wireless input device).

### Display

One monitor: a **Dell P2422HE**, **1920x1080 @ 60 Hz**, 530x300 mm, scale **1**,
no VRR, on **DP-5** off the NVIDIA card.

```bash
hyprctl monitors
```

**`hyprctl monitors` prints the panel's SERIAL.** Do not paste its output into
this repo, a commit message, or any file under `~/nix` outside `docs/`. That is
the exact leak `ee1d105` had to redact.

1080p is the budget every layout is designed against — there is no second screen
and no headroom. Notably the `player` window runs at roughly **480x826**, not
the 1080-tall default, so its layouts need floors and stacked fallbacks.

**Telling a real monitor from an agent's sandbox monitor.** `tools/sandbox.sh`
creates one with `hyprctl output create headless`, and it is a real output in
every way the compositor cares about — so anything that must not act on it needs
a test. The rule, implemented in `home/prog/quickshell-files/WinState.qml`:

> A **physical** output has a non-zero physical size **and** at least one of
> make / model / serial / description. A headless one has none of those. The
> `HEADLESS-n` name prefix is ORed in as corroboration, never as the sole test.

Use that predicate, not the name alone, and not a hard-coded `DP-5`. Panels,
grids, VU meters and window lists have each had to learn this separately; the
`WinState.qml` comment is the canonical statement.

### Storage — the parts that change decisions

The root filesystem is a **single 1.8 T ext4 partition on an NVMe SSD**
(WD Green SN3000). It runs full: budget before any bulk write.

```bash
df -hT -x tmpfs -x devtmpfs
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,MODEL,ROTA     # ROTA=1 means spinning rust
```

Everything else is external or secondary, and the tiering matters more than the
capacities:

| mount | kind | what it is for |
|---|---|---|
| `/` | NVMe SSD | the system, `~`, and the model files. **Models stay here** — load speed outranks the space; do not propose moving `~/models` or `~/.ollama` off root. |
| `/run/media/lam/SSD` | SATA **SSD**, **exFAT** | the ~208 GB music library (`aud`). exFAT means **reserved characters** — `\ / : * ? " < > |` are illegal in filenames, which the library reorg tooling has to respect. |
| `/home/lam/drives/cld`, `/home/lam/drives/linux-old` | HDD, btrfs | bulk / archival |
| `/home/lam/drives/nixos-old` | SATA SSD, ext4 | the previous install |
| `/run/media/lam/arc` | USB HDD | archive |
| `/run/media/lam/bak` | USB HDD, btrfs | backups — **its USB bridge discards flushes**, so `fsync` is not durable and btrfs is at risk on power loss. Do not put anything here you cannot re-create. |

The decisive number is not capacity but the **fsync cliff**: flash does
638–3701 IOPS here, the spinning disks 14–24. Anything that fsyncs in a loop (a
git repo, a SQLite database, a build tree) is unusable on the HDDs regardless of
free space. Measured detail, per-drive health and the monitoring gaps are in the
private `docs/top-storage-tiers.md`.

`/home` has **no btrfs snapshots**. A deleted file there is gone; there is no
rollback.

### Compositor and session

```bash
hyprctl version           # pinned tag; see flake.nix for why it is pinned
hyprctl plugin list       # exactly one hyprvtb, at the expected Version
uname -r; nixos-version
```

The live session is Hyprland + a Quickshell panel + the `hyprvtb` plugin. Plasma
6 is installed as an alternative session. All of it is described in `AGENTS.md`
and the nested guides; this file only claims the metal underneath.

---

## `book` — the MacBook Air

Not measurable from `top`. What is established:

- **Apple Silicon**, `aarch64-linux`, Fedora Asahi Remix, OS hostname `book`.
- GPU is the Apple one via Asahi Mesa, `/dev/dri/card2`, output `eDP-1`.
  **nixpkgs' Mesa does not work on Apple Silicon** — an app must use Fedora's,
  which is why the port keeps some things off nix deliberately.
- Retina panel: Hyprland scale `1.67`, Xwayland scale `2`
  (`home/prog/hypr-host.nix`, `home/plasma.nix`, both branching on `host`).
- Whole-machine power is available from `macsmc_hwmon` ("Total System Power") —
  a sensor `top` has no equivalent for.
- `tailscaled` is Fedora system state and **cannot** live in this repo.
- **nix-built binaries on book cannot resolve `.local` mDNS names** — only
  Fedora binaries can. The SMB mount uses the MagicDNS name `top`, not
  `top.local`, for exactly this reason.

Its SSD layout and the deferred macOS-removal plan are in a memory, not here —
they involve partition-level detail.

---

## When this file is wrong

It will be, eventually. The failure mode this file exists to prevent is an agent
acting on a *remembered* hardware fact that was never true. So:

- **Measure, then edit here.** Every section above names its command.
- A fact that needs a serial, UUID, MAC or IP to be actionable does **not**
  belong in this file — put it in the private `docs/` repo and leave a pointer.
- If you rediscover something from scratch because it was not here, that is the
  signal to add it.

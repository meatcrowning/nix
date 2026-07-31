{ config, pkgs, lib, ... }:

# Known-good boot entries — a second, pinned section in the systemd-boot menu.
#
# The normal menu shows the last `configurationLimit` (15) *configuration*
# generations, and `nix-collect-garbage --delete-older-than 14d` (weekly, see
# sys/base.nix) eventually eats them — so after a fortnight of daily rebuilds
# every entry in the menu can be younger than the last time the machine
# demonstrably came up. This module keeps, IN ADDITION, the last three
# generations that were *observed to boot*, and makes them immune to garbage
# collection.
#
# Three moving parts, all self-managed so nothing here fights the bootloader
# installer:
#
#   1. MARKER — `known-good-boot.timer` fires 3 minutes after boot and runs
#      the recorder, which records /run/booted-system (NOT current-system: a
#      rebuild since boot must not be credited with having booted). "Good" is
#      defined as *multi-user.target reached and still up 3 minutes later* —
#      not a graphical session, because a deliberate boot to a TTY is still a
#      good boot, and not merely "systemd started", because an initrd/root-fs
#      failure can still get that far.
#
#   2. GC IMMUNITY — each kept generation is held by a permanent GC root under
#      /nix/var/nix/gcroots/known-good-boots/. That single root blocks BOTH
#      the root-level `nix-collect-garbage` and the user-profile one (all
#      collection goes through the daemon, which reads this directory), which
#      matters here because on `top` the user profile is the collection that
#      actually frees space.
#
#   3. MENU — the recorder writes its own loader entries and its own copies of
#      kernel+initrd on the ESP. It deliberately does NOT use
#      `boot.loader.systemd-boot.extraEntries`, which is evaluated at rebuild
#      time and so cannot name a runtime-discovered generation. The paths are
#      chosen against what the installer actually deletes
#      (nixpkgs' systemd-boot builder, `garbage_collect()`): it unlinks
#      everything under /boot/EFI/nixos and every /boot/loader/entries/nixos-*.conf
#      that is not a current generation. Ours live at /boot/EFI/known-good/ and
#      /boot/loader/entries/known-good-*.conf, so a rebuild never touches them
#      — and because the kernel and initrd are OUR copies, the entry stays
#      bootable even once the generation itself is gone from the menu.
#
# `sort-key zz-known-good` sorts the whole set below the `nixos` generation
# list, so it reads as its own section at the bottom of the menu.
#
# NixOS-only (sys/), so `book` does not get this.

let
  recorder = pkgs.writeShellApplication {
    name = "known-good-boots";
    runtimeInputs = with pkgs; [ coreutils jq systemd gnused findutils gawk ];
    text = ''
      # Ring of the last three generations observed to boot successfully.
      #   known-good-boots record   — mark /run/booted-system good (the timer)
      #   known-good-boots list     — what is currently pinned
      #   known-good-boots prune    — re-apply the keep-3 rule
      #
      # SAFETY: this script only ever ADDS to the ESP under its own directory
      # and its own entry names. It never writes, moves or deletes a
      # nixos-generation entry, and every failure path leaves the machine
      # exactly as bootable as it found it.

      # The KGB_* overrides exist so tools/boot-known-good-test.sh can exercise
      # every path of this script against a throwaway directory tree. Nothing
      # in the deployed units sets them.
      KEEP="''${KGB_KEEP:-3}"
      ROOTS="''${KGB_ROOTS:-/nix/var/nix/gcroots/known-good-boots}"
      BOOTMNT="''${KGB_BOOT:-/boot}"
      ESP="$BOOTMNT/EFI/known-good"
      ENTRIES="$BOOTMNT/loader/entries"
      BOOTED_LINK="''${KGB_BOOTED:-/run/booted-system}"
      # Headroom to leave free on the ESP after a copy, in MiB.
      MARGIN_MB="''${KGB_MARGIN_MB:-64}"

      log() { echo "known-good-boots: $*" >&2; }

      # hash part of a /nix/store path, used as the slot key
      slot_of() { basename "$1" | cut -d- -f1; }

      list_slots() {
        # newest last; the name is <UTC timestamp>-<slot>, so plain sort works
        [ -d "$ROOTS" ] || return 0
        find "$ROOTS" -maxdepth 1 -type l -printf '%f\n' 2>/dev/null | sort
      }

      drop_slot() {
        local name="$1" slot="''${1#*-}"
        rm -f "$ROOTS/$name"
        rm -f "$ENTRIES/known-good-$slot.conf"
        rm -rf "''${ESP:?}/$slot"
        log "dropped $name"
      }

      # free MiB on the ESP
      esp_free_mb() { df -Pm "$BOOTMNT" | awk 'NR==2 {print $4}'; }

      cmd_prune() {
        local keep="''${1:-$KEEP}" all n booted_slot
        booted_slot=$(slot_of "$(readlink -f "$BOOTED_LINK")")
        mapfile -t all < <(list_slots)
        n=''${#all[@]}
        while [ "$n" -gt "$keep" ]; do
          if [ "''${all[0]#*-}" = "$booted_slot" ]; then
            # never drop the generation we are running right now; it is the one
            # thing we know for certain still boots.
            break
          fi
          drop_slot "''${all[0]}"
          all=("''${all[@]:1}")
          n=$((n - 1))
        done
      }

      cmd_list() {
        local name slot target
        if [ -z "$(list_slots)" ]; then echo "no known-good generations recorded yet"; return 0; fi
        while read -r name; do
          slot="''${name#*-}"
          target=$(readlink -f "$ROOTS/$name" || echo "MISSING")
          printf '%s  %s\n' "''${name%%-*}" "$target"
          printf '    gcroot %s\n    entry  %s\n' "$ROOTS/$name" "$ENTRIES/known-good-$slot.conf"
        done < <(list_slots)
      }

      cmd_record() {
        local booted slot json kernel initrd init params label stamp title version need free gen

        # Evidence that this boot is actually good. Anything short of this is
        # not an error — it is simply not a recordable boot.
        if [ -z "''${KGB_SKIP_TARGET_CHECK:-}" ] && ! systemctl is-active --quiet multi-user.target; then
          log "multi-user.target is not active; not recording"
          return 0
        fi

        booted=$(readlink -f "$BOOTED_LINK")
        slot=$(slot_of "$booted")

        if [ -n "$(find "$ROOTS" -maxdepth 1 -type l -name "*-$slot" 2>/dev/null)" ]; then
          log "generation $slot already recorded"
          return 0
        fi

        json="$booted/boot.json"
        [ -r "$json" ] || { log "no bootspec at $json; not recording"; return 0; }

        if [ "$(jq -r '.["org.nixos.bootspec.v1"].initrdSecrets // empty' "$json")" != "" ]; then
          log "bootspec has initrdSecrets, which this ring cannot reproduce; not recording"
          return 0
        fi

        kernel=$(jq -r '.["org.nixos.bootspec.v1"].kernel' "$json")
        initrd=$(jq -r '.["org.nixos.bootspec.v1"].initrd' "$json")
        init=$(jq -r '.["org.nixos.bootspec.v1"].init' "$json")
        label=$(jq -r '.["org.nixos.bootspec.v1"].label' "$json")
        params=$(jq -r '.["org.nixos.bootspec.v1"].kernelParams | join(" ")' "$json")

        for f in "$kernel" "$initrd" "$init"; do
          [ -e "$f" ] || { log "bootspec names a missing file ($f); not recording"; return 0; }
        done

        mkdir -p "$ROOTS" "$ESP" "$ENTRIES"

        # Make room before copying — but only if evicting the oldest slot would
        # actually be enough. Spending a known-good generation on a copy that
        # then fails for want of space would leave the ring worse than
        # untouched.
        need=$(( ( $(stat -Lc %s "$kernel") + $(stat -Lc %s "$initrd") ) / 1048576 + MARGIN_MB ))
        free=$(esp_free_mb)
        if [ "$free" -lt "$need" ]; then
          local oldest reclaim
          oldest=$(list_slots | head -n1)
          reclaim=0
          [ -n "$oldest" ] && [ -d "$ESP/''${oldest#*-}" ] \
            && reclaim=$(du -sm "$ESP/''${oldest#*-}" | cut -f1)
          if [ $((free + reclaim)) -ge "$need" ]; then
            cmd_prune $((KEEP - 1))
            free=$(esp_free_mb)
          fi
        fi
        if [ "$free" -lt "$need" ]; then
          log "ESP has ''${free}M free, needs ''${need}M; not recording (menu left untouched)"
          return 0
        fi

        # Copy first, write the entry last: a half-copied slot is invisible to
        # the boot menu, an entry pointing at a half-copied kernel is not.
        rm -rf "''${ESP:?}/$slot"
        mkdir -p "$ESP/$slot"
        cp -L "$kernel" "$ESP/$slot/linux.tmp" && mv "$ESP/$slot/linux.tmp"  "$ESP/$slot/linux"
        cp -L "$initrd" "$ESP/$slot/initrd.tmp" && mv "$ESP/$slot/initrd.tmp" "$ESP/$slot/initrd"
        sync

        stamp=$(date -u +%Y%m%d%H%M%S)
        gen=$(find /nix/var/nix/profiles -maxdepth 1 -name 'system-*-link' -lname "$booted" \
                -printf '%f\n' 2>/dev/null | sed 's/^system-\(.*\)-link$/\1/' | head -n1 || true)
        title="NixOS known-good $(date +%Y-%m-%d)''${gen:+ (generation $gen)}"
        # `version` is what systemd-boot sorts on inside the group, descending,
        # so the newest known-good sits at the top of its section.
        version="$stamp"

        {
          echo "title    $title"
          echo "version  $version"
          echo "sort-key zz-known-good"
          echo "linux    /EFI/known-good/$slot/linux"
          echo "initrd   /EFI/known-good/$slot/initrd"
          echo "options  init=$init $params"
          echo "# $label"
        } > "$ENTRIES/known-good-$slot.conf.tmp"
        mv "$ENTRIES/known-good-$slot.conf.tmp" "$ENTRIES/known-good-$slot.conf"
        sync

        # The GC root goes in only once the entry is real, and is what keeps
        # `init=` above resolvable after the generation leaves the profile.
        ln -sfn "$booted" "$ROOTS/$stamp-$slot"

        log "recorded $booted as known-good ($title)"
        cmd_prune "$KEEP"
      }

      case "''${1:-record}" in
        record) cmd_record ;;
        list)   cmd_list ;;
        prune)  cmd_prune "''${2:-$KEEP}" ;;
        *) echo "usage: known-good-boots [record|list|prune [n]]" >&2; exit 2 ;;
      esac
    '';
  };
in
{
  systemd.services.known-good-boot = {
    description = "Record the running generation as a known-good boot";
    after = [ "multi-user.target" ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${recorder}/bin/known-good-boots record";
    };
    # Deliberately not wantedBy anything: the timer below is the only trigger,
    # so the marker cannot fire before the machine has proven it stays up.
  };

  systemd.timers.known-good-boot = {
    description = "Mark this boot known-good once it has stayed up";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "3min";
      AccuracySec = "30s";
      Unit = "known-good-boot.service";
    };
  };

  environment.systemPackages = [ recorder ];

  # Exposed so tools/boot-known-good-test.sh can build the recorder on its own,
  # without realising a whole system closure.
  system.build.knownGoodBoots = recorder;
}

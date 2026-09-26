"""Complete-release acquisition over the existing slskd/importer protocol."""
import fcntl
import importlib.util
import re
import shutil
import socket
import time
import urllib.parse
from pathlib import Path

import trackmatch
from discovery import album_name


class DeferredAcquisition(ValueError):
    """A temporary gate, not a bad recommendation or a failed transfer."""


def pipeline():
    spec = importlib.util.spec_from_file_location("discovery_slsk", Path(__file__).parent / "tools/soulseek-missing.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def complete_candidate(item, responses, quality):
    """Never assemble a guessed edition from unrelated peer folders."""
    candidates = []
    for response in responses:
        groups = {}
        for f in response.get("files", []):
            path = f.get("filename", "")
            folder, _, name = path.rpartition("\\")
            ext = name.rsplit(".", 1)[-1].lower()
            if ext not in ("flac", "alac", "wav", "aiff", "mp3", "m4a", "ogg", "opus"):
                continue
            groups.setdefault(folder, []).append(f)
        for folder, files in groups.items():
            parts = folder.split("\\")
            # Only known packaging labels may be ignored; live/remix titles stay distinct.
            leaf = re.sub(r"[\[(](?:(?:19|20)\d{2}|FLAC|MP3|ALAC|lossless)[\])]", "", parts[-1], flags=re.I)
            leaf = re.sub(r"^(?:19|20)\d{2}\s*[-–.]?\s*", "", leaf)
            artist_key = trackmatch.fold(item["artist"])
            album_key = album_name(item["album"])
            exact_folder = album_name(leaf) == album_key and any(trackmatch.fold(p) == artist_key for p in parts[:-1])
            combined_folder = album_name(leaf) == trackmatch.fold(item["artist"] + " " + album_key)
            if not (exact_folder or combined_folder):
                continue
            if len(files) != len(item["tracks"]):
                continue
            picked = []
            for track in item["tracks"]:
                matches = []
                for f in files:
                    stem = f["filename"].rsplit("\\", 1)[-1].rsplit(".", 1)[0]
                    stem = re.sub(r"^\s*(?:\d+[-_. ])+\s*", "", stem)
                    # Exact title or artist-title, no substring matches for live/remix editions.
                    title = trackmatch.fold(track["title"])
                    if trackmatch.fold(stem) not in (title, trackmatch.fold(track["artist"] + " - " + track["title"])):
                        continue
                    if not f.get("length") or not track["duration"] or abs(float(f["length"]) - track["duration"]) > 5:
                        continue
                    ext = f["filename"].rsplit(".", 1)[-1].lower()
                    if quality == "lossless" and ext not in ("flac", "alac", "wav", "aiff"):
                        continue
                    if quality == "high" and ext not in ("flac", "alac", "wav", "aiff") and float(f.get("bitRate") or 0) < 256:
                        continue
                    if int(f.get("size") or 0) <= 0:
                        continue
                    matches.append(f)
                if len(matches) != 1 or matches[0] in picked:
                    break
                picked.append(matches[0])
            if len(picked) == len(item["tracks"]):
                candidates.append((0 if response.get("hasFreeUploadSlot") else 1,
                                   int(response.get("queueLength") or 0), response["username"], picked))
    if not candidates:
        raise ValueError("No complete release matched the tracklist and quality. Nothing queued.")
    _, _, user, files = min(candidates, key=lambda x: x[:2])
    return user, files


def acquire(catalog, key, root, stop, automatic=False, slsk=None, host=None):
    host = host or socket.gethostname().split(".")[0]
    settings = catalog.settings
    if host != "top":
        raise ValueError("Acquisition runs on top; preview and save are available on book.")
    if automatic and (settings["mode"] != "automatic" or settings["host"] != host):
        return
    item = catalog.item(key)
    existing = catalog.state["requests"].get(key, {})
    if existing.get("status") in ("queued", "checking transfer", "downloading", "downloaded"):
        return
    if catalog.owned(item, catalog.library()):
        raise ValueError("This release is already represented in your library.")
    if not item.get("resolved"):
        item = catalog.resolve(key)
    if any(any(c in str(value) for c in "\t\r\n") for value in
           [item["artist"], item["album"]] + [t["title"] for t in item["tracks"]]):
        raise ValueError("Release metadata contains unsupported control characters.")
    if not item.get("resolved") or not item["tracks"]:
        raise ValueError("A complete tracklist is required before acquisition.")
    recent = [r for r in catalog.state["requests"].values() if r.get("when", 0) > time.time() - 7 * 86400 and r.get("status") not in ("review", "failed")]
    if automatic and len(recent) >= settings["weekly"]:
        raise DeferredAcquisition("Weekly automatic acquisition limit reached.")
    root = Path(root)
    if not root.is_dir():
        raise DeferredAcquisition("Library storage is unavailable.")
    slsk = slsk or pipeline()
    meta = Path(slsk.DUMP_DIR)
    meta.mkdir(parents=True, exist_ok=True)
    with (meta / "soulseek-missing.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise DeferredAcquisition("Acquisition pipeline is busy; try again later.") from None
        api_key = Path(slsk.DEFAULT_KEY_FILE).read_text().strip()
        base = slsk.DEFAULT_HOST
        state_path = str(meta / "soulseek-state.tsv")
        state = slsk.load_state(state_path)
        # The legacy pipeline and this UI share receipts and a lock.
        wanted = {trackmatch.fold(t["artist"]) + "\0" + trackmatch.fold(t["title"]) for t in item["tracks"]}
        if any(trackmatch.fold(r.get("artists", "")) + "\0" + trackmatch.fold(r.get("title", "")) in wanted
               and r.get("status") == "queued" for r in state.values()):
            raise ValueError("Tracks from this release are already queued in the acquisition pipeline.")
        result = slsk.http("POST", base + "/api/v0/searches", api_key,
                           {"searchText": item["artist"] + " " + item["album"]})
        sid = result.get("id") if isinstance(result, dict) else result
        if not sid:
            raise ValueError("Search returned no identifier.")
        search = base + "/api/v0/searches/" + urllib.parse.quote(str(sid), safe="")
        deadline = time.monotonic() + 100
        while time.monotonic() < deadline:
            if stop.wait(2):
                return
            result = slsk.http("GET", search, api_key)
            if "Completed" in result.get("state", ""):
                break
        else:
            raise ValueError("Search timed out; nothing queued.")
        user, files = complete_candidate(item, slsk.http("GET", search + "/responses", api_key), settings["quality"])
        size = sum(int(f["size"]) for f in files)
        used = sum(r.get("bytes", 0) for r in recent)
        if used + size > float(settings["budget"]) * 1024**3:
            raise DeferredAcquisition("Weekly acquisition storage budget reached.")
        if shutil.disk_usage(root).free < size + 1024**3:
            raise DeferredAcquisition("Insufficient library space (1 GiB reserve required).")
        if stop.is_set() or catalog.owned(item, catalog.library()):
            return
        # Persist before POST: an uncertain timeout must never trigger an automatic duplicate.
        receipt = {"status": "checking transfer", "when": time.time(), "bytes": size, "user": user,
                   "files": [f["filename"] for f in files], "detail": ""}
        catalog.state["requests"][key] = receipt
        catalog.save()
        for track, f in zip(item["tracks"], files):
            record = {"artists": track["artist"], "title": track["title"], "album_artist": item["artist"],
                      "album": item["album"], "year": item["year"], "album_ref": "",
                      "status": "queued", "user": user, "filename": f["filename"], "when": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            state[slsk._state_key(record)] = record
        slsk.save_state(state_path, state)
        try:
            slsk.http("POST", base + "/api/v0/transfers/downloads/" + urllib.parse.quote(user, safe=""), api_key,
                      [{"filename": f["filename"], "size": f["size"]} for f in files])
        except Exception:
            receipt["detail"] = "Transfer outcome uncertain; inspect downloads before retrying."
            catalog.save()
            raise
        receipt["status"] = "queued"
        catalog.save()


def reconcile(catalog, slsk=None):
    pending = [r for r in catalog.state["requests"].values() if r.get("files") and r["status"] in
               ("queued", "checking transfer", "downloading", "downloaded")]
    if not pending:
        return
    slsk = slsk or pipeline()
    api_key = Path(slsk.DEFAULT_KEY_FILE).read_text().strip()
    transfers = slsk.http("GET", slsk.DEFAULT_HOST + "/api/v0/transfers/downloads", api_key)
    # iter_transfers is the importer pipeline's authoritative slskd shape reader.
    by_file = {}
    for f in slsk.iter_transfers(transfers):
        by_file[(f.get("username"), f.get("filename"))] = f
    for receipt in pending:
        found = [by_file.get((receipt["user"], f)) for f in receipt["files"]]
        if not all(found):
            continue
        if any(slsk.transfer_failed(f) for f in found):
            receipt["status"] = "checking transfer"
            receipt["detail"] = "A transfer failed; inspect downloads. No automatic retry."
        elif all("Succeeded" in f.get("state", "") for f in found):
            receipt["status"] = "downloaded"
            receipt["detail"] = "Waiting for library import"
        elif any("InProgress" in f.get("state", "") for f in found):
            receipt["status"] = "downloading"
            receipt["detail"] = ""
    catalog.save()

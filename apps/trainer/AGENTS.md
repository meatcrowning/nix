# MOSS Trainer

Standalone native QtWidgets client on top and book; CUDA stays on top. Follow
`apps/AGENTS.md` and `docs/DESIGN.md`. No automatic captioning. Datasets remain
untouched: run-local image symlinks, copied caption text, and caches live under
the chosen output directory. Missing captions use the optional fallback text.

`core.py` owns manifests and sd-scripts arguments. `setup_engine.py` installs a
pinned checkout and separate CUDA venv in `~/.local/share/moss-trainer/engine`;
never install training dependencies into ComfyUI. `worker.py` subclasses the
upstream trainer only for step-boundary controls, progress and checkpoint
publication. Upstream owns optimization, caching, model loading and sampling.
Update REVISION only after checking callback signatures and argument parsing.

`service.py` owns workers in the on-demand `moss-trainer-controller.service`
on top. The private mode-0600 Unix socket is reached by `moss-trainer --rpc`
over SSH (`top`, via LAN or Tailscale); no TCP API is exposed. `remote.py`
uses the same controller locally on top. GUI closure/network loss detaches;
only explicit Save and stop ends a run. The service owns logs and worker stdin,
so the worker's existing EOF save-and-stop rule still applies to controller loss.
Do not restart the controller during training. Old pre-controller workers remain
under their original window's control; new starts/resumes refuse while one exists.
Saved runs can be opened by absolute top path, without migration.

Book uploads use rsync into unique top-local staging folders. Failed transfers
retain their id for retry; successful submission seals that dataset against reuse.
Run manifests still reference top-local images, never a remote mount. Samples
are cached on book; LoRA downloads are explicit and exclude optimizer state.
The GUI never owns the GPU lease, and all starts/control requests are serialized
by the controller. Request receipts prevent replayed submissions; generation ids
reject controls aimed at an older job. Neither status nor inspect writes a run.

Pause keeps GPU memory and the renewable exclusive warden lease. Save-and-stop
finishes the current step (or sampling batch), saves LoRA plus optimizer state,
then exits and releases the lease. Worker pipe EOF also requests save-and-stop.
Engine preparation has no trained checkpoint yet. Controls requested during it
are serviced at the first completed step. Checkpoints publish `latest.json`
only after both state and weights are complete; failed saves retain the prior
checkpoint. Resuming restores optimizer/weights/RNG with constant learning rate
and restarts dataset traversal; it is not an exact sample-order replay.
Periodic intervals use completed optimizer steps, with epochs counting one pass
through the dataset (batch size and repeats are both one). Training length
selects either steps or epochs; core.py resolves the step budget from the
frozen dataset count, including for resume. Old manifests default to steps.
Alpha defaults to 1 for new settings and is independent of rank. Run manifests
without alpha retain the historical alpha=rank behavior when opened/resumed.

Sampling changes travel through worker stdin and are accepted at completed
steps. Sample now applies the current prompts and requests one batch at the next
completed step, bypassing the enable switch and interval without changing them.
While paused it waits for resume; repeated pending requests coalesce.
Disabling skips future automatic batches, never cancels an active sampler. Accepted
sampling settings persist in run-local sampling.json; prompts.json is derived.
New prompt text temporarily loads the encoder, preserving RNG and H2D streamed
blocks; failures skip sampling, while failure to restore training weights is
fatal. Baselines use multiplier zero with restoration in finally, at startup
and before sampling changed prompts. Existing workers cannot gain these controls
without restarting: never interrupt a user's run to apply source updates.
Random sample seeds derive from a per-run seed frozen in run.json; explicit
seeds belong to individual sample rows. The count is the total batch size,
with one prompt per row; duplicate and multiline prompts are preserved. Baselines use
the same seeds. Changing live sample seeds never changes the training RNG.
GUI values autosave; File menu presets contain Settings only, not checkpoints.

Verify without live GPU work or windows:
- `python3 apps/trainer/tools/test_sampling.py`
- `python3 apps/trainer/tools/test_core.py`
- `python3 apps/trainer/tools/test_service.py`
- `python3 apps/trainer/tools/test_client.py` (PySide6 imports only, no window)
- `tools/test_remote_ui.py` with the same offscreen/session guard as `test_ui.py`;
  unset the platform theme and select Fusion for headless Fedora Qt menu tests.
- `python3 apps/trainer/tools/test_worker.py`
- `CUDA_VISIBLE_DEVICES= ENGINE/.venv/bin/python tools/test_backend.py` from
  this directory, with the package library environment: real upstream dataset
  loading on synthetic images, no model loading or GPU work.
- `python3 tools/ai-warden-test.py`
- `worker.py RUN --check` in the engine venv validates real backend imports and
  argument/dataset-schema parsing without loading models or reserving GPU memory.
- GUI harness: `tools/test_ui.py` with the package interpreter, offscreen and
  the session guard; it stubs all worker launch paths and uses temporary config.

`moss-trainer --setup-engine` submits backend setup on top without opening a
window; progress remains available in the client. Engine setup takes an exclusive file lock; training holds a shared lock
so a second app cannot replace dependencies during a run.

The user performs real training and visual checks. Never use their dataset or
start a training run merely to test the app.

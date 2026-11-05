# MOSS Trainer

Standalone native QtWidgets app, packaged on top only (CUDA). Follow
`apps/AGENTS.md` and `docs/DESIGN.md`. No automatic captioning. Datasets remain
untouched: run-local image symlinks, copied caption text, and caches live under
the chosen output directory. Missing captions use the optional fallback text.

`core.py` owns manifests and sd-scripts arguments. `setup_engine.py` installs a
pinned checkout and separate CUDA venv in `~/.local/share/moss-trainer/engine`;
never install training dependencies into ComfyUI. `worker.py` subclasses the
upstream trainer only for step-boundary controls, progress and checkpoint
publication. Upstream owns optimization, caching, model loading and sampling.
Update REVISION only after checking callback signatures and argument parsing.

Pause keeps GPU memory and the renewable exclusive warden lease. Save-and-stop
finishes the current step (or sampling batch), saves LoRA plus optimizer state,
then exits and releases the lease. GUI pipe EOF also requests save-and-stop.
Engine preparation has no trained checkpoint yet. Controls requested during it
are serviced at the first completed step. Checkpoints publish `latest.json`
only after both state and weights are complete; failed saves retain the prior
checkpoint. Resuming restores optimizer/weights/RNG with constant learning rate
and restarts dataset traversal; it is not an exact sample-order replay.
Periodic intervals use completed optimizer steps, with epochs counting one pass
through the dataset (batch size and repeats are both one). Training length
selects either steps or epochs; core.py resolves the step budget from the
frozen dataset count, including for resume. Old manifests default to steps.

Verify without live GPU work or windows:
- `python3 apps/trainer/tools/test_core.py`
- `python3 apps/trainer/tools/test_worker.py`
- `CUDA_VISIBLE_DEVICES= ENGINE/.venv/bin/python tools/test_backend.py` from
  this directory, with the package library environment: real upstream dataset
  loading on synthetic images, no model loading or GPU work.
- `python3 tools/ai-warden-test.py`
- `worker.py RUN --check` in the engine venv validates real backend imports and
  argument/dataset-schema parsing without loading models or reserving GPU memory.
- GUI harness: `tools/test_ui.py` with the package interpreter, offscreen and
  the session guard; it stubs all worker launch paths and uses temporary config.

`moss-trainer --setup-engine` installs/repairs the backend without opening a
window. Engine setup takes an exclusive file lock; training holds a shared lock
so a second app cannot replace dependencies during a run.

The user performs real training and visual checks. Never use their dataset or
start a training run merely to test the app.

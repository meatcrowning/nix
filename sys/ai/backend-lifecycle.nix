{ lib, ... }:

{
  # Ollama remains a normal system unit (and can still be started manually),
  # but it no longer comes up merely because top booted. Chatter's renewable
  # ai-warden client lease starts it on the first window and stops it after the
  # last one closes; ComfyUI already has no WantedBy and uses the same contract.
  systemd.services.ollama.wantedBy = lib.mkForce [ ];
}

#!/usr/bin/env python3
"""Selector labels are presentation only; Ollama ids stay exact."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("ORACLE_SELFTEST", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main as oracle

labels = oracle.MODEL_LABELS
assert labels["qwen3.6:35b-a3b"].endswith("qwen3.6:35b-a3b")
assert labels["hf.co/bartowski/Qwen_Qwen3.5-9B-GGUF:Q5_K_M"].endswith("qwen3.5-9b q5")
assert oracle.Ollama().modelLabel("unknown:latest") == "unknown:latest"
print("model labels: ok")

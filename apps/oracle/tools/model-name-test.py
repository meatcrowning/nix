#!/usr/bin/env python3
"""The assistant's friendly caption and model-name override are remembered."""
import os
import sys
import tempfile
from pathlib import Path

TMP = tempfile.TemporaryDirectory(prefix="chatter-model-name-")
os.environ["ORACLE_CONFIG"] = TMP.name

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / "pylib"))
sys.argv = [sys.argv[0], "--selftest"]

from PySide6.QtCore import QCoreApplication  # noqa: E402
import main as oracle                         # noqa: E402

app = QCoreApplication([])
fails = []


def check(name, condition):
    print(("ok   " if condition else "FAIL ") + name)
    if not condition:
        fails.append(name)


first = oracle.Ollama()
check("the friendly caption is the default", not first.showModelName)
check("the conversational name defaults to Sable", first.assistantName == "Sable")
check("the agent can rename itself persistently",
      first._set_assistant_name("Vesper").get("ok")
      and oracle.ASSISTANT_NAME_PATH.read_text(encoding="utf-8") == "Vesper\n"
      and oracle.Ollama().assistantName == "Vesper")
check("an invalid name is refused",
      "error" in first._set_assistant_name("x" * 25)
      and first.assistantName == "Vesper")
first.setShowModelName(True)
check("enabling model captions persists the setting",
      oracle.SHOW_MODEL_NAME_PATH.read_text(encoding="utf-8") == "1\n"
      and oracle.Ollama().showModelName)
first.setShowModelName(False)
check("disabling model captions restores the conversational name and persists",
      oracle.SHOW_MODEL_NAME_PATH.read_text(encoding="utf-8") == "0\n"
      and not oracle.Ollama().showModelName)

print("FAILED: " + ", ".join(fails) if fails else "OK")
sys.exit(1 if fails else 0)

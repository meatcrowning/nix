#!/usr/bin/env python3
"""Pure construction check for slsk's loopback-only endpoint seam."""

import os
from pathlib import Path
import sys
import tempfile

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

with tempfile.TemporaryDirectory(prefix="slsk-isolation-") as tmp:
    key = Path(tmp) / "key"
    key.write_text("fixture-key")
    os.environ["SLSK_API_URL"] = "http://127.0.0.1:1"
    os.environ["SLSK_API_KEY_FILE"] = str(key)
    import slskapi
    api = slskapi.SlskApi()
    assert api._base == "http://127.0.0.1:1"
    assert api._key == "fixture-key"
    try:
        slskapi.SlskApi(base="https://example.com")
    except ValueError:
        pass
    else:
        raise AssertionError("non-loopback endpoint was accepted")
print("slsk isolation: loopback fake accepted; remote rejected")

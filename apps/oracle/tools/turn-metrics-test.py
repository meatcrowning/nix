#!/usr/bin/env python3
"""Content-free telemetry contract; no Qt, model server or user state."""
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

with tempfile.TemporaryDirectory(prefix="chatter-metrics-test-") as tmp:
    path = Path(tmp) / "metrics.jsonl"
    os.environ["ORACLE_METRICS"] = str(path)
    from turnmetrics import TurnMetrics

    metrics = TurnMetrics(selftest=True)
    metrics.begin(model="test-model", kind="send", num_ctx=32768, warm=True,
                  history_messages=4, input_chars=19, attachments=1)
    metrics.request(1234)
    metrics.first_output()
    metrics.tool_round(["read_file", "read_file", "run_python"])
    metrics.tools_finished()
    metrics.server_done({"prompt_eval_count": 100,
                         "prompt_eval_duration": 2_000_000,
                         "eval_count": 20, "eval_duration": 4_000_000,
                         "load_duration": 5_000_000})
    metrics.finish("done")

    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["model"] == "test-model"
    assert row["requests"] == 1 and row["request_bytes"] == 1234
    assert row["tool_rounds"] == 1 and row["tool_calls"] == 3
    assert row["tool_names"] == {"read_file": 2, "run_python": 1}
    assert row["prompt_tokens"] == 100 and row["prompt_ms"] == 2.0
    assert row["decode_tokens"] == 20 and row["decode_ms"] == 4.0
    assert row["load_ms"] == 5.0 and row["status"] == "done"
    forbidden = {"prompt", "reply", "content", "arguments", "results"}
    assert forbidden.isdisjoint(row)
    print("OK", json.dumps(row, sort_keys=True))

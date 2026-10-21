#!/usr/bin/env python3
"""Check the built ly setup wrapper without a login or graphical session."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

wrapper = Path(sys.argv[1])
probe = [sys.executable, "-c", r"""
import sys
assert sys.argv[1:] == ['two words', '$literal;value']
assert sys.stdin.read() == 'terminal input\n'
print('terminal output')
print('terminal error', file=sys.stderr)
sys.exit(23)
""", "two words", "$literal;value"]
environment = dict(os.environ, XDG_SESSION_TYPE="tty")
result = subprocess.run([str(wrapper), *probe], env=environment,
                        input="terminal input\n", text=True, capture_output=True)
assert (result.returncode, result.stdout, result.stderr) == (
    23, "terminal output\n", "terminal error\n"), result
print("PASS: TTY preserves stdin, stdout, stderr, arguments and exit status")

# Replace only the graphical delegate with a harmless argument reporter.
# Never invoke the real wrapper: it imports environment and starts targets.
source = wrapper.read_text()
delegate = source.rstrip().splitlines()[-1]
assert delegate.startswith("exec /nix/store/") and delegate.endswith(' "$@"')
with tempfile.TemporaryDirectory(prefix="ly-session-test-") as directory:
    stub = Path(directory) / "setup"
    stub.write_text(source.replace(delegate, 'printf "graphical:%s\\n" "$@"'))
    stub.chmod(0o700)
    for session in ("x11", "wayland", ""):
        result = subprocess.run([str(stub), "two words", "$literal;value"],
                                env=dict(environment, XDG_SESSION_TYPE=session),
                                text=True, capture_output=True, check=True)
        assert result.stdout == "graphical:two words\ngraphical:$literal;value\n"
print("PASS: graphical and unspecified sessions retain the graphical delegate")

#!/usr/bin/python2.7
"""Forward an original-shell launch to the host application environment."""
from __future__ import print_function

import json
import os
import socket
import sys

request = {
    "argv": sys.argv[1:],
    "command": os.path.basename(sys.argv[0]),
    "cwd": os.getcwd(),
    "startup_id": os.environ.get("DESKTOP_STARTUP_ID", ""),
}
try:
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(10)
    connection.connect(os.environ["UNITY_QUANTAL_HOST_SOCKET"])
    connection.sendall((json.dumps(request) + "\n").encode("utf-8"))
    response = json.loads(connection.makefile("r").readline())
    if response.get("error"):
        print(response["error"], file=sys.stderr)
        sys.exit(1)
except (IOError, ValueError, KeyError) as error:
    print("Unity application launch failed: " + str(error), file=sys.stderr)
    sys.exit(1)

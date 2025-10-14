#!/usr/bin/env python3

# ssh into the runner and use `nc localhost 4444` for bash

import os
import socket
import subprocess

print(f"PATH={os.getenv('PATH', '')}", flush=True)
print("Welcome home!", flush=True)

s = socket.socket()
s.bind(("0.0.0.0", 4444))
s.listen(1)
conn, _ = s.accept()
os.dup2(conn.fileno(), 0)
os.dup2(conn.fileno(), 1)
os.dup2(conn.fileno(), 2)
subprocess.call(["bash", "--noprofile", "--norc", "-i"])

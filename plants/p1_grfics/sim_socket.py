"""Eval only: one request to the GRFICS simulator socket. Runs INSIDE the simulation container:
    docker exec -i simulation python3 - '<json request>'   (this file on stdin)
Prints the JSON reply."""
import json
import socket
import sys

s = socket.create_connection(("127.0.0.1", 55555), timeout=3)
s.sendall(sys.argv[1].encode())
buf = b""
while True:
    chunk = s.recv(65536)
    if not chunk:
        break
    buf += chunk
    try:
        json.loads(buf)
        break
    except ValueError:
        continue
s.close()
print(buf.decode())

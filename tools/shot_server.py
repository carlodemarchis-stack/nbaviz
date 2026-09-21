#!/usr/bin/env python3
"""Receives packed shot charts from the browser, via URL rather than fetch.

    python3 tools/shot_server.py [--port 8809]

Why this shape: stats.nba.com only answers a page whose origin is nba.com, and Chrome's
Local Network Access blocks that page from fetch/XHR/sendBeacon-ing to localhost. But a
top-level NAVIGATION to localhost is allowed, so the nba.com tab opens one popup window
and repeatedly points it at

    http://localhost:8809/shot?id=<espnId>&m=<made>&x=<missed>

Each shot is 2 characters, so a player is ~3 KB -- comfortably inside the 64 KB request
line limit. Nothing has to travel through the model's context.
"""
import argparse
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "scratch", "shots")
SAFE_ID = re.compile(r"^[0-9]{1,12}$")
SAFE_PACK = re.compile(r"^[0-9A-Za-z]*$")


class H(BaseHTTPRequestHandler):
    # http.server's default 65536 request-line cap is what bounds a player's payload.
    def log_message(self, *a):
        pass

    def _ok(self, body, ctype="text/html; charset=utf-8"):
        b = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/shot":
            pid = (q.get("id") or [""])[0]
            made = (q.get("m") or [""])[0]
            miss = (q.get("x") or [""])[0]
            if not SAFE_ID.match(pid) or not SAFE_PACK.match(made) or not SAFE_PACK.match(miss):
                self._ok("bad")
                return
            os.makedirs(OUT, exist_ok=True)
            with open(os.path.join(OUT, f"{pid}.json"), "w") as f:
                json.dump({"m": made, "x": miss}, f)
            n = len([f for f in os.listdir(OUT) if f.endswith(".json")])
            print(f"\r  saved {n} players "
                  f"(last {pid}: {len(made)//2} made, {len(miss)//2} missed)   ",
                  end="", flush=True)
            self._ok(f"ok {pid}")
        elif u.path == "/count":
            os.makedirs(OUT, exist_ok=True)
            n = sorted(f[:-5] for f in os.listdir(OUT) if f.endswith(".json"))
            self._ok(json.dumps({"n": len(n), "ids": n}), "application/json")
        else:
            self._ok("shot sink ready")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8809)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    print(f"shot sink on http://localhost:{a.port}  -> scratch/shots/")
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()

#!/usr/bin/env python3
"""Local half of the browser-proxied harvester.

    python3 tools/harvest_server.py [--stage league|rosters|players] [--port 8807]

Hands a job list to a browser sitting on nba.com and writes back whatever it posts.
Chrome treats http://localhost as a trustworthy origin, so an https nba.com page is
allowed to talk to it -- no mixed-content block, no proxy, no Apify credits.

Already-downloaded jobs are skipped, so re-running resumes rather than refetching.
"""
import argparse
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "..", "scratch", "raw")
sys.path.insert(0, HERE)
import jobs as J  # noqa: E402

SAFE = re.compile(r"^[A-Za-z0-9_.-]+$")
STATE = {"jobs": [], "done": set(), "failed": {}}


def raw_path(name):
    if not SAFE.match(name):
        raise ValueError(f"unsafe job name: {name!r}")
    return os.path.join(RAW, name + ".json")


def pending():
    return [j for j in STATE["jobs"] if not os.path.exists(raw_path(j["name"]))]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # the progress line below is the only output worth reading

    def _send(self, code, body=b"", ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        # Chrome's Private Network Access check: an https page reaching a local
        # server is preflighted and refused without this.
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204)

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            with open(os.path.join(HERE, "harvest.html"), "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        elif self.path.startswith("/jobs"):
            p = pending()
            self._send(200, json.dumps(p).encode())
        elif self.path.startswith("/status"):
            p = pending()
            self._send(200, json.dumps({
                "total": len(STATE["jobs"]), "pending": len(p),
                "done": len(STATE["jobs"]) - len(p), "failed": STATE["failed"],
            }).encode())
        else:
            self._send(404, b'{"error":"no"}')

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        name = self.path.rsplit("/", 1)[-1].split("?")[0]
        try:
            path = raw_path(name)
        except ValueError as e:
            self._send(400, json.dumps({"error": str(e)}).encode())
            return
        try:
            payload = json.loads(body)
        except Exception as e:
            STATE["failed"][name] = f"bad json: {e}"
            self._send(400, b'{"error":"bad json"}')
            return
        if isinstance(payload, dict) and payload.get("__error__"):
            STATE["failed"][name] = str(payload["__error__"])[:200]
            self._send(200, b'{"ok":false}')
        else:
            os.makedirs(RAW, exist_ok=True)
            with open(path, "wb") as f:
                f.write(body)
            STATE["done"].add(name)
            self._send(200, b'{"ok":true}')
        left = len(pending())
        print(f"\r  saved {len(STATE['jobs']) - left}/{len(STATE['jobs'])}"
              f"  failed {len(STATE['failed'])}   ", end="", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="league",
                    choices=["league", "rosters", "players"])
    ap.add_argument("--port", type=int, default=8807)
    ap.add_argument("--ids", default="",
                    help="comma-separated player ids, for --stage players")
    a = ap.parse_args()

    if a.stage == "league":
        STATE["jobs"] = J.league_jobs()
    elif a.stage == "rosters":
        STATE["jobs"] = J.roster_jobs()
    else:
        ids = [x for x in a.ids.split(",") if x.strip()]
        if not ids:
            sys.exit("--stage players needs --ids")
        STATE["jobs"] = J.player_jobs(ids)

    os.makedirs(RAW, exist_ok=True)
    print(f"stage {a.stage}: {len(STATE['jobs'])} jobs, {len(pending())} pending")
    print(f"listening on http://localhost:{a.port}  (ctrl-c to stop)")
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()


if __name__ == "__main__":
    main()

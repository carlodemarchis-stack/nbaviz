#!/usr/bin/env python3
"""Integrity checks for the built data. Run after ANY refetch.

    python3 tools/validate.py 2025-26

Exits non-zero on failure so it can gate a rebuild. Every check here exists because
something actually went wrong once:
  * records vs official standings  -- catches postponed-shell duplicates and the
    NBA Cup final wrongly counting
  * box score points vs final score -- catches dropped players (an `active:false`
    filter once deleted real players from 22 games)
  * season team assignment          -- catches ESPN's current-roster leakage, which
    put Jaylen Brown on Philadelphia for his Boston season
"""
import gzip
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
IMG = os.path.join(HERE, "..", "img")
FAILS = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{('  -- ' + detail) if detail else ''}")
    if not ok:
        FAILS.append(name)


def espn_year(label):
    return int(label.split("-")[0]) + 1


def main(label):
    print(f"validating {label}")
    teams = json.load(open(os.path.join(DATA, "teams.json")))
    check("30 teams", len(teams) == 30, f"{len(teams)}")

    crests = [ab for ab in teams if not os.path.exists(os.path.join(IMG, "crest", ab + ".svg"))]
    check("a crest per team", not crests, f"missing {crests}" if crests else "30/30")

    sched = json.load(open(os.path.join(DATA, f"schedule-{label}.json")))
    rec = {ab: (sum(1 for g in v if g.get("counts", True) and g["res"] == "W"),
                sum(1 for g in v if g.get("counts", True) and g["res"] == "L"))
           for ab, v in sched.items()}
    played = sum(w + l for w, l in rec.values())
    total = {ab: sum(1 for g in v if g.get("counts", True)) for ab, v in sched.items()}
    complete = played and all(w + l == 82 for w, l in rec.values())

    if complete:
        check("every team at 82 counting games", all(n == 82 for n in total.values()),
              f"{sorted(set(total.values()))}")
        # Only a finished season can be reconciled against final standings.
        url = ("https://site.web.api.espn.com/apis/v2/sports/basketball/nba/standings"
               f"?season={espn_year(label)}")
        d = json.loads(urllib.request.urlopen(url, timeout=40).read())
        by_espn = {v["espnId"]: k for k, v in teams.items()}
        off = {}

        def walk(n):
            for e in n.get("standings", {}).get("entries", []):
                ab = by_espn.get(e["team"]["id"])
                st = {s["name"]: s.get("value", s.get("displayValue")) for s in e["stats"]}
                if ab and st.get("wins") is not None:
                    off[ab] = (int(float(st["wins"])), int(float(st["losses"])))
            for c in n.get("children", []):
                walk(c)
        walk(d)
        wrong = {ab: (rec[ab], off.get(ab)) for ab in rec if off.get(ab) != rec[ab]}
        check("records match official standings", not wrong,
              f"{len(wrong)} wrong: {list(wrong.items())[:3]}" if wrong else "30/30")
    else:
        check("season not yet played -- standings check skipped", True,
              f"{played} team-games played")

    # Box scores: the strongest available check, since it reconciles two independent
    # payloads (schedule score vs the sum of that game's player lines).
    bp = os.path.join(DATA, f"boxlines-{label}.json.gz")
    if os.path.exists(bp):
        box = json.load(gzip.open(bp, "rt"))
        want = {}
        for ab, gs in sched.items():
            for g in gs:
                if g["res"]:
                    want.setdefault(g["id"], {})[ab] = g["us"]
        bad, checked = [], 0
        for gid, blocks in box.items():
            for ab, rows in blocks.items():
                exp = want.get(gid, {}).get(ab)
                if exp is None:
                    continue
                checked += 1
                got = sum(r[2] for r in rows)
                if got != exp:
                    bad.append((gid, ab, got, exp))
        # KNOWN UPSTREAM GAP, verified 2026-09-20: in 7 Chicago games ESPN's own
        # payload omits one player's line outright -- the listed players total 230
        # of the required 240 minutes, and ESPN's id-less row for that player
        # (Lachlan Olbrich, a two-way it has no athlete id for) carries "--" minutes
        # and no stats. The data is simply absent, not mis-parsed.
        # The towers are UNAFFECTED: they use the schedule's final scores, which are
        # correct and independently reconciled against the official standings above.
        known = {("401810150", "CHI"), ("401810372", "CHI"), ("401810547", "CHI"),
                 ("401810560", "CHI"), ("401810577", "CHI"), ("401810633", "CHI"),
                 ("401810760", "CHI")}
        unexpected = [b for b in bad if (b[0], b[1]) not in known]
        check("box score points reconcile to final scores", not unexpected,
              f"{checked} team-games checked"
              + (f", {len(bad)} known-incomplete tolerated" if bad else "")
              if not unexpected else f"{len(unexpected)} NEW mismatches: {unexpected[:3]}")
        stale = known - {(b[0], b[1]) for b in bad}
        if stale:
            print(f"        note: {len(stale)} known-incomplete game(s) now reconcile "
                  f"-- ESPN backfilled them, drop from the allowlist")
        missing = [g for g in want if g not in box]
        check("a box score for every played game", not missing,
              f"{len(box)} games" if not missing else f"{len(missing)} missing")

    # Season-accurate teams, derived from who actually appeared in box scores.
    pf = os.path.join(DATA, f"players-{label}.json")
    if os.path.exists(pf) and os.path.exists(bp):
        players = json.load(open(pf))
        seen = set()
        for blocks in box.values():
            for rows in blocks.values():
                seen.update(r[0] for r in rows)
        scored = [p for p in players.values() if (p["rs"] or {}).get("points")]
        orphan = [p["name"] for p in scored if p["id"] not in seen]
        check("every scoring player appears in a box score", not orphan,
              f"{len(scored)} players" if not orphan else f"{len(orphan)}: {orphan[:4]}")

    print()
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED: {FAILS}")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2025-26")

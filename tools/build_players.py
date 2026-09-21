#!/usr/bin/env python3
"""Join stats + box scores + NBA ids into the player deck.

    python3 tools/build_players.py 2025-26

Three things happen here that cannot happen earlier:

1. **Season-accurate teams.** ESPN's rosters are always CURRENT, so they cannot say who
   played where last season. Team is derived instead from the box scores -- whoever a
   player actually appeared for, counted by game. This also yields mid-season trades for
   free, which is good card material rather than an inconvenience.
2. **NBA ids**, matched by name, which unlock the official 1040x760 headshots.
3. **Proper spelling.** ESPN flattens accents ("Luka Doncic", "Nikola Jokic"); the NBA
   index keeps them ("Luka Dončić", "Nikola Jokić"). The cards use the NBA's spelling.

Writes data/deck-players-<label>.json.
"""
import gzip
import json
import os
import re
import sys
import unicodedata
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")

SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?")


def norm(s):
    """Fold to a comparable key: accents out, punctuation out, suffixes out."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("&", "and")
    s = re.sub(r"[.'`’-]", " ", s)
    s = SUFFIX.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def main(label):
    players = json.load(open(os.path.join(DATA, f"players-{label}.json")))
    box = json.load(gzip.open(os.path.join(DATA, f"boxlines-{label}.json.gz"), "rt"))
    nba = json.load(open(os.path.join(DATA, "nba_index.json")))

    # --- 1. teams actually played for, from the box scores
    appear = {}
    for blocks in box.values():
        for ab, rows in blocks.items():
            for r in rows:
                appear.setdefault(r[0], Counter())[ab] += 1

    # --- 2. NBA id by normalised name
    by_norm = {}
    for nid, name in nba.items():
        by_norm.setdefault(norm(name), (nid, name))

    deck, unmatched, teamless = [], [], []
    for pid, p in players.items():
        rs = p.get("rs") or {}
        if not rs.get("points"):
            continue
        counts = appear.get(pid)
        if not counts:
            teamless.append(p["name"])
            continue
        order = counts.most_common()
        hit = by_norm.get(norm(p["name"]))
        if not hit:
            unmatched.append(p["name"])
        nid, nba_name = hit if hit else (None, None)

        deck.append({
            "id": pid, "nbaId": nid,
            "name": nba_name or p["name"],          # NBA spelling keeps the accents
            "short": p.get("short"), "last": p.get("last"),
            "team": order[0][0],
            "teams": [{"t": t, "g": g} for t, g in order],
            "pos": p.get("pos"), "age": p.get("age"), "debut": p.get("debut"),
            "jersey": p.get("jersey"), "height": p.get("height"),
            "weight": p.get("weight"), "college": p.get("college"),
            "rs": rs, "po": p.get("po"),
        })

    deck.sort(key=lambda p: -p["rs"]["points"])
    for i, p in enumerate(deck, 1):
        p["rank"] = i

    traded = [p for p in deck if len(p["teams"]) > 1]
    print(f"  {len(deck)} players with points")
    print(f"  {len(traded)} played for more than one team "
          f"(eg {[p['name'] for p in traded[:3]]})")
    print(f"  {len(unmatched)} without an NBA id" +
          (f": {unmatched[:5]}" if unmatched else ""))
    if teamless:
        print(f"  {len(teamless)} scored but never appear in a box score: {teamless[:4]}")

    # The bug this whole module exists to prevent -- spot-check it loudly.
    for name, expect in (("Jaylen Brown", "BOS"), ("Kawhi Leonard", "LAC")):
        got = next((p["team"] for p in deck if p["name"] == name), None)
        flag = "ok" if got == expect else "WRONG"
        print(f"  {flag}: {name} 2025-26 team = {got} (expected {expect})")

    out = os.path.join(DATA, f"deck-players-{label}.json")
    with open(out, "w") as f:
        json.dump(deck, f, separators=(",", ":"), ensure_ascii=False)
    print(f"  wrote data/deck-players-{label}.json  "
          f"{os.path.getsize(out) / 1024:.0f} KB")

    print("  top 10: " + ", ".join(
        f"{p['name']} ({p['team']}) {int(p['rs']['points'])}" for p in deck[:10]))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2025-26")

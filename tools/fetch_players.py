#!/usr/bin/env python3
"""Player rosters and season stat lines, from ESPN.

    python3 tools/fetch_players.py 2026        # the 2025-26 season

Two sources, joined on the ESPN athlete id:
  * /teams/{id}/roster       -- who is on which team, plus jersey/height/weight/college
  * /statistics/byathlete    -- every player's season line, 578 of them in 12 pages,
                                carrying per-game AND total columns

The deck is ordered by TOTAL POINTS, which is why the totals columns matter: it needs no
arbitrary games-played cutoff and it lets availability count for something.

Writes data/players-<label>.json.
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from fetch_espn import DATA, cached, season_label, write  # noqa: E402

SITE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
COMMON = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba"


def roster(espn_id, year):
    d = cached(f"espn_roster_{espn_id}_{year}",
               f"{SITE}/teams/{espn_id}/roster?season={year}")
    return d.get("athletes", [])


def byathlete_page(year, page, stype=2):
    return cached(
        f"espn_byathlete_{year}_{stype}_{page}",
        f"{COMMON}/statistics/byathlete?region=us&lang=en&contentorigin=espn"
        f"&season={year}&seasontype={stype}&limit=50&page={page}")


def collect_stats(year, stype=2):
    """Flatten byathlete into {athleteId: {stat: value}} across all pages."""
    first = byathlete_page(year, 1, stype)
    pages = first["pagination"]["pages"]
    # The top-level `categories` list names the columns; each athlete's `values`
    # align to it by index, so the names must come from here, not the athlete.
    names = {c["name"]: c["names"] for c in first["categories"]}

    with ThreadPoolExecutor(max_workers=4) as ex:
        rest = list(ex.map(lambda p: byathlete_page(year, p, stype),
                           range(2, pages + 1)))
    out = {}
    for d in [first] + rest:
        for a in d.get("athletes", []):
            flat = {}
            for cat in a.get("categories", []):
                for k, v in zip(names.get(cat["name"], []), cat.get("values", [])):
                    flat[k] = v
            out[a["athlete"]["id"]] = {"athlete": a["athlete"], "stats": flat}
    return out


def do(year):
    label = season_label(year)
    teams = json.load(open(os.path.join(DATA, "teams.json")))

    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ab: ex.submit(roster, t["espnId"], year) for ab, t in teams.items()}
        rosters = {ab: f.result() for ab, f in futs.items()}

    where = {}
    for ab, ath in rosters.items():
        for a in ath:
            where[a["id"]] = {
                "team": ab, "jersey": a.get("jersey"),
                "pos": (a.get("position") or {}).get("abbreviation"),
                "height": a.get("displayHeight"), "weight": a.get("displayWeight"),
                "college": (a.get("college") or {}).get("name"),
                "exp": (a.get("experience") or {}).get("years"),
            }

    rs = collect_stats(year, 2)
    po = collect_stats(year, 3)
    print(f"  rosters: {sum(len(v) for v in rosters.values())} entries across {len(rosters)} teams")
    print(f"  stat lines: {len(rs)} regular season, {len(po)} playoffs")

    players = {}
    for pid, row in rs.items():
        a, s = row["athlete"], row["stats"]
        w = where.get(pid, {})
        players[pid] = {
            "id": pid,
            "name": a.get("displayName"), "short": a.get("shortName"),
            "first": a.get("firstName"), "last": a.get("lastName"),
            "age": a.get("age"), "debut": a.get("debutYear"),
            "pos": (a.get("position") or {}).get("abbreviation") or w.get("pos"),
            "team": w.get("team"), "jersey": w.get("jersey"),
            "height": w.get("height"), "weight": w.get("weight"),
            "college": w.get("college"), "exp": w.get("exp"),
            "rs": s,
            "po": po.get(pid, {}).get("stats"),
        }

    noteam = [p["name"] for p in players.values() if not p["team"]]
    print(f"  {len(players)} players, {len(noteam)} without a team "
          f"(waived/two-way mid-season): {noteam[:4]}")

    ranked = sorted((p for p in players.values() if p["rs"].get("points")),
                    key=lambda p: -p["rs"]["points"])
    print("  top 5 by total points: " + ", ".join(
        f"{p['short']} {int(p['rs']['points'])}" for p in ranked[:5]))
    write(f"players-{label}.json", players)


if __name__ == "__main__":
    do(int(sys.argv[1]) if len(sys.argv) > 1 else 2026)

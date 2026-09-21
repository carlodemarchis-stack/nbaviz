#!/usr/bin/env python3
"""Derive everything the cards render, into one compact payload.

    python3 tools/build_cards.py 2025-26

Reads data/{teams,schedule-*,playoffs-*,deck-players-*,boxlines-*}, writes
data/cards-<label>.json. Nothing here fetches: it is pure derivation, so it is cheap to
re-run while iterating on the card design.
"""
import gzip
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")

PLAYER_CARDS = 100         # the 100 biggest scorers — about 46% of all points in the league
BIG_NIGHTS = 100           # the 100 biggest individual scoring games, league-wide
ROUND_ORDER = ["1st Round", "Semifinals", "Conference Finals", "NBA Finals"]


def load(name, gz=False):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return None
    return json.load(gzip.open(p, "rt") if gz else open(p))


def r1(x):
    return round(x + 1e-9, 1)


def streaks(games):
    """Longest winning and losing runs over the counting games, in order."""
    best = {"W": 0, "L": 0}
    cur, kind = 0, None
    for g in games:
        if not g["res"]:
            continue
        if g["res"] == kind:
            cur += 1
        else:
            kind, cur = g["res"], 1
        best[kind] = max(best[kind], cur)
    return best


def round_name(note):
    """'East Semifinals - Game 3' -> 'Semifinals'; conference finals normalised."""
    if not note:
        return None
    head = note.split(" - ")[0].strip()
    if head.startswith("NBA Finals"):
        return "NBA Finals"
    for word in ("1st Round", "Semifinals", "Finals"):
        if head.endswith(word):
            return "Conference Finals" if word == "Finals" else word
    return head


def playoff_run(games):
    """Group a team's playoff games into series and describe how the run ended."""
    series, order = defaultdict(lambda: {"w": 0, "l": 0, "opp": None, "games": []}), []
    for g in games:
        rn = round_name(g.get("note"))
        if not rn:
            continue
        if rn not in series:
            order.append(rn)
        s = series[rn]
        s["opp"] = g["opp"]
        s["round"] = rn
        if g["res"] == "W":
            s["w"] += 1
        elif g["res"] == "L":
            s["l"] += 1
        s["games"].append({"res": g["res"], "us": g.get("us"), "them": g.get("them"),
                           "ha": g["ha"]})
    order.sort(key=lambda r: ROUND_ORDER.index(r) if r in ROUND_ORDER else 9)
    rounds = [series[r] for r in order]
    if not rounds:
        return None
    last = rounds[-1]
    won_last = last["w"] > last["l"]
    if last["round"] == "NBA Finals":
        outcome = "CHAMPIONS" if won_last else "Lost the NBA Finals"
    else:
        outcome = f"Lost the {last['round']}" if not won_last else f"Won the {last['round']}"
    return {"rounds": rounds, "outcome": outcome,
            "w": sum(r["w"] for r in rounds), "l": sum(r["l"] for r in rounds)}


def seeds(label):
    """Conference seed from ESPN's own standings, not recomputed from wins."""
    raw = os.path.join(HERE, "..", "scratch", "raw",
                       f"espn_standings_{int(label.split('-')[0]) + 1}.json")
    if not os.path.exists(raw):
        return {}
    teams = load("teams.json")
    by_espn = {v["espnId"]: k for k, v in teams.items()}
    out = {}

    def walk(n):
        for e in n.get("standings", {}).get("entries", []):
            ab = by_espn.get(e["team"]["id"])
            st = {s["name"]: s.get("value", s.get("displayValue")) for s in e["stats"]}
            if ab and st.get("playoffSeed") is not None:
                out[ab] = int(float(st["playoffSeed"]))
        for c in n.get("children", []):
            walk(c)
    walk(json.load(open(raw)))
    return out


def shots(label):
    """Packed shot grids harvested from stats.nba.com (see README: browser-only source).

    Each player: 4 chars per grid cell -- x, y, attempts, makes -- in base 62, on a
    32x32 grid of 16 court units (1.6 ft). A cell busier than 61 shots is emitted as
    several entries for the same cell, which the renderer sums.
    """
    d = os.path.join(HERE, "..", "scratch", "shots")
    if not os.path.isdir(d):
        return {}
    out = {}
    for f in os.listdir(d):
        if f.endswith(".json") and f[:-5].isdigit():
            out[f[:-5]] = json.load(open(os.path.join(d, f)))
    return out


def big_nights(sched, box, uncounted, deck, n=BIG_NIGHTS):
    """The n biggest individual scoring games of the season, league-wide.

    Deliberately NOT restricted to the carded players: a 40-point night counts the same
    whoever had it, and the leaderboard is more interesting for the names that turn up
    once. The pool is every player-game in the box scores, so it reaches all 578.

    Ties are broken by date, then by name, so the cut is stable across rebuilds -- it
    lands in the middle of a fat tie (28 games reached 41 points in 2025-26), and an
    unstable sort would reshuffle the tail every time the payload was rebuilt.
    """
    who = {p["id"]: p for p in deck}
    entry = {}                      # (team, gameId) -> that team's schedule row
    for ab, gs in sched.items():
        for g in gs:
            entry[(ab, g["id"])] = g

    perf = []
    for gid, blocks in box.items():
        if gid in uncounted:
            continue
        for ab, rows in blocks.items():
            g = entry.get((ab, gid))
            if not g:
                continue
            for r in rows:
                pid, mins, pts, fgm, fga, tpm, tpa, ftm, fta, reb, ast = r[:11]
                p = who.get(pid)
                if not p:
                    continue
                perf.append({
                    "pts": pts, "id": pid, "name": p["name"], "short": p["short"],
                    "team": ab, "opp": g["opp"], "h": 1 if g["ha"] == "H" else 0,
                    "w": 1 if g["res"] == "W" else 0,
                    "us": g["us"], "them": g["them"], "date": g["date"][:10],
                    "min": mins, "fgm": fgm, "fga": fga, "tpm": tpm, "tpa": tpa,
                    "ftm": ftm, "fta": fta, "reb": reb, "ast": ast,
                })
    perf.sort(key=lambda x: (-x["pts"], x["date"], x["name"]))
    top = perf[:n]
    if top:
        # How many nights league-wide tied the last man in. The cut lands mid-tie, so
        # the card says so rather than implying 41 points was a clean line.
        cut = top[-1]["pts"]
        top[-1] = dict(top[-1], tie=sum(1 for x in perf if x["pts"] == cut))
    return top


def main(label):
    teams = load("teams.json")
    sched = load(f"schedule-{label}.json")
    po = load(f"playoffs-{label}.json") or {}
    deck = load(f"deck-players-{label}.json") or []
    box = load(f"boxlines-{label}.json.gz", gz=True) or {}
    seed = seeds(label)
    shot = shots(label)

    # --- per player per team aggregates, straight from the box scores
    agg = defaultdict(lambda: defaultdict(lambda: [0] * 6))   # pid -> team -> tallies
    plog = defaultdict(list)                                  # pid -> [(date, pts, ...)]
    date_of, uncounted, gidx = {}, set(), {}
    for ab, gs in sched.items():
        for g in gs:
            date_of[g["id"]] = g["date"]
            # Where this game sits in the team's emitted games list, so a player's log
            # can point at it instead of carrying its own copy of opponent and score.
            if g.get("counts") is False:
                uncounted.add(g["id"])
    for ab, gs in sched.items():
        for i, g in enumerate(gs):
            gidx[(ab, g["id"])] = i

    # The NBA Cup Championship counts for NOBODY: not the team's record, and not a
    # player's season statistics either. Leaving it in gave 6 Knicks and Spurs one more
    # game in their log than their official games-played, so the per-game average line
    # was drawn against a game the average excludes.
    for gid, blocks in box.items():
        if gid in uncounted:
            continue
        for ab, rows in blocks.items():
            for r in rows:
                pid, mins, pts, fgm, fga, tpm, tpa, ftm, fta, reb, ast = r[:11]
                a = agg[pid][ab]
                a[0] += 1
                a[1] += pts
                a[2] += reb
                a[3] += ast
                a[4] += mins
                a[5] += tpm
                plog[pid].append((date_of.get(gid, ""), pts, reb, ast, tpm, mins,
                                  ab, gidx.get((ab, gid), -1)))

    # --- teams
    out_teams = []
    for ab, t in teams.items():
        games = sched.get(ab, [])
        counting = [g for g in games if g.get("counts", True)]
        done = [g for g in counting if g["res"]]
        w = sum(1 for g in done if g["res"] == "W")
        l = sum(1 for g in done if g["res"] == "L")
        pf = sum(g["us"] for g in done)
        pa = sum(g["them"] for g in done)
        home = [g for g in done if g["ha"] == "H"]
        away = [g for g in done if g["ha"] == "A"]
        margins = sorted(done, key=lambda g: g["us"] - g["them"])

        roster = []
        for pid, byteam in agg.items():
            if ab not in byteam:
                continue
            gp, pts, reb, ast, mins, tpm = byteam[ab]
            roster.append({"id": pid, "g": gp, "pts": pts,
                           "ppg": r1(pts / gp), "rpg": r1(reb / gp),
                           "apg": r1(ast / gp), "mpg": r1(mins / gp)})
        roster.sort(key=lambda r: -r["ppg"])

        out_teams.append({
            "abbr": ab, "name": t["name"], "city": t["city"], "nick": t["nick"],
            "conf": t["conf"], "div": t["div"], "seed": seed.get(ab),
            "primary": t["primary"], "secondary": t["secondary"],
            "w": w, "l": l, "pct": r1(100 * w / max(1, w + l)),
            "ppg": r1(pf / max(1, len(done))), "oppg": r1(pa / max(1, len(done))),
            "diff": r1((pf - pa) / max(1, len(done))),
            "home": f"{sum(1 for g in home if g['res'] == 'W')}-"
                    f"{sum(1 for g in home if g['res'] == 'L')}",
            "away": f"{sum(1 for g in away if g['res'] == 'W')}-"
                    f"{sum(1 for g in away if g['res'] == 'L')}",
            "streak": streaks(counting),
            "best": ({"opp": margins[-1]["opp"], "us": margins[-1]["us"],
                      "them": margins[-1]["them"], "date": margins[-1]["date"][:10]}
                     if margins else None),
            "worst": ({"opp": margins[0]["opp"], "us": margins[0]["us"],
                       "them": margins[0]["them"], "date": margins[0]["date"][:10]}
                      if margins else None),
            # The full 82 in order -- this is what draws the mini tower on the card
            # and the big towers on the towers page.
            "games": [{"g": g["g"], "opp": g["opp"], "ha": g["ha"], "res": g["res"],
                       "us": g.get("us"), "them": g.get("them"),
                       "date": g["date"][:10], "note": g.get("note"),
                       **({"counts": False} if g.get("counts") is False else {})}
                      for g in games],
            "po": playoff_run(po.get(ab, [])),
            "roster": roster[:18],
        })

    # Standings order: by record. With nothing played yet every team is 0-0, so fall
    # back to conference then city -- otherwise the order is an accident of the dict.
    if any(t["w"] or t["l"] for t in out_teams):
        out_teams.sort(key=lambda t: (-t["w"], t["l"]))
    else:
        out_teams.sort(key=lambda t: (t["conf"], t["div"], t["city"]))

    # --- players
    out_players = []
    for p in deck[:PLAYER_CARDS]:
        rs = p["rs"]
        log = sorted(plog.get(p["id"], []))
        pts_log = [x[1] for x in log]
        # The hover on the game chart wants opponent, result and final score. Rather
        # than copy those onto every game (7,000 of them), each entry points at the row
        # in that team's own games list, which the payload already ships:
        #   [index into p["teams"], index into that team's games, min, reb, ast]
        tix = {t["t"]: i for i, t in enumerate(p["teams"])}
        game_log = [[tix.get(x[6], 0), x[7], x[5], x[2], x[3]] for x in log]
        out_players.append({
            "rank": p["rank"], "id": p["id"], "nbaId": p["nbaId"],
            "name": p["name"], "short": p["short"], "team": p["team"],
            "teams": p["teams"], "pos": p["pos"], "age": p["age"],
            "jersey": p["jersey"], "height": p["height"], "weight": p["weight"],
            "college": p["college"], "debut": p["debut"],
            "gp": int(rs.get("gamesPlayed", 0)), "pts": int(rs["points"]),
            "ppg": r1(rs.get("avgPoints", 0)), "rpg": r1(rs.get("avgRebounds", 0)),
            "apg": r1(rs.get("avgAssists", 0)), "mpg": r1(rs.get("avgMinutes", 0)),
            "spg": r1(rs.get("avgSteals", 0)), "bpg": r1(rs.get("avgBlocks", 0)),
            "fg": r1(rs.get("fieldGoalPct", 0)), "tp": r1(rs.get("threePointFieldGoalPct", 0)),
            "ft": r1(rs.get("freeThrowPct", 0)),
            "fgm": int(rs.get("fieldGoalsMade", 0)), "fga": int(rs.get("fieldGoalsAttempted", 0)),
            "tpm": int(rs.get("threePointFieldGoalsMade", 0)),
            "tpa": int(rs.get("threePointFieldGoalsAttempted", 0)),
            "ftm": int(rs.get("freeThrowsMade", 0)), "fta": int(rs.get("freeThrowsAttempted", 0)),
            "reb": int(rs.get("rebounds", 0)), "ast": int(rs.get("assists", 0)),
            "dd": int(rs.get("doubleDouble", 0)), "td": int(rs.get("tripleDouble", 0)),
            "log": pts_log, "glog": game_log,
            "highs": {"pts": max(pts_log or [0]),
                      "reb": max((x[2] for x in log), default=0),
                      "ast": max((x[3] for x in log), default=0),
                      "tpm": max((x[4] for x in log), default=0)},
            "shots": shot.get(p["id"]),
            "po": ({"gp": int(p["po"].get("gamesPlayed", 0)),
                    "ppg": r1(p["po"].get("avgPoints", 0)),
                    "rpg": r1(p["po"].get("avgRebounds", 0)),
                    "apg": r1(p["po"].get("avgAssists", 0))}
                   if p.get("po") else None),
        })

    champ = next((t["abbr"] for t in out_teams if t["po"] and t["po"]["outcome"] == "CHAMPIONS"), None)

    # Team-card rosters reference players by id; ship a lookup so they can show names
    # without carrying a full player object per roster row. Whole pool, not just the
    # carded 60, because a roster row can be anyone who played.
    names = {p["id"]: [p["name"], p["pos"] or "", p["jersey"] or ""] for p in deck}

    nights = big_nights(sched, box, uncounted, deck)

    payload = {
        "season": label, "champion": champ,
        "teams": out_teams, "players": out_players, "names": names,
        "nights": nights,
        "counts": {"teams": len(out_teams), "players": len(out_players),
                   "playerPool": len(deck)},
    }
    p = os.path.join(DATA, f"cards-{label}.json")
    with open(p, "w") as f:
        json.dump(payload, f, separators=(",", ":"), ensure_ascii=False)

    print(f"  {len(out_teams)} team cards, {len(out_players)} player cards "
          f"(pool {len(deck)})")
    if nights:
        print(f"  big nights: {len(nights)}, {nights[0]['pts']} down to "
              f"{nights[-1]['pts']} ({nights[0]['name']} the best), "
              f"{len({x['id'] for x in nights})} different players")
    print(f"  champion: {champ}")
    top = out_teams[0]
    print(f"  best record: {top['name']} {top['w']}-{top['l']} "
          f"seed {top['seed']} diff {top['diff']:+}")
    bad = [t["abbr"] for t in out_teams if len([g for g in t["games"] if g["res"]]) == 0]
    if bad:
        print(f"  NOTE {len(bad)} teams with no played games (unplayed season)")
    nolog = [p["name"] for p in out_players if not p["log"]]
    if nolog:
        print(f"  WARNING {len(nolog)} player cards with an empty game log: {nolog[:4]}")
    # A player's game log must be exactly as long as his official games-played, or the
    # average line is drawn against a different set of games than the average. This
    # caught the NBA Cup final leaking into 6 players' logs.
    mismatch = [(p["name"], len(p["log"]), p["gp"]) for p in out_players
                if len(p["log"]) != p["gp"]]
    if mismatch:
        print(f"  WARNING {len(mismatch)} game logs != games played: {mismatch[:5]}")
    else:
        print(f"  ok: all {len(out_players)} game logs match games played")
    # The game chart's hover resolves each log entry through its [team, game] pointer.
    # If those ever drift the tooltip silently describes the wrong night, so check every
    # pointer lands on a game played on the same date as the log entry it came from.
    byab = {t["abbr"]: t for t in out_teams}
    drift = 0
    for x in out_players:
        dates = [d[0][:10] for d in sorted(plog.get(x["id"], []))]
        for d, (ti, gi, *_ ) in zip(dates, x["glog"]):
            ab = x["teams"][ti]["t"] if ti < len(x["teams"]) else None
            g = (byab.get(ab) or {"games": []})["games"]
            if not (0 <= gi < len(g)) or g[gi]["date"] != d:
                drift += 1
    print(f"  game-log pointers: {drift} wrong"
          if drift else
          f"  ok: all {sum(len(x['glog']) for x in out_players)} game-log pointers "
          f"resolve to the right night")

    withshots = sum(1 for x in out_players if x.get("shots"))
    print(f"  shot charts: {withshots}/{len(out_players)} player cards")
    # Cross-check the harvested totals against the independently-sourced ESPN line.
    mism = [(x["name"], x["shots"]["att"], x["fga"]) for x in out_players
            if x.get("shots") and x["shots"]["att"] != x["fga"]]
    if mism:
        print(f"  WARNING {len(mism)} shot totals disagree with ESPN FGA: {mism[:3]}")
    else:
        print(f"  ok: all {withshots} shot totals match ESPN's field-goal attempts")
    print(f"  wrote data/cards-{label}.json  {os.path.getsize(p) / 1024:.0f} KB")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2025-26")

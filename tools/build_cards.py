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
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")

PLAYER_CARDS = 100         # the 100 biggest scorers — about 46% of all points in the league
BIG_NIGHTS = 100           # the 100 biggest individual scoring PERFORMANCES, league-wide
                           # -- one row per player per game, so two players from the same
                           # game can both make it. NOT the highest-scoring games.
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


def best_night(log, sched):
    """Opponent and venue of the highest-scoring game in a player's log."""
    if not log:
        return {}
    top = max(log, key=lambda x: x[1])
    gs = sched.get(top[6]) or []
    gm = gs[top[7]] if 0 <= top[7] < len(gs) else None
    if not gm:
        return {}
    return {"opp": gm.get("opp"), "ha": gm.get("ha")}


def team_run_label(games):
    """How far a team got, phrased for a player card: 'LAL reached the West Semifinals'."""
    run = playoff_run(games)
    if not run:
        return None
    last = run["rounds"][-1]
    if run["outcome"] == "CHAMPIONS":
        return "won the title"
    # Every playoff team "reaches" the first round, so name the exit, not the arrival.
    if last["w"] > last["l"]:
        return "reached the " + last["round"]
    return ("lost the NBA Finals" if last["round"] == "NBA Finals"
            else "went out in the " + last["round"])


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


def jersey_of(p, worn):
    """The number he actually wore, from the box scores, for the team he played most for.

    ESPN's athlete record carries the number he wears NOW, and none at all for a player
    who is unsigned when it is fetched -- that left 10 of the 100 carded players with no
    number on the card. Falls back to the ESPN value, then to nothing.
    """
    byteam = worn.get(p["id"]) or {}
    for team in [p.get("team")] + [t["t"] for t in (p.get("teams") or [])]:
        if team and byteam.get(team):
            return byteam[team].most_common(1)[0][0]
    if byteam:
        pool = Counter()
        for c in byteam.values():
            pool += c
        return pool.most_common(1)[0][0]
    return p.get("jersey")


def main(label):
    teams = load("teams.json")
    sched = load(f"schedule-{label}.json")
    po = load(f"playoffs-{label}.json") or {}
    deck = load(f"deck-players-{label}.json") or []
    box = load(f"boxlines-{label}.json.gz", gz=True) or {}
    pobox = load(f"boxlines-po-{label}.json.gz", gz=True) or {}
    seed = seeds(label)
    shot = shots(label)

    # --- per player per team aggregates, straight from the box scores
    agg = defaultdict(lambda: defaultdict(lambda: [0] * 6))   # pid -> team -> tallies
    worn = defaultdict(lambda: defaultdict(Counter))          # pid -> team -> jersey tally
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
                if len(r) > 16 and r[16]:
                    worn[pid][ab][r[16]] += 1
                a = agg[pid][ab]
                a[0] += 1
                a[1] += pts
                a[2] += reb
                a[3] += ast
                a[4] += mins
                a[5] += tpm
                # How many of points / rebounds / assists / steals / blocks reached 10.
                # 3+ is a triple-double, 2+ a double-double -- and ESPN counts a triple
                # as a double too, which is what makes these tally to its season figures.
                cats = sum(1 for v in (pts, reb, ast, r[12], r[13]) if v >= 10)
                plog[pid].append((date_of.get(gid, ""), pts, reb, ast, tpm, mins,
                                  ab, gidx.get((ab, gid), -1), ftm, cats, r[12], r[13]))

    # --- playoff per-game lines, tagged with the round they belong to.
    # Kept apart from plog: these games are not in a team's `games` list, so they carry
    # their own opponent/score rather than pointing at an index like the season log does.
    po_meta = {}                                   # (team, gid) -> round/opponent/score
    for ab, gs in po.items():
        for g in gs:
            rn = round_name(g.get("note"))
            if rn:
                po_meta[(ab, g["id"])] = (rn, g["opp"], g.get("us"), g.get("them"),
                                          g.get("res"), g.get("date", ""))
    pologs = defaultdict(list)                     # pid -> [(date, round, ...)]
    for gid, blocks in pobox.items():
        for ab, rows in blocks.items():
            meta = po_meta.get((ab, gid))
            if not meta:
                continue
            rn, opp, us, them, res, date = meta
            ri = ROUND_ORDER.index(rn) if rn in ROUND_ORDER else 9
            for r in rows:
                pid, mins, pts, fgm, fga, tpm, tpa, ftm, fta, reb, ast = r[:11]
                if not mins:                       # did not play: no bar
                    continue
                pocats = sum(1 for v in (pts, reb, ast, r[12], r[13]) if v >= 10)
                pologs[pid].append((date, ri, pts, tpm, ftm, mins, reb, ast,
                                    opp, us, them, res, pocats, r[12], r[13]))

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
    def player_record(p, with_shots=True):
        rs = p["rs"]
        log = sorted(plog.get(p["id"], []))
        pts_log = [x[1] for x in log]
        # The hover on the game chart wants opponent, result and final score. Rather
        # than copy those onto every game (7,000 of them), each entry points at the row
        # in that team's own games list, which the payload already ships:
        #   [index into p["teams"], index into that team's games, min, reb, ast,
        #    threes made, free throws made, 3 if a triple-double / 2 if a double-double]
        # The last two are what colours the game chart: threes*3 and free throws come
        # straight out, and everything left over came from twos.
        # His team's record IN THE GAMES HE PLAYED -- not the team's season record.
        # A player who missed 13 games did not take part in those results.
        wl = [0, 0]
        for x in log:
            gm = (sched.get(x[6]) or [])[x[7]] if 0 <= x[7] < len(sched.get(x[6], [])) else None
            if gm and gm.get("res") == "W":
                wl[0] += 1
            elif gm and gm.get("res") == "L":
                wl[1] += 1
        powl = [0, 0]
        for g in pologs.get(p["id"], []):
            if g[11] == "W":
                powl[0] += 1
            elif g[11] == "L":
                powl[1] += 1
        tix = {t["t"]: i for i, t in enumerate(p["teams"])}
        # ..., steals, blocks -- carried only so the hover can NAME the categories that
        # made a double-double. Points, rebounds and assists alone cannot: a game can
        # qualify on steals or blocks, and then the panel would list two numbers under
        # ten and call it a double-double.
        game_log = [[tix.get(x[6], 0), x[7], x[5], x[2], x[3], x[4], x[8],
                     3 if x[9] >= 3 else 2 if x[9] >= 2 else 0, x[10], x[11]]
                    for x in log]
        return {
            "rank": p["rank"], "id": p["id"], "nbaId": p["nbaId"],
            "name": p["name"], "short": p["short"], "team": p["team"],
            "teams": p["teams"], "pos": p["pos"], "age": p["age"],
            "jersey": jersey_of(p, worn), "height": p["height"], "weight": p["weight"],
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
            "log": pts_log, "glog": game_log, "wl": wl,
            "highs": {"pts": max(pts_log or [0]),
                      "reb": max((x[2] for x in log), default=0),
                      "ast": max((x[3] for x in log), default=0),
                      "tpm": max((x[4] for x in log), default=0),
                      # Who the best night came against. Ties go to the earliest such
                      # game -- log is already in date order, so max() keeps the first.
                      **best_night(log, sched)},
            "shots": shot.get(p["id"]) if with_shots else None,
            "po": ({"gp": int(p["po"].get("gamesPlayed", 0)),
                    "ppg": r1(p["po"].get("avgPoints", 0)),
                    "mpg": r1(p["po"].get("avgMinutes", 0)),
                    "rpg": r1(p["po"].get("avgRebounds", 0)),
                    "apg": r1(p["po"].get("avgAssists", 0)),
                    "wl": powl}
                   if p.get("po") else None),
            # No playoff line, but his team played: say so, otherwise the missing row
            # reads the same as "team missed the playoffs" and the reader can't tell
            # a DNP from an early exit. Value is how far the team actually got.
            # Playoff games on the same timeline as the season, after a divider.
            # [pts, threes made, free throws made, minutes, rebounds, assists,
            #  round index, W/L, opponent, us, them] -- round index keys the labels.
            # [pts, 3pm, ftm, min, reb, ast, round, W/L, opp, us, them, dbl, stl, blk]
            "polog": ([[g[2], g[3], g[4], g[5], g[6], g[7], g[1], g[11],
                        g[8], g[9], g[10], 3 if g[12] >= 3 else 2 if g[12] >= 2 else 0,
                        g[13], g[14]]
                       for g in sorted(pologs[p["id"]])] or None),
            "poMiss": (team_run_label(po.get(p.get("team"))) 
                       if not p.get("po") and po.get(p.get("team")) else None),
        }

    for p in deck[:PLAYER_CARDS]:
        out_players.append(player_record(p))

    # --- the tail: everyone who played but is outside the carded 100.
    # These are the film's UNLISTED cards. They are not in the deck -- it stays at its
    # 135 -- and no arrow key walks into them; they are reached by deep link only, and
    # the page fetches one team's file the first time a card on it is asked for. One
    # file per team rather than one bundle: a 21 KB fetch scoped to the team already on
    # screen beats a 640 KB fetch on the first click anywhere.
    carded = {p["id"] for p in deck[:PLAYER_CARDS]}
    by_id = {p["id"]: p for p in deck}
    tails, rows = {}, 0
    for t in out_teams:
        ids = [r["id"] for r in t["roster"] if r["id"] not in carded and r["id"] in by_id]
        rows += len(ids)
        if ids:
            tails[t["abbr"]] = {by_id[i]["id"]: player_record(by_id[i], with_shots=False)
                                for i in ids}

    # The order the unlisted cards sit in, and which file each is fetched from. It rides
    # in the payload rather than being re-derived in the browser so a card's number is
    # exactly its place in the scoring order -- deck order is by points with a tiebreak
    # the page cannot see, and re-sorting there would quietly renumber ties.
    #
    # A traded player appears on two rosters with an identical whole-season record in
    # both files, so the first team is as good as the second and he gets ONE card.
    home = {}
    for t in out_teams:
        for r in t["roster"]:
            home.setdefault(r["id"], t["abbr"])
    tail_order = [[p["id"], home[p["id"]]] for p in deck[PLAYER_CARDS:] if p["id"] in home]

    # --- the leader boards behind the three ranking charts.
    #
    # Over the WHOLE POOL, not the carded 100, because for two of the three they are not
    # the same list. The deck is ordered by points, so it has every scorer -- but the
    # rebounding lead belongs to Donovan Clingan with Rudy Gobert third, and Gobert is
    # not in the 100. Ranking what happened to be on hand would have had Karl-Anthony
    # Towns leading a category he did not lead. Points goes through the same path even
    # though the deck already answers it, so no card depends on that staying true.
    #
    # Top 12 rather than 10: the two views of each category are different lists, and a
    # couple of rows spare means a tie at the bottom does not silently truncate one.
    # Each row is [id, team, total, average, games played].
    LEAD = {"pts": ("points", "avgPoints"), "ast": ("assists", "avgAssists"),
            "reb": ("rebounds", "avgRebounds")}
    leaders = {}
    for key, (tot_k, avg_k) in LEAD.items():
        rows = [[p["id"], p["team"], int(p["rs"].get(tot_k, 0)),
                 r1(p["rs"].get(avg_k, 0)), int(p["rs"].get("gamesPlayed", 0))]
                for p in deck]
        leaders[key] = {
            # Ties broken by the other measure, then by id, so the order is stable
            # across rebuilds rather than riding on whatever sort() happened to do.
            "tot": sorted(rows, key=lambda r: (-r[2], -r[3], r[0]))[:12],
            "avg": sorted(rows, key=lambda r: (-r[3], -r[2], r[0]))[:12],
        }

    champ = next((t["abbr"] for t in out_teams if t["po"] and t["po"]["outcome"] == "CHAMPIONS"), None)

    # Team-card rosters reference players by id; ship a lookup so they can show names
    # without carrying a full player object per roster row. Whole pool, not just the
    # carded 60, because a roster row can be anyone who played.
    # The number he wore in THIS season, from the box scores -- not ESPN's athlete record,
    # which serves the number he wears now and none at all for anyone unsigned. The carded
    # 100 already went through jersey_of(); the roster tiles show the other 478, so they
    # need it too or a third of the league is labelled with next season's number.
    names = {p["id"]: [p["name"], p["pos"] or "", jersey_of(p, worn) or ""] for p in deck}

    nights = big_nights(sched, box, uncounted, deck)

    payload = {
        "season": label, "champion": champ,
        "teams": out_teams, "players": out_players, "names": names,
        "nights": nights, "tail": tail_order, "leaders": leaders,
        "counts": {"teams": len(out_teams), "players": len(out_players),
                   "playerPool": len(deck)},
    }
    p = os.path.join(DATA, f"cards-{label}.json")
    with open(p, "w") as f:
        json.dump(payload, f, separators=(",", ":"), ensure_ascii=False)

    rdir = os.path.join(DATA, "roster")
    os.makedirs(rdir, exist_ok=True)
    for old_f in os.listdir(rdir):
        if old_f.startswith(f"{label}-"):
            os.remove(os.path.join(rdir, old_f))
    tot = 0
    for ab, players in tails.items():
        rp = os.path.join(rdir, f"{label}-{ab}.json")
        with open(rp, "w") as f:
            json.dump(players, f, separators=(",", ":"), ensure_ascii=False)
        tot += os.path.getsize(rp)
    if tails:
        sizes = [os.path.getsize(os.path.join(rdir, f"{label}-{ab}.json")) for ab in tails]
        print(f"  roster files: {len(tails)} teams, {sum(len(v) for v in tails.values())} "
              f"players over {rows} rows, {min(sizes)/1024:.0f}-{max(sizes)/1024:.0f} KB "
              f"each, {tot/1024:.0f} KB total")

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

    dbl = [(x["name"], sum(1 for g in x["glog"] if g[7] >= 2), x["dd"],
            sum(1 for g in x["glog"] if g[7] == 3), x["td"]) for x in out_players]
    off = [d for d in dbl if d[1] != d[2] or d[3] != d[4]]
    print(f"  double/triple-doubles: {len(dbl) - len(off)}/{len(dbl)} tally to ESPN's season"
          + (f" -- OFF: {off[:3]}" if off else ""))

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

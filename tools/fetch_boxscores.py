#!/usr/bin/env python3
"""Every box score of a season, reduced to compact per-game player lines.

    python3 tools/fetch_boxscores.py 2025-26

This exists for one unavoidable reason: **ESPN has no season-accurate roster.** Every
roster endpoint (site, and the season-scoped core API) returns the CURRENT roster, so
after the 2026 offseason it put Jaylen Brown on Philadelphia and Paul George on Boston
while serving their 2025-26 stat lines. Box scores are the ground truth for who played
for whom, and they come with the per-game lines the film wants anyway.

Each summary is ~425 KB (it bundles play-by-play), so raw payloads are NOT kept -- only
the extracted lines, gzipped. Re-running resumes from the cache.
"""
import gzip
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
CACHE = os.path.join(HERE, "..", "scratch", "boxlines")
SUM = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event="

# The order ESPN lists them in; stored positionally to keep the file small.
LABELS = ["MIN", "PTS", "FG", "3PT", "FT", "REB", "AST", "TO", "STL", "BLK",
          "OREB", "DREB", "PF", "+/-"]


def get(url, tries=4):
    last = None
    for a in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=45) as r:
                return json.loads(r.read())
        except Exception as e:                      # noqa: BLE001
            last = e
            time.sleep(1.2 * (a + 1))
    raise RuntimeError(f"{url}: {last}")


def split(v):
    """'4-8' -> (4, 8); handles blanks and the odd '--'."""
    try:
        a, b = v.split("-")
        return int(a), int(b)
    except Exception:                                # noqa: BLE001
        return 0, 0


def num(v):
    try:
        return int(str(v).replace("+", ""))
    except Exception:                                # noqa: BLE001
        return 0


def extract(gid, d):
    """-> {'g':gid, 'teams':{ABBR:[[pid,min,pts,fgm,fga,tpm,tpa,ftm,fta,reb,ast,to,stl,blk,pm,started,jersey],...]}}"""
    out = {"g": gid, "teams": {}}
    for block in d.get("boxscore", {}).get("players", []):
        ab = block["team"]["abbreviation"]
        rows = []
        for stat in block.get("statistics", []):
            labels = stat.get("labels", [])
            idx = {l: i for i, l in enumerate(labels)}
            for a in stat.get("athletes", []):
                s = a.get("stats") or []
                if not s:
                    continue            # DNP -- carries no line at all
                # An inactive player (coach's decision) still gets a row, but it is
                # all zeros with "--" minutes and the athlete object has NO id --
                # only links and a shortName. Missing id is the reliable signal.
                #
                # Do NOT filter on a["active"]: it means "on the CURRENT roster",
                # not "played in this game". Huerter is active:false in a game he
                # played 32 minutes of, so filtering on it silently deleted real
                # players from 22 games and broke the score reconciliation.
                pid = (a.get("athlete") or {}).get("id")
                if not pid or a.get("didNotPlay"):
                    continue
                def g(l):
                    i = idx.get(l)
                    return s[i] if i is not None and i < len(s) else "0"
                fgm, fga = split(g("FG"))
                tpm, tpa = split(g("3PT"))
                ftm, fta = split(g("FT"))
                # THE signal for "was he actually in this game": the RAW minutes string.
                # "--" means he never entered; a numeric "0" means he did but logged
                # under a minute -- Mikal Bridges has exactly that, with one personal
                # foul to prove it, and ESPN counts it as a game played. num() turns
                # both into 0, so testing the parsed value cannot tell them apart:
                # dropping all zero-minute rows cost Bridges a game off his 82-game
                # season, and keeping them gave Vucevic a 65th game he never played.
                if not str(g("MIN")).strip().isdigit():
                    continue
                line = [
                    pid, num(g("MIN")), num(g("PTS")),
                    fgm, fga, tpm, tpa, ftm, fta,
                    num(g("REB")), num(g("AST")), num(g("TO")),
                    num(g("STL")), num(g("BLK")), num(g("+/-")),
                    1 if a.get("starter") else 0,
                    # The number he wore THAT NIGHT. ESPN's athlete endpoint serves the
                    # number he wears NOW -- same trap as the roster -- and for a player
                    # who is unsigned at fetch time it serves none at all, which left 10
                    # of the 100 carded players with no number. The box score has one for
                    # every athlete in it.
                    str((a.get("athlete") or {}).get("jersey") or ""),
                ]
                rows.append(line)
        out["teams"][ab] = rows
    return out


def one(gid):
    p = os.path.join(CACHE, f"{gid}.json.gz")
    if os.path.exists(p):
        with gzip.open(p, "rt") as f:
            return json.load(f)
    d = get(SUM + gid)
    e = extract(gid, d)
    os.makedirs(CACHE, exist_ok=True)
    with gzip.open(p, "wt") as f:
        json.dump(e, f, separators=(",", ":"))
    return e


def do(label, postseason=False):
    """postseason=True pulls the playoff games instead, from playoffs-*.json.

    Same endpoint, same extraction -- ESPN's summary is identical for a playoff game,
    it is only the id list that differs. Written to its own file so a playoff line can
    never be mistaken for a regular-season one downstream.
    """
    if postseason:
        po = json.load(open(os.path.join(DATA, f"playoffs-{label}.json")))
        gids = sorted({g["id"] for gs in po.values() for g in gs if g.get("res")})
    else:
        sched = json.load(open(os.path.join(DATA, f"schedule-{label}.json")))
        gids = sorted({g["id"] for gs in sched.values() for g in gs if g["res"]})
    print(f"  {len(gids)} completed {'playoff ' if postseason else ''}games to pull")

    got, fail, t0 = {}, [], time.time()
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(one, g): g for g in gids}
        for n, f in enumerate(as_completed(futs), 1):
            gid = futs[f]
            try:
                got[gid] = f.result()
            except Exception as e:                   # noqa: BLE001
                fail.append((gid, str(e)[:70]))
            if n % 200 == 0 or n == len(gids):
                print(f"    {n}/{len(gids)}  {time.time() - t0:.0f}s  "
                      f"{len(fail)} failed", flush=True)

    if fail:
        print(f"  WARNING {len(fail)} games failed: {fail[:3]}")

    out = {g: got[g]["teams"] for g in sorted(got)}
    p = os.path.join(DATA, f"boxlines{'-po' if postseason else ''}-{label}.json.gz")
    with gzip.open(p, "wt") as f:
        json.dump(out, f, separators=(",", ":"))
    rows = sum(len(r) for t in out.values() for r in t.values())
    print(f"  wrote {os.path.relpath(p, os.path.join(HERE, '..'))}  "
          f"{os.path.getsize(p) / 1024 / 1024:.1f} MB  ({rows} player-games)")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--playoffs"]
    do(args[0] if args else "2025-26", postseason="--playoffs" in sys.argv)

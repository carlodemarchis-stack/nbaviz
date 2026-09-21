#!/usr/bin/env python3
"""Pull teams, schedules and results from ESPN's public API.

    python3 tools/fetch_espn.py teams
    python3 tools/fetch_espn.py schedule 2026      # = the 2025-26 season
    python3 tools/fetch_espn.py schedule 2027      # = 2026-27, unplayed

ESPN answers plain curl, which is the whole point: this same script has to keep running
from GitHub Actions once 2026-27 tips off on 22 Oct 2026. stats.nba.com does not -- it
fingerprints non-browser clients -- so nothing the live path depends on may come from there.

ESPN labels a season by the calendar year it ENDS in: season=2026 is 2025-26.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "..", "scratch", "raw")
DATA = os.path.join(HERE, "..", "data")
SITE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
# ESPN's UA handling is fussy and counter-intuitive, so do not "improve" this:
#   Chrome string        -> 403   (spoofing a browser from a non-browser client)
#   custom "agwas/1.0"   -> 403   (anything it doesn't recognise)
#   curl/x.y, Python-urllib -> 200
# So we send no override and let urllib identify itself honestly.
# stats.nba.com is the exact opposite (it wants a real browser), which is why the two
# sources are fetched by different code paths rather than one shared helper.
UA = None


def season_label(year):
    """ESPN's end-year -> the NBA's own label. 2026 -> '2025-26'."""
    return f"{year - 1}-{str(year)[2:]}"


def get(url, tries=4):
    last = None
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA} if UA else {})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read())
        except Exception as e:                      # noqa: BLE001 - retry anything transient
            last = e
            time.sleep(1.5 * (a + 1))
    raise RuntimeError(f"{url} failed after {tries}: {last}")


def cached(name, url):
    os.makedirs(RAW, exist_ok=True)
    p = os.path.join(RAW, name + ".json")
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    d = get(url)
    with open(p, "w") as f:
        json.dump(d, f)
    return d


def write(name, obj):
    os.makedirs(DATA, exist_ok=True)
    p = os.path.join(DATA, name)
    with open(p, "w") as f:
        json.dump(obj, f, separators=(",", ":"), ensure_ascii=False)
    print(f"  wrote data/{name}  {os.path.getsize(p) / 1024:.0f} KB")


# --- teams ------------------------------------------------------------------

# ESPN carries no conference/division on the teams endpoint, and the standings tree
# is awkward to walk, so the league's own alignment is stated here. It changes about
# once a decade; when it does, this is the one place to edit.
ALIGN = {
    "BOS": ("East", "Atlantic"), "BKN": ("East", "Atlantic"), "NY": ("East", "Atlantic"),
    "PHI": ("East", "Atlantic"), "TOR": ("East", "Atlantic"),
    "CHI": ("East", "Central"), "CLE": ("East", "Central"), "DET": ("East", "Central"),
    "IND": ("East", "Central"), "MIL": ("East", "Central"),
    "ATL": ("East", "Southeast"), "CHA": ("East", "Southeast"), "MIA": ("East", "Southeast"),
    "ORL": ("East", "Southeast"), "WSH": ("East", "Southeast"),
    "DEN": ("West", "Northwest"), "MIN": ("West", "Northwest"), "OKC": ("West", "Northwest"),
    "POR": ("West", "Northwest"), "UTAH": ("West", "Northwest"),
    "GS": ("West", "Pacific"), "LAC": ("West", "Pacific"), "LAL": ("West", "Pacific"),
    "PHX": ("West", "Pacific"), "SAC": ("West", "Pacific"),
    "DAL": ("West", "Southwest"), "HOU": ("West", "Southwest"), "MEM": ("West", "Southwest"),
    "NO": ("West", "Southwest"), "SA": ("West", "Southwest"),
}

# ESPN abbreviation -> the NBA's own team id, which is what cdn.nba.com keys crests
# and headshots by. Without this the official logo SVGs are unreachable.
NBA_ID = {
    "ATL": 1610612737, "BOS": 1610612738, "BKN": 1610612751, "CHA": 1610612766,
    "CHI": 1610612741, "CLE": 1610612739, "DAL": 1610612742, "DEN": 1610612743,
    "DET": 1610612765, "GS": 1610612744, "HOU": 1610612745, "IND": 1610612754,
    "LAC": 1610612746, "LAL": 1610612747, "MEM": 1610612763, "MIA": 1610612748,
    "MIL": 1610612749, "MIN": 1610612750, "NO": 1610612740, "NY": 1610612752,
    "OKC": 1610612760, "ORL": 1610612753, "PHI": 1610612755, "PHX": 1610612756,
    "POR": 1610612757, "SAC": 1610612758, "SA": 1610612759, "TOR": 1610612761,
    "UTAH": 1610612762, "WSH": 1610612764,
}


def do_teams():
    d = cached("espn_teams", f"{SITE}/teams")
    rows = d["sports"][0]["leagues"][0]["teams"]
    out = {}
    for r in rows:
        t = r["team"]
        ab = t["abbreviation"]
        conf, div = ALIGN.get(ab, ("?", "?"))
        out[ab] = {
            "abbr": ab, "espnId": t["id"], "nbaId": NBA_ID.get(ab),
            "name": t["displayName"], "short": t["shortDisplayName"],
            "city": t.get("location"), "nick": t.get("name"),
            "primary": "#" + t.get("color", "888888"),
            "secondary": "#" + t.get("alternateColor", "cccccc"),
            "conf": conf, "div": div,
        }
    missing = [a for a, v in out.items() if v["nbaId"] is None or v["conf"] == "?"]
    if missing:
        sys.exit(f"FAIL unmapped teams: {missing}")
    if len(out) != 30:
        sys.exit(f"FAIL expected 30 teams, got {len(out)}")
    write("teams.json", out)
    return out


# --- schedule / results -----------------------------------------------------

def team_schedule(espn_id, year):
    d = cached(f"espn_sched_{espn_id}_{year}",
               f"{SITE}/teams/{espn_id}/schedule?season={year}&seasontype=2")
    return d.get("events", [])


def do_schedule(year):
    teams = json.load(open(os.path.join(DATA, "teams.json")))
    by_espn = {v["espnId"]: k for k, v in teams.items()}
    label = season_label(year)

    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ab: ex.submit(team_schedule, t["espnId"], year) for ab, t in teams.items()}
        raw = {ab: f.result() for ab, f in futs.items()}

    sched, played, scheduled, dropped, uncounted = {}, 0, 0, 0, 0
    for ab, events in raw.items():
        games = []
        for e in events:
            c = e["competitions"][0]
            me = them = None
            for comp in c["competitors"]:
                side = by_espn.get(comp["team"]["id"])
                (me := comp) if side == ab else (them := comp)  # noqa: E731
            if me is None or them is None:
                continue
            opp = by_espn.get(them["team"]["id"])
            st = c["status"]["type"]

            # A postponed game stays in ESPN's feed as a shell alongside its makeup,
            # so both dates are listed and the team appears to play 83 games. Four
            # pairs were postponed in 2025-26 (court condensation at the United Center
            # among them). Drop the shell; the makeup carries the result.
            if st["name"] in ("STATUS_POSTPONED", "STATUS_CANCELED"):
                dropped += 1
                continue

            note = next((n.get("headline") for n in c.get("notes", []) if n.get("headline")), None)
            # The NBA Cup Championship is the one game of the season that does NOT
            # count toward a team's record (the group and knockout rounds do). It is
            # kept here as a trophy for the team card, but excluded from W/L.
            counts = not (note and "Cup Championship" in note)

            g = {
                "id": c["id"], "date": c["date"], "opp": opp,
                "ha": "H" if me["homeAway"] == "home" else "A",
                "neutral": bool(c.get("neutralSite")),
            }
            if note:
                g["note"] = note
            if not counts:
                g["counts"] = False
                uncounted += 1
            if st.get("completed"):
                us, th = int(me["score"]["value"]), int(them["score"]["value"])
                g.update({"us": us, "them": th, "res": "W" if us > th else "L"})
                played += 1
            else:
                g["res"] = None
                scheduled += 1
            games.append(g)
        games.sort(key=lambda x: x["date"])
        for i, g in enumerate(games, 1):
            g["g"] = i
        sched[ab] = games

    # Every team's RECORD is 82 games; the Cup final sits outside it.
    rec = {ab: sum(1 for g in v if g.get("counts", True)) for ab, v in sched.items()}
    odd = {ab: n for ab, n in rec.items() if n != 82}
    print(f"  {label}: {played} played, {scheduled} scheduled, "
          f"{dropped} postponed shells dropped, {uncounted} not counting toward record")
    if odd:
        # 2026-27 legitimately lands here: the NBA publishes 80 games per team and
        # fills the last two only after the Cup group stage resolves in December.
        lo = min(odd.values())
        print(f"  NOTE teams not at 82 counting games: {len(odd)} teams, "
              f"{lo}-{max(odd.values())} games each")
    write(f"schedule-{label}.json", sched)
    return sched


def do_playoffs(year):
    """Playoff games (seasontype=3). A season film has to know who won the title.

    Kept separate from the regular season: playoff results must never touch a team's
    W/L record, and the towers show the 82-game season only.
    """
    teams = json.load(open(os.path.join(DATA, "teams.json")))
    by_espn = {v["espnId"]: k for k, v in teams.items()}
    label = season_label(year)

    def sched(espn_id):
        return cached(f"espn_po_{espn_id}_{year}",
                      f"{SITE}/teams/{espn_id}/schedule?season={year}&seasontype=3"
                      ).get("events", [])

    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ab: ex.submit(sched, t["espnId"]) for ab, t in teams.items()}
        raw = {ab: f.result() for ab, f in futs.items()}

    out = {}
    for ab, events in raw.items():
        games = []
        for e in events:
            c = e["competitions"][0]
            st = c["status"]["type"]
            if st["name"] in ("STATUS_POSTPONED", "STATUS_CANCELED"):
                continue
            me = them = None
            for comp in c["competitors"]:
                (me := comp) if by_espn.get(comp["team"]["id"]) == ab else (them := comp)  # noqa: E731
            if me is None or them is None:
                continue
            g = {"id": c["id"], "date": c["date"],
                 "opp": by_espn.get(them["team"]["id"]),
                 "ha": "H" if me["homeAway"] == "home" else "A",
                 "note": next((n.get("headline") for n in c.get("notes", [])
                               if n.get("headline")), None)}
            if st.get("completed"):
                us, th = int(me["score"]["value"]), int(them["score"]["value"])
                g.update({"us": us, "them": th, "res": "W" if us > th else "L"})
            else:
                g["res"] = None
            games.append(g)
        games.sort(key=lambda x: x["date"])
        if games:
            out[ab] = games

    wins = {ab: sum(1 for g in v if g["res"] == "W") for ab, v in out.items()}
    champ = [ab for ab, n in wins.items() if n >= 16]
    print(f"  {label} playoffs: {len(out)} teams, "
          f"{sum(len(v) for v in out.values()) // 2} games")
    print(f"  16-win team (champion): {champ or 'none yet'}")
    write(f"playoffs-{label}.json", out)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "teams"
    if cmd == "teams":
        do_teams()
    elif cmd == "schedule":
        do_schedule(int(sys.argv[2]))
    elif cmd == "playoffs":
        do_playoffs(int(sys.argv[2]))
    else:
        sys.exit(__doc__)

"""The stats.nba.com harvest job list.

curl cannot reach stats.nba.com from here (Akamai fingerprints it and hangs), but a real
browser sitting on nba.com fetches the same endpoints in ~0.5s. So the job list lives here,
harvest_server.py hands it to the browser, and the browser posts the answers back.

Everything ESPN can serve by plain curl is deliberately NOT in this list -- that lives in
fetch_espn.py, because it has to keep working headlessly in CI once 2026-27 tips off.
"""

SEASON = "2025-26"
RS = "Regular+Season"

TEAMS = {
    1610612737: "ATL", 1610612738: "BOS", 1610612751: "BKN", 1610612766: "CHA",
    1610612741: "CHI", 1610612739: "CLE", 1610612742: "DAL", 1610612743: "DEN",
    1610612765: "DET", 1610612744: "GSW", 1610612745: "HOU", 1610612754: "IND",
    1610612746: "LAC", 1610612747: "LAL", 1610612763: "MEM", 1610612748: "MIA",
    1610612749: "MIL", 1610612750: "MIN", 1610612740: "NOP", 1610612752: "NYK",
    1610612760: "OKC", 1610612753: "ORL", 1610612755: "PHI", 1610612756: "PHX",
    1610612757: "POR", 1610612758: "SAC", 1610612759: "SAS", 1610612761: "TOR",
    1610612762: "UTA", 1610612764: "WAS",
}

B = "https://stats.nba.com/stats/"


def _dash(measure, entity, per="PerGame", season=SEASON, stype=RS):
    """leaguedash{player,team}stats -- the long parameter list these endpoints insist on."""
    return (
        f"{B}leaguedash{entity}stats?College=&Conference=&Country=&DateFrom=&DateTo="
        f"&Division=&DraftPick=&DraftYear=&GameScope=&GameSegment=&Height=&LastNGames=0"
        f"&LeagueID=00&Location=&MeasureType={measure}&Month=0&OpponentTeamID=0&Outcome="
        f"&PORound=0&PaceAdjust=N&PerMode={per}&Period=0&PlayerExperience=&PlayerPosition="
        f"&PlusMinus=N&Rank=N&Season={season}&SeasonSegment=&SeasonType={stype}"
        f"&ShotClockRange=&StarterBench=&TeamID=0&TwoWay=&VsConference=&VsDivision=&Weight="
    )


def league_jobs(season=SEASON):
    """League-wide pulls: one call each, the backbone of the card stats."""
    j = {
        f"standings_{season}": f"{B}leaguestandingsv3?LeagueID=00&Season={season}&SeasonType=Regular+Season",
        # Player stats, four measure types -- Base gives points/rebounds/assists,
        # Advanced gives TS%/usage/net rating, Scoring the shot mix, Usage the share.
        f"players_base_{season}": _dash("Base", "player"),
        f"players_adv_{season}": _dash("Advanced", "player"),
        f"players_scor_{season}": _dash("Scoring", "player"),
        # Totals as well as per-game: the card deck is ordered by total points scored.
        f"players_totals_{season}": _dash("Base", "player", per="Totals"),
        f"teams_base_{season}": _dash("Base", "team"),
        f"teams_adv_{season}": _dash("Advanced", "team"),
        f"teams_totals_{season}": _dash("Base", "team", per="Totals"),
        # Playoffs -- 2025-26 is a closed season, so the film can show the whole run.
        f"players_base_po_{season}": _dash("Base", "player", stype="Playoffs"),
        f"teams_base_po_{season}": _dash("Base", "team", stype="Playoffs"),
    }
    return [{"name": k, "url": v} for k, v in j.items()]


def roster_jobs(season=SEASON):
    return [
        {"name": f"roster_{abbr}_{season}",
         "url": f"{B}commonteamroster?LeagueID=00&Season={season}&TeamID={tid}"}
        for tid, abbr in TEAMS.items()
    ]


def player_jobs(player_ids, season=SEASON):
    """Per-player career + game log + shot chart, for the players that get a card."""
    out = []
    for pid in player_ids:
        out.append({"name": f"career_{pid}",
                    "url": f"{B}playercareerstats?LeagueID=00&PerMode=PerGame&PlayerID={pid}"})
        out.append({"name": f"info_{pid}",
                    "url": f"{B}commonplayerinfo?LeagueID=00&PlayerID={pid}"})
        out.append({"name": f"log_{pid}_{season}",
                    "url": f"{B}playergamelogs?LeagueID=00&PlayerID={pid}&Season={season}"
                           f"&SeasonType={RS}"})
        out.append({"name": f"shots_{pid}_{season}", "url": (
            f"{B}shotchartdetail?AheadBehind=&CFID=&CFPARAMS=&ClutchTime=&Conference="
            f"&ContextFilter=&ContextMeasure=FGA&DateFrom=&DateTo=&Division=&EndPeriod=10"
            f"&EndRange=28800&GameID=&GameSegment=&LastNGames=0&LeagueID=00&Location=&Month=0"
            f"&OpponentTeamID=0&Outcome=&Period=0&PlayerID={pid}&PlayerPosition=&PointDiff="
            f"&Position=&RangeType=0&RookieYear=&Season={season}&SeasonSegment=&SeasonType={RS}"
            f"&StartPeriod=1&StartRange=0&TeamID=0&VsConference=&VsDivision=")})
    return out

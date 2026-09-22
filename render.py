#!/usr/bin/env python3
"""Inject the card payload into the template(s) and write the shippable pages.

    python3 render.py                # 2025-26
    python3 render.py 2026-27

template.html  -> index.html   (the card film)
towers.html.in -> towers.html  (the season towers, if present)

The pages ship self-contained: the payload is inlined rather than fetched, so the film
paints without a second round trip and works from a file:// URL.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

SITE = "https://nba.aguywithascarf.com"

# Fields the towers page needs; the film payload is far bigger than the towers require,
# so each page gets only what it draws.
TOWER_TEAM_KEYS = ("abbr", "name", "city", "nick", "conf", "div", "seed", "primary",
                   "secondary", "w", "l", "pct", "diff", "games", "po")


def build(tpl_path, out_path, payload, season, extra=None):
    with open(tpl_path) as f:
        html = f.read()
    blob = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    # The template says `const D = /*__DATA__*/{};` so it stays valid JavaScript on its
    # own. The trailing {} must be consumed here or the render produces `{...}{}`,
    # which is a syntax error that kills the whole script silently.
    if "/*__DATA__*/{}" in html:
        html = html.replace("/*__DATA__*/{}", blob)
    elif "/*__DATA__*/" in html:
        html = html.replace("/*__DATA__*/", blob)
    else:
        sys.exit(f"FAIL {os.path.basename(tpl_path)} has no /*__DATA__*/ marker")
    html = html.replace("__SEASON__", season)
    for k, v in (extra or {}).items():
        html = html.replace(k, v)
    with open(out_path, "w") as f:
        f.write(html)
    kb = os.path.getsize(out_path) / 1024
    print(f"  wrote {os.path.basename(out_path)}  {kb:.0f} KB "
          f"(payload {len(blob) / 1024:.0f} KB)")


def social(stem, season, payload, landing=False):
    """Per-file link-preview text. Each page says what IT is.

    The towers page is not the film, and a season with nothing played yet must not
    advertise a champion -- a shared description would claim both. Facts come out of the
    payload rather than being written by hand, so they cannot drift from the cards.
    """
    teams = payload.get("teams") or []
    played = [t for t in teams if any(g.get("res") for g in t.get("games", []))]
    top = teams[0] if teams else None
    champ = next((t for t in teams
                  if t.get("po") and t["po"].get("outcome") == "CHAMPIONS"), None)
    url = f"{SITE}/" if landing else f"{SITE}/{stem}-{season}.html"

    if not played:
        story = (f"All 30 franchises and the published {season} schedule, before a ball "
                 f"is thrown. The cards fill in as the season is played.")
    else:
        story = (f"{top['name']} won {top['w']}"
                 + (f", and {champ['nick']} took the title from the {champ['seed']} seed"
                    if champ and champ.get("seed") else "")
                 + ".")

    if stem == "towers":
        desc = (f"Every NBA team's {season} season as a shape: wins stack up, losses hang "
                f"down, games still to play hang from the ceiling. "
                + (f"Drag the slider and watch the table re-sort game by game. {story}"
                   if played else story))
        return {"__PAGEURL__": url,
                "__OGTITLE__": f"NBA Season Towers — {season}",
                "__OGDESC__": desc,
                "__OGALT__": f"Thirty NBA teams drawn as towers on a shared baseline, {season}"}

    n = len(payload.get("players") or [])
    if not played:
        # No players, so no "leading scorers" -- the unplayed film is the schedule.
        desc = (f"The {season} NBA season as a film, before a ball is thrown: a card per "
                f"franchise carrying the published schedule. The player cards and the "
                f"charts fill in as the season is played.")
        alt = f"A team card from the {season} NBA season film"
    else:
        desc = (f"The {season} NBA season as a film of {1 + len(teams) + n + 4} cards: "
                f"the {n} leading scorers with every shot they took, all {len(teams)} "
                f"franchises, and the charts that rank them. {story}")
        alt = f"A player card from the {season} NBA season film"
    return {"__PAGEURL__": url,
            "__OGTITLE__": f"NBA Season Film — {season}",
            "__OGDESC__": desc, "__OGALT__": alt}


def one_season(season, seasons):
    payload = json.load(open(os.path.join(DATA, f"cards-{season}.json")))
    payload["seasons"] = seasons

    build(os.path.join(HERE, "template.html"),
          os.path.join(HERE, f"index-{season}.html"), payload, season,
          social("index", season, payload))

    # The previous player-card layout, kept buildable so the two can be compared live
    # and the new one reverted by deleting template.html and renaming this back.
    classic = os.path.join(HERE, "template-classic.html")
    if os.path.exists(classic):
        build(classic, os.path.join(HERE, f"classic-{season}.html"), payload, season,
              social("classic", season, payload))

    tow_tpl = os.path.join(HERE, "towers.html.in")
    if os.path.exists(tow_tpl):
        slim = {"season": season, "seasons": seasons,
                "champion": payload.get("champion"),
                "teams": [{k: t[k] for k in TOWER_TEAM_KEYS if k in t}
                          for t in payload["teams"]]}
        build(tow_tpl, os.path.join(HERE, f"towers-{season}.html"), slim, season,
              social("towers", season, payload))


def main(default_season):
    seasons = sorted(f[6:-5] for f in os.listdir(DATA)
                     if f.startswith("cards-") and f.endswith(".json"))
    if default_season not in seasons:
        sys.exit(f"FAIL no data/cards-{default_season}.json "
                 f"-- run tools/build_cards.py {default_season}")

    # Every season gets its own pair of pages, so cross-links can be derived from the
    # season name alone rather than needing to know which one is "default".
    for s in seasons:
        one_season(s, seasons)

    # index.html / towers.html are the landing pair: a copy of the default season.
    payload = json.load(open(os.path.join(DATA, f"cards-{default_season}.json")))
    for stem in ("index", "towers", "classic"):
        src = os.path.join(HERE, f"{stem}-{default_season}.html")
        if os.path.exists(src):
            with open(src) as f:
                html = f.read()
            # index.html IS the site root, so its canonical and og:url must be the bare
            # domain -- otherwise every share of nba.aguywithascarf.com points the
            # crawler at index-2025-26.html and the two compete as duplicates.
            root = social(stem, default_season, payload, landing=True)["__PAGEURL__"]
            if stem == "towers":
                root = f"{SITE}/towers.html"
            elif stem == "classic":
                root = f"{SITE}/classic.html"
            html = html.replace(f"{SITE}/{stem}-{default_season}.html", root)
            with open(os.path.join(HERE, f"{stem}.html"), "w") as f:
                f.write(html)
            print(f"  {stem}.html -> copy of {stem}-{default_season}.html  ({root})")

    print(f"  seasons: {seasons}  (landing = {default_season})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2025-26")

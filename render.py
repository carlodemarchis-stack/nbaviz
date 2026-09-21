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


def one_season(season, seasons):
    payload = json.load(open(os.path.join(DATA, f"cards-{season}.json")))
    payload["seasons"] = seasons

    build(os.path.join(HERE, "template.html"),
          os.path.join(HERE, f"index-{season}.html"), payload, season)

    # The previous player-card layout, kept buildable so the two can be compared live
    # and the new one reverted by deleting template.html and renaming this back.
    classic = os.path.join(HERE, "template-classic.html")
    if os.path.exists(classic):
        build(classic, os.path.join(HERE, f"classic-{season}.html"), payload, season)

    tow_tpl = os.path.join(HERE, "towers.html.in")
    if os.path.exists(tow_tpl):
        slim = {"season": season, "seasons": seasons,
                "champion": payload.get("champion"),
                "teams": [{k: t[k] for k in TOWER_TEAM_KEYS if k in t}
                          for t in payload["teams"]]}
        build(tow_tpl, os.path.join(HERE, f"towers-{season}.html"), slim, season)


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
    for stem in ("index", "towers", "classic"):
        src = os.path.join(HERE, f"{stem}-{default_season}.html")
        if os.path.exists(src):
            with open(src) as f:
                html = f.read()
            with open(os.path.join(HERE, f"{stem}.html"), "w") as f:
                f.write(html)
            print(f"  {stem}.html -> copy of {stem}-{default_season}.html")

    print(f"  seasons: {seasons}  (landing = {default_season})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2025-26")

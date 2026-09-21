#!/usr/bin/env python3
"""Official crests and headshots from cdn.nba.com.

    python3 tools/fetch_images.py crests
    python3 tools/fetch_images.py heads        # needs data/nba_ids.json

cdn.nba.com serves images to plain curl happily -- it is only the /static/json/ paths
that are 403. Crests are real SVGs (vector, so they stay crisp at any card size) and
headshots are 1040x760 transparent cutouts.
"""
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
IMG = os.path.join(HERE, "..", "img")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def grab(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return "cached"
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Referer": "https://www.nba.com/"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            b = r.read()
    except Exception as e:                           # noqa: BLE001
        return f"FAIL {e}"
    if len(b) < 200:
        return f"FAIL tiny ({len(b)}B)"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b)
    return f"{len(b) / 1024:.0f}KB"


def crests():
    teams = json.load(open(os.path.join(DATA, "teams.json")))
    out = os.path.join(IMG, "crest")
    jobs = [(ab, f"https://cdn.nba.com/logos/nba/{t['nbaId']}/primary/L/logo.svg",
             os.path.join(out, f"{ab}.svg")) for ab, t in teams.items()]
    with ThreadPoolExecutor(max_workers=8) as ex:
        res = list(ex.map(lambda j: (j[0], grab(j[1], j[2])), jobs))
    bad = [r for r in res if str(r[1]).startswith("FAIL")]
    print(f"  crests: {len(res) - len(bad)}/{len(res)} ok")
    for b in bad:
        print("   ", b)


def heads(limit=120):
    """Official 1040x760 cutouts for the players that get a card.

    Keyed by NBA player id, which build_players.py resolved by name -- ESPN ids do
    not work against cdn.nba.com. Files are named by ESPN id so the card template
    (which keys everything by ESPN id) can find them.
    """
    deck = json.load(open(os.path.join(DATA, "deck-players-2025-26.json")))[:limit]
    out = os.path.join(IMG, "head")
    jobs, missing = [], []
    for p in deck:
        if not p.get("nbaId"):
            missing.append(p["name"])
            continue
        jobs.append((p["name"],
                     f"https://cdn.nba.com/headshots/nba/latest/1040x760/{p['nbaId']}.png",
                     os.path.join(out, f"{p['id']}.png")))
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(lambda j: (j[0], grab(j[1], j[2])), jobs))
    bad = [r for r in res if str(r[1]).startswith("FAIL")]
    print(f"  headshots: {len(res) - len(bad)}/{len(res)} ok, {len(missing)} unmapped")
    for b in bad[:6]:
        print("   ", b)


def optimise(width=560, quality=82):
    """PNG cutouts -> webp at card size.

    The 1040x760 originals are 23 MB for 120 players, which is far too much for a page
    that shows 60 of them. Transparency must survive, so RGBA webp, not JPEG.
    """
    from PIL import Image
    src = os.path.join(IMG, "head")
    dst = os.path.join(IMG, "headw")
    os.makedirs(dst, exist_ok=True)
    before = after = 0
    n = 0
    for f in sorted(os.listdir(src)):
        if not f.endswith(".png"):
            continue
        sp, dp = os.path.join(src, f), os.path.join(dst, f[:-4] + ".webp")
        before += os.path.getsize(sp)
        if not os.path.exists(dp):
            im = Image.open(sp).convert("RGBA")
            if im.width > width:
                im = im.resize((width, round(im.height * width / im.width)),
                               Image.LANCZOS)
            im.save(dp, "WEBP", quality=quality, method=6)
        after += os.path.getsize(dp)
        n += 1
    print(f"  {n} headshots: {before / 1024 / 1024:.1f} MB PNG -> "
          f"{after / 1024 / 1024:.1f} MB webp ({after / max(1, before) * 100:.0f}%)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "crests"
    if cmd == "crests":
        crests()
    elif cmd == "optimise":
        optimise()
    else:
        heads(int(sys.argv[2]) if len(sys.argv) > 2 else 120)

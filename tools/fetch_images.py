#!/usr/bin/env python3
"""Official crests and headshots from cdn.nba.com.

    python3 tools/fetch_images.py crests
    python3 tools/fetch_images.py heads        # needs data/nba_ids.json
    python3 tools/fetch_images.py nbaroster 2026-27  # this season's official photos
    python3 tools/fetch_images.py season 2026-27   # missing photos for a live season

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


def season_heads(label):
    """Photos for everyone on the live season's rosters and in its deck who has none yet.

    The official NBA cutout when we know his NBA id (build_players resolves those by
    name, against an index that only covers last season's players); otherwise ESPN's
    headshot, which every rookie and newcomer has. The two are different crops of the
    same idea, a transparent head-and-shoulders, so they sit together on a tile well
    enough -- and a tile without either falls back to initials. Only missing photos are
    fetched, so this is cheap to run every night.
    """
    have = {f[:-5] for f in os.listdir(os.path.join(IMG, "headw")) if f.endswith(".webp")}
    want = {}
    rp = os.path.join(DATA, f"rosters-{label}.json")
    if os.path.exists(rp):
        for players in json.load(open(rp)).values():
            for a in players:
                want[a["id"]] = {"name": a["name"], "espn": a.get("headshot")}
    dp = os.path.join(DATA, f"deck-players-{label}.json")
    if os.path.exists(dp):
        for p in json.load(open(dp)):
            want.setdefault(p["id"], {"name": p["name"]})["nba"] = p.get("nbaId")
    sdir = os.path.join(IMG, "headw", label)
    seasonal = {f[:-5] for f in os.listdir(sdir)} if os.path.isdir(sdir) else set()
    todo = {pid: w for pid, w in want.items() if pid not in have and pid not in seasonal}
    out = os.path.join(IMG, "head")

    def one(item):
        pid, w = item
        path = os.path.join(out, f"{pid}.png")
        tried = []
        for url in ([f"https://cdn.nba.com/headshots/nba/latest/1040x760/{w['nba']}.png"]
                    if w.get("nba") else []) + [
                    w.get("espn") or
                    f"https://a.espncdn.com/i/headshots/nba/players/full/{pid}.png"]:
            r = grab(url, path)
            if not str(r).startswith("FAIL"):
                return pid, w["name"], r
            tried.append(r)
        return pid, w["name"], "FAIL " + " / ".join(tried)

    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(one, todo.items()))
    bad = [r for r in res if str(r[2]).startswith("FAIL")]
    print(f"  {label}: {len(want)} players, {len(want) - len(todo)} already had a photo, "
          f"{len(res) - len(bad)} fetched, {len(bad)} still without one")
    for b in bad[:6]:
        print("   ", b[1], b[2][:90])
    # Only when something new arrived: the two or three players with no photo anywhere
    # are retried every night, and on a fresh runner img/head does not exist at all.
    if len(res) > len(bad):
        optimise()


def _webp(png_bytes, width=560, quality=82):
    """The same conversion optimise() applies, in memory -- so a fresh download can be
    compared byte for byte with the photo already on disk."""
    import io
    from PIL import Image
    im = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=quality, method=6)
    return buf.getvalue()


def _same_picture(webp_bytes, path, tol=30, share=0.01):
    """Same photo, whatever encoder made the file? Compared by pixels, not bytes.

    Bytes worked on one machine and failed on the next: GitHub's runner has a different
    libwebp, so it re-encoded four unchanged photos into different bytes, called them
    new, and stopped re-checking them -- Isaac Jones's real new photo would never have
    been picked up. Under 1% of pixels off by more than 30/255 is the same picture."""
    import io
    from PIL import Image, ImageChops
    a = Image.open(io.BytesIO(webp_bytes)).convert("RGBA")
    b = Image.open(path).convert("RGBA")
    if a.size != b.size:
        return False
    hist = ImageChops.difference(a, b).convert("L").histogram()
    return sum(hist[tol:]) < share * a.size[0] * a.size[1]


def nba_roster_photos(label):
    """This season's official headshots, kept apart from last season's.

    cdn.nba.com serves one "latest" photo per player, and before 2026-27 it served last
    season's: Isaiah Joe was on our Pistons card in a Thunder jersey. The NBA has since
    published the new media-day photos -- 17 of Detroit's 18 had changed. They go in
    img/headw/<label>/ rather than over the shared files, because the shared file is
    also what LAST season's cards show: overwriting it would put Joe in Pistons white on
    the 2025-26 Thunder roster. build_cards lists this folder in the payload, and the
    template prefers it for that season only.

    NBA ids come from nba.com's standard team page (/team/<nbaTeamId>), the one layout
    all 30 teams share -- the team-branded /<slug>/roster pages are custom on seven of
    them. Matched to ESPN ids by name. A photo is fetched once per player, and again
    only if he changes team; one identical to the shared file is not duplicated.
    A failure on nba.com is reported and skipped, never fatal: the cards fall back to
    the shared photos.
    """
    import re
    import unicodedata

    def norm(x):
        x = unicodedata.normalize("NFKD", x or "")
        x = "".join(c for c in x if not unicodedata.combining(c)).lower()
        x = re.sub(r"[.,'`’-]", " ", x)            # nba.com writes "Ernest Udeh, Jr."
        x = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", " ", x)
        return re.sub(r"\s+", " ", x).strip()

    teams = json.load(open(os.path.join(DATA, "teams.json")))
    rp = os.path.join(DATA, f"rosters-{label}.json")
    if not os.path.exists(rp):
        print(f"  no rosters-{label}.json -- not a live season, nothing to do")
        return
    rosters = json.load(open(rp))
    start_year = label.split("-")[0]               # nba.com names 2026-27 "2026"
    mp = os.path.join(DATA, f"photos-{label}.json")
    known = json.load(open(mp)) if os.path.exists(mp) else {}
    sdir = os.path.join(IMG, "headw", label)
    os.makedirs(sdir, exist_ok=True)

    def page(ab):
        url = f"https://www.nba.com/team/{teams[ab]['nbaId']}"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                s = r.read().decode("utf8", "ignore")
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', s, re.S)
            rows = json.loads(m.group(1))["props"]["pageProps"]["team"]["roster"]
        except Exception as e:                       # noqa: BLE001
            return ab, None, f"{e}"[:70]
        rows = [x for x in rows if str(x.get("SEASON")) == start_year]
        return ab, rows, None

    with ThreadPoolExecutor(max_workers=6) as ex:
        pages = list(ex.map(page, teams))
    failed = [(ab, err) for ab, rows, err in pages if rows is None]

    matched, unmatched, todo = 0, [], []
    for ab, rows, _ in pages:
        if not rows:
            continue
        ours = {norm(a["name"]): a["id"] for a in rosters.get(ab, [])}
        for x in rows:
            eid = ours.get(norm(x.get("PLAYER")))
            if not eid:
                unmatched.append(f"{ab} {x.get('PLAYER')}")
                continue
            matched += 1
            prev = known.get(eid)
            known[eid] = {"nba": x["PLAYER_ID"], "team": ab,
                          "same": (prev or {}).get("same", False)}
            fresh = not prev or prev.get("team") != ab
            # "same" means the NBA had not yet posted his new photo when we last looked
            # (Isaac Jones, still in Kings purple on opening night). Those few are
            # looked at again every run, so the new one lands when it is published.
            have = os.path.exists(os.path.join(sdir, f"{eid}.webp"))
            if fresh or not have:
                todo.append((eid, x["PLAYER_ID"], x.get("PLAYER")))

    def fetch(job):
        eid, nid, name = job
        url = f"https://cdn.nba.com/headshots/nba/latest/1040x760/{nid}.png"
        req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                   "Referer": "https://www.nba.com/"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                b = r.read()
            if len(b) < 2000:
                return eid, name, "FAIL tiny"
            w = _webp(b)
        except Exception as e:                       # noqa: BLE001
            return eid, name, f"FAIL {e}"[:70]
        base = os.path.join(IMG, "headw", f"{eid}.webp")
        if os.path.exists(base) and _same_picture(w, base):
            return eid, name, "same"
        with open(os.path.join(sdir, f"{eid}.webp"), "wb") as f:
            f.write(w)
        return eid, name, "new"

    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(fetch, todo))
    for eid, name, r in res:
        if r == "same":
            known[eid]["same"] = True
    with open(mp, "w") as f:
        json.dump(dict(sorted(known.items())), f, separators=(",", ":"))

    n_new = sum(1 for r in res if r[2] == "new")
    n_same = sum(1 for r in res if r[2] == "same")
    bad = [r for r in res if str(r[2]).startswith("FAIL")]
    print(f"  nba.com {label}: {30 - len(failed)}/30 team pages, {matched} players matched, "
          f"{len(unmatched)} unmatched; checked {len(todo)}: {n_new} new season photos, "
          f"{n_same} unchanged, {len(bad)} failed")
    for ab, err in failed[:4]:
        print(f"    team page {ab} failed: {err}")
    if unmatched:
        print(f"    unmatched (no ESPN roster entry by that name): {unmatched[:6]}")
    for b in bad[:4]:
        print(f"    {b[1]}: {b[2]}")


def optimise(width=560, quality=82):
    """PNG cutouts -> webp at card size.

    The 1040x760 originals are 23 MB for 120 players, which is far too much for a page
    that shows 60 of them. Transparency must survive, so RGBA webp, not JPEG.
    """
    from PIL import Image
    src = os.path.join(IMG, "head")
    dst = os.path.join(IMG, "headw")
    os.makedirs(dst, exist_ok=True)
    if not os.path.isdir(src):               # gitignored: absent on a fresh checkout
        return
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
    elif cmd == "season":
        season_heads(sys.argv[2])
    elif cmd == "nbaroster":
        nba_roster_photos(sys.argv[2])
    else:
        heads(int(sys.argv[2]) if len(sys.argv) > 2 else 120)

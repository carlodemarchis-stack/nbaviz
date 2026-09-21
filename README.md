# NBA Season Film + Season Towers

The NBA entry in the AGWAS sport-viz family. One app, two ways to read a season:

- **`index.html` — the Film.** 135 cards: a cover, one per franchise in order of record,
  the 100 leading scorers, then four charts. Horizontal, deep-linkable, keyboard-driven.
- **`towers.html` — the Towers.** All 30 teams as vertical stacks on a shared baseline:
  **wins build up, losses hang down, games still to play hang from the ceiling.**
  A slider replays the season game by game and the teams re-sort live.

Both carry a Film/Towers toggle and a season switcher. Built for **2025-26** (complete)
and **2026-27** (published schedule, nothing played yet).

## Build it

```bash
python3 tools/fetch_espn.py teams
python3 tools/fetch_espn.py schedule 2026      # ESPN names a season by the year it ENDS
python3 tools/fetch_espn.py schedule 2027
python3 tools/fetch_espn.py playoffs 2026
python3 tools/fetch_players.py 2026            # 578 season lines + playoffs
python3 tools/fetch_boxscores.py 2025-26       # 1,231 games, ~70s
python3 tools/build_players.py 2025-26         # season-accurate teams + NBA ids
python3 tools/fetch_images.py crests
python3 tools/fetch_images.py heads 120
python3 tools/fetch_images.py optimise         # 22.6 MB PNG -> 2.9 MB webp
python3 tools/validate.py 2025-26              # MUST pass
python3 tools/build_cards.py 2025-26
python3 tools/build_cards.py 2026-27
python3 render.py 2025-26                      # writes every season's pages
```

Raw payloads cache in `scratch/` (gitignored), so re-running is cheap. `render.py` writes
`index-<season>.html` / `towers-<season>.html` for each built season, plus `index.html` /
`towers.html` as copies of the season you pass it.

## The three data sources, and why they are three

Their client requirements are mutually exclusive — a shared fetch helper would break one.

| Source | Reached by | Carries |
|---|---|---|
| **ESPN** `site.api.espn.com` | plain curl | teams, standings, schedules, results, box scores, player lines |
| **stats.nba.com** | a real browser **on an nba.com page** | deep stats; only genuinely unique thing is shot charts |
| **cdn.nba.com** | plain curl | crest SVGs, 1040×760 headshot cutouts |

ESPN is the backbone **because it is the only one that works headlessly** — when 2026-27
tips off on 22 Oct 2026, the update job has to run without a browser.

### Two counter-intuitive client rules

- **ESPN 403s a browser User-Agent**, and 403s any custom one. It serves `curl/x.y` and
  `Python-urllib/x.y`. So `fetch_espn.py` sends **no UA override**. Adding a Chrome UA —
  the reflexive fix — is exactly what breaks it.
- **stats.nba.com is the opposite**: it hangs for curl (Akamai fingerprinting) and for any
  origin other than nba.com. Fetching works from a browser pane sitting on nba.com;
  *writing those bytes to disk* is still unsolved (see `tools/harvest_server.py`).

## Traps this pipeline already handles

Each of these produced plausible-looking wrong output once.

1. **Postponed games appear twice.** ESPN keeps the postponed shell *and* its makeup, so
   10 teams looked like they played 83 games. Drop `status.type.name == STATUS_POSTPONED`.
2. **The NBA Cup Championship counts for nobody** — not the team's record, not a player's
   season stats. Flagged `counts:false`; excluded from W/L, towers and game logs, but kept
   on the team card as a trophy.
3. **2026-27 publishes only 80 games per team, and that is correct.** The league sets each
   team's last two after the Cup group stage resolves in December.
4. **ESPN has no season-accurate roster.** Every roster endpoint returns the *current*
   roster, which after the 2026 offseason put Jaylen Brown on Philadelphia and Paul George
   on Boston beside their 2025-26 stats. Teams are derived from box scores instead.
5. **`athlete.active` does not mean "played in this game"** — it means "on the current
   roster". Huerter is `active:false` in a game he played 32 minutes of. Filtering on it
   deleted real players from 22 games.
6. **Known upstream gap:** 7 Chicago games where ESPN omits a player's line entirely (the
   listed players total 230 of the required 240 minutes). Allowlisted in `validate.py`;
   the towers are unaffected because they use final scores.

## Validation

`tools/validate.py <season>` exits non-zero on failure. Every check exists because
something went wrong once:

```
30 teams · a crest per team · every team at 82 counting games
records match the official standings          30/30
box score points reconcile to final scores    2,462 team-games
a box score for every played game             1,231
every scoring player appears in a box score   578
```

`build_cards.py` additionally asserts every player's game log is exactly as long as his
official games-played — the check that caught the Cup final leaking into 6 players' logs —
and that all 6,908 game-log pointers resolve to a game played on the right date.

## Layout rules that are load-bearing

- **The towers' baseline is shared by all 30 teams.** Cell size is derived from the
  *tallest column that can occur* (`MAXNEED`), not an average, and the label block under
  each tower is a **fixed 50px with fixed line boxes** — the champion's ★ glyph made its
  label 3px taller and lifted that one team's baseline off the line.
- **`content-visibility:auto` on `.card`** keeps 135 full-screen cards out of the render
  tree. Without it this format crashes mobile Safari.
- **The hover panel is `position:fixed`, outside the cards.** Anything drawn inside a
  chart panel is clipped by its own overflow.
- **A player's game log carries points only.** Opponent, result and final score come from
  a `[team, game]` pointer into the team's own games list, which the payload already
  ships — copying them onto all 6,908 player-games cost 100 KB for nothing. `build_cards`
  checks every pointer lands on a game played on that log entry's date.
- **The biggest-nights columns drop their names below 1180px.** 100 columns need about
  1200px before a 9px vertical name fits in one; narrower, it renders as glyph slices.
- **On mobile the cards are a flex column, not a one-column grid.** The grid box has a
  definite height, so auto rows share it and a `min-height:0` column collapses to 0px
  while its content spills over the next one.
- `scrollTo({behavior:'auto'})` defers to CSS `scroll-behavior`, which is `smooth` here —
  use `'instant'` for real jumps.

## Design

House style: `--bg:#070910`, Helvetica 300/700, glass panels, radius 20. Accent
**`--acc:#e0453f`** (NBA red — distinct from F1 `#00d7b6`, tennis `#f2c14e`, golf
`#f2952e`, NFL `#4d94e0`). Team colours are lifted toward readability when near-black
(San Antonio, Brooklyn) via `winColor()`.

Live at **https://nba.aguywithascarf.com** (repo `carlodemarchis-stack/nbaviz`).

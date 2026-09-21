# NBA Season Film + Season Towers

The NBA entry in the AGWAS sport-viz family. One app, two ways to read a season:

- **`index.html` — the Film.** 135 cards, in five sections: a cover, the 100 leading
  scorers, the three charts that rank players, the 30 franchises in order of record, then
  the chart that ranks teams. Horizontal, deep-linkable, keyboard-driven.
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
5. **The jersey number is season-accurate only from the box scores.** ESPN's athlete
   endpoint serves the number a player wears *now* — the same trap as the roster — and
   serves none at all for anyone unsigned at fetch time. That left 10 of the 100 carded
   players with no number and **6 with the wrong one**: Giannis showed as 7, having worn
   34 in 2025-26. Every athlete in a box score carries the number he wore that night.
6. **`athlete.active` does not mean "played in this game"** — it means "on the current
   roster". Huerter is `active:false` in a game he played 32 minutes of. Filtering on it
   deleted real players from 22 games.
7. **Known upstream gap:** 7 Chicago games where ESPN omits a player's line entirely (the
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
  checks every pointer lands on a game played on that log entry's date. The same entry
  carries that night's threes and free throws, which is what stacks the game chart into
  2PT / 3PT / FT; everything left over came from twos.
- **Both photo-box numbers are sized by the box**, via a size container query on `.shot`:
  jersey `min(74cqh, 42cqw)` on the right, rank at half that on the left. Bounded by
  height *and* width — rank 100 is the deck's only three-digit number and gets a narrower
  `--rw` inline. The `clamp()`s are the fallback.
- **The player's number, team and bio are ONE line**, truncated rather than wrapped. A
  traded player shows his split (`LAC 44 → CLE 26`) instead of the current team's full
  name, which is what used to push five of the hundred past the end of the line.
- **Jersey big on the right in the team's colour** (through `winColor()`, so a near-black
  primary is lifted; opacity rather than an alpha, because winColor returns `#rrggbb`,
  `rgb()` or a `var()`), rank half-size on the left captioned "by points" — a bare number
  reads as a jersey, so the rank has to say what it is.
- **The points chart has a Split / Avg switch** beside its title: Split stacks each column
  by 2PT / 3PT / FT, Avg colours the whole bar green at or above the average, red below,
  gold for the best night. Rebounds and assists have no split, so they are always drawn
  the Avg way and the switch is hidden there.
- **Each bar is topped with a W or an L.** HTML overlay, not `<text>` — same reason as the
  axis labels. Neutral colours on purpose: green and red already mean above/below average
  on that very chart. Hidden below 1160px, where 82 columns stop leaving ~9px each.
- **The game chart draws every game his team played while he was on it**, not just his
  appearances — a missed game is a gap with a faint baseline tick. The calendar is derived
  client-side (`calendar()`) from the `[team, game]` pointers plus the team fixture lists
  the payload already ships, so it costs nothing. A traded player's calendar is his first
  team's games up to the day he first played for the second, then the second's — so it is
  **not** 82 (two schedules do not line up) and the caption counts it.
- **The game chart has Points / Rebounds / Assists / Minutes tabs**, each on its own
  deck-wide scale (99th percentile of season highs; gridlines every 10 for points and
  minutes, every 5 for rebounds and assists). Minutes has no precomputed high in the
  payload — it comes off the game log, which is already there. Only the
  card you are looking at is re-rendered on a switch — redrawing all 100 charts is waste —
  so `paint()` calls `paintLog(cur)` and each card catches up when you land on it.
- **The biggest-nights columns drop their names below 1180px.** 100 columns need about
  1200px before a 9px vertical name fits in one; narrower, it renders as glyph slices.
- **Mobile overrides for the left column need TWO classes.** `.pleft .shot` and
  `.pleft > .panel` are two-class selectors, so a bare `.shot{min-height:44vh}` in the
  media query never applied: on a phone the portrait was sized as half of a column with no
  definite height, and the court svg drew 240px tall inside a 118px panel.
- **On mobile the cards are a flex column, not a one-column grid.** The grid box has a
  definite height, so auto rows share it and a `min-height:0` column collapses to 0px
  while its content spills over the next one.
- `scrollTo({behavior:'auto'})` defers to CSS `scroll-behavior`, which is `smooth` here —
  use `'instant'` for real jumps.

## Design

**Two palettes that must not collide.** The shot chart's cold→hot ramp is steel blue →
grey → red. The shot-type trio (`--two` violet `#7a5af5`, `--three` teal `#2fd4d0`, `--ft`
pink `#e879c4`) used to be *exactly* those three hues, so one card said blue-grey-red
twice meaning two different things. The trio now clears the ramp, the win green, the loss
red and the best-night gold by at least 31° of hue, and sits 67–140° apart internally.
Anything new about where points came from uses those three variables.

House style: `--bg:#070910`, Helvetica 300/700, glass panels, radius 20. Accent
**`--acc:#e0453f`** (NBA red — distinct from F1 `#00d7b6`, tennis `#f2c14e`, golf
`#f2952e`, NFL `#4d94e0`). Team colours are lifted toward readability when near-black
(San Antonio, Brooklyn) via `winColor()`.

Live at **https://nba.aguywithascarf.com** (repo `carlodemarchis-stack/nbaviz`).

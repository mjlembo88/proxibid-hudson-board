# Hudson auction board · Proxibid + HiBid

Mobile-first watch board for auctions near 14515 Giddyup Pl, Hudson FL.

Live: https://mjlembo88.github.io/proxibid-hudson-board/

## Tabs

1. **Lots / watch** — Proxibid + HiBid lots (photo-first), platform filter, ★ watch, hard max $, 100/page + Next at bottom
   - **Grid / List toggle** (saved in localStorage `proxibid-hudson-lots-view-v1`; default Grid on phones, List on desktop). Grid = 2 square thumbnails per row with one-line title + bid and a ★ overlay; tap a tile to open the full card (hard max $ lives there) in a sheet. Android back closes the sheet.
2. **Auctions** — Proxibid + HiBid map/table, platform filter + badges, ★ favorite auction
3. **Favorites** — starred auctions + watched lots; export JSON

## Rules

- **Hard max bid** = Mark’s ceiling for Auction Desk (never bid above)
- Board does **not** place bids

## Data

| File | Role |
|------|------|
| `auctions.json` | Proxibid auctions (map) |
| `hibid-auctions.json` | HiBid auctions within 50 mi |
| `lots.json` | Proxibid lot catalog scrape |
| `hibid-lots.json` | Selected HiBid lot catalogs |
| `build-info.json` | Last build: time (ET), auctions/lots removed as expired, unknown end dates |

## Local

```bash
cd /workspace/proxibid/dashboard && python3 -m http.server 8766
```

## Build / publish

```bash
cd /workspace/proxibid/dashboard
python3 build.py                        # writes the site to ../pages-publish (git clone of this repo, main = Pages)
python3 build.py --check-hibid unknown  # optionally confirm HiBid auctions with no parseable end date via GraphQL
cd ../pages-publish && git add -A && git commit -m "..." && git push
```

`build.py` drops expired auctions and lots at build time: an auction is removed once the end of its
end date (23:59:59 America/New_York) is before the build time. HiBid auctions confirmed closed via
GraphQL (`hibid-live-state.json`, lots `isClosed=true`) are dropped; auctions with no end date are kept
unless confirmed closed and are logged in `build-info.json`. New catalogs can be dropped into
`incoming/proxibid-lots-*.json` / `incoming/proxibid-auctions-*.json` (same shape as `lots.json` /
`auctions.json`) and are merged on the next build. Saved Proxibid catalog HTML
(`/workspace/proxibid/new-catalogs/<aid>-p<page>.html`) is turned into those files by
`python3 /workspace/proxibid/scripts/parse_proxibid_catalogs.py` (never fetches proxibid.com).

Lot tags (build time, keyword rules in `build.py` `lot_tags`): `mower` (riding / zero-turn / stand-on /
lawn tractor), `walk-behind mower` (commercial walk-behinds), `RC mower` (remote-control / crawler / robotic),
`tractor + mower` (tractor sold with deck / rotary cutter / bush hog), `mower parts`. Skid steers / loaders never get a mower tag. Lots tab → **Tag** filter.
Auctions flagged `always_show` (Mark's picks beyond 50 mi) stay on the map and are marked "beyond N mi".

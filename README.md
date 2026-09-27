# Hudson auction board · Proxibid + HiBid

Mobile-first watch board for auctions near 14515 Giddyup Pl, Hudson FL.

Live: https://mjlembo88.github.io/proxibid-hudson-board/

## Tabs

1. **Lots / watch** — Proxibid + HiBid lots (photo-first), platform filter, ★ watch, hard max $, 100/page + Next at bottom
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
`auctions.json`) and are merged on the next build.

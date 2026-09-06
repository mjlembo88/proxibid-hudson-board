# Proxibid · Hudson watch board

Mobile-first lot watch board + map for auctions within 50 mi of 14515 Giddyup Pl, Hudson FL.

Live: https://mjlembo88.github.io/proxibid-hudson-board/

## Open locally

```bash
cd /workspace/proxibid/dashboard
python3 -m http.server 8766
```

→ http://127.0.0.1:8766/

## UI

- **Lots / watch** — photo-first cards (large thumbnail on top), auction picker, search, filters, ★ watch, hard max $, export
- **Auctions map** — pins + table

## Rules

- **Hard max bid** = Mark’s ceiling for Auction Desk (never bid above)
- Page does **not** place bids

## Data

| File | Source |
|------|--------|
| `auctions.json` | `/workspace/proxibid/hudson-50mi-upcoming.json` |
| `lots.json` | `/workspace/proxibid/lots-raw.json` |

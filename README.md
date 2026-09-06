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

## Local

```bash
cd /workspace/proxibid/dashboard && python3 -m http.server 8766
```

#!/usr/bin/env python3
"""Build the Hudson auction board (Proxibid + HiBid) for GitHub Pages.

    python3 build.py                       # src=this dir, out=../pages-publish (the Pages git clone)
    python3 build.py --out .               # prune the source dir in place (idempotent)
    python3 build.py --check-hibid unknown # also ask HiBid GraphQL about auctions with no parseable end date
    python3 build.py --check-hibid all     # ...or about every HiBid auction (1 small query each, 1s apart)
    python3 build.py --dry-run             # report only, write nothing

Expiry filter (runs on every build):
  * "now" = build time in America/New_York (override with --now ISO8601 for testing).
  * Each auction gets an end date:
      - explicit `end_local` / `datetime_end` (ISO8601) if present;
      - Proxibid: `datetime_local` (sale date) or lots.json `start_time`; live sales end that day;
      - HiBid: the latest date found in `datetime_display` ("Date(s) 9/25/2026 - 9/29/2026 ...
        closes Sep 30" -> Sep 30), or `eventDateEnd` from hibid-live-state.json.
    An auction is expired when the END OF ITS END DAY (23:59:59 ET) is before now, so nothing is dropped
    while it can still be running that day.
  * hibid-live-state.json (written by --check-hibid) overrides dates: confirmed closed -> drop,
    confirmed open (checked within the last 24h) -> keep.
  * Auctions with no end date: kept unless confirmed closed, and logged in build-info.json + stdout.
  * Individual lots whose `status` is closed/sold/passed/ended are dropped too.
  * Every kept lot gets `tags` from lot_tags(): "mower" (riding / zero-turn / stand-on / lawn tractor),
    "walk-behind mower", "RC mower", "tractor + mower", "mower parts"; counts go to build-info.json tag_counts.
  * Map markers (auctions.json, hibid-auctions.json, and the fallback copy embedded in index.html)
    and lot catalogs (lots.json, hibid-lots.json) are filtered with the same rule.

New catalogs: any `incoming/proxibid-lots-*.json` (same shape as lots.json: {"auctions":[{aid,title,url,
start_time,lots:[...]}]}) and `incoming/proxibid-auctions-*.json` (same shape as auctions.json) are merged
(by aid, incoming wins) before filtering. Same for `incoming/hibid-lots-*.json` / `incoming/hibid-auctions-*.json`.
"""
import argparse, datetime as dt, glob, json, os, re, shutil, sys, time, urllib.error, urllib.request
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = ["app.js", "styles.css", "README.md", "build.py", "hibid-live-state.json"]
CLOSED_LOT_STATUS = {"closed", "sold", "passed", "ended", "unsold", "withdrawn"}
MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

# ------------------------------------------------------------------ end-date parsing
def _eod(d):
    return dt.datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=ET)

def parse_iso(s):
    if not s:
        return None
    try:
        x = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return x.date() if x.tzinfo is None else x.astimezone(ET).date()

def dates_in_text(text, default_year):
    """All calendar dates mentioned in free text (M/D/YYYY, M/D, 'September 30th[, 2026]', 'Sep 30')."""
    out = []
    t = text or ""
    for m, d, y in re.findall(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t):
        y = int(y) if y else default_year
        y = y + 2000 if y < 100 else y
        try:
            out.append(dt.date(y, int(m), int(d)))
        except ValueError:
            pass
    for mon, d, y in re.findall(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?", t, re.I):
        try:
            out.append(dt.date(int(y) if y else default_year, MONTHS[mon.lower()[:3]], int(d)))
        except ValueError:
            pass
    return out

def auction_end(a, default_year, live=None):
    """Return (end_date or None, source string)."""
    for k in ("end_local", "datetime_end", "end_time"):
        d = parse_iso(a.get(k))
        if d:
            return d, k
    if live and live.get("eventDateEnd"):
        d = parse_iso(live["eventDateEnd"])
        if d:
            return d, "hibid-live-state eventDateEnd"
    ds = dates_in_text(a.get("datetime_display") or "", default_year)
    if ds:
        return max(ds), "datetime_display (latest date)"
    d = parse_iso(a.get("datetime_local"))
    if d:
        return d, "datetime_local (sale date)"
    ds = dates_in_text(a.get("start_time") or "", default_year)
    if ds:
        return max(ds), "start_time (sale date)"
    return None, None

def _fresh(lv, now, hours=24):
    try:
        t = dt.datetime.fromisoformat(lv.get("checked_at"))
    except (TypeError, ValueError):
        return False
    t = t.replace(tzinfo=ET) if t.tzinfo is None else t
    return dt.timedelta(0) <= now - t <= dt.timedelta(hours=hours)

# ------------------------------------------------------------------ HiBid live check (GraphQL LotSearch)
HIBID_HOST = "https://florida-b.hibid.com"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
LOT_QUERY = """query LotSearch($input: LotSearchInput!, $pageNumber: Int!, $pageLength: Int!, $sortDirection: SortDirection) {
  lotSearch(input: $input, pageNumber: $pageNumber, pageLength: $pageLength, sortDirection: $sortDirection) {
    pagedResults { totalCount filteredCount results {
      id lotNumber lotState { status isClosed timeLeft }
      auction { id eventName eventDateBegin eventDateEnd }
    } } } }"""

def hibid_live_state(aid):
    """One small LotSearch for an auction (same query shape as scripts/mower_search.py)."""
    v = {"input": {"auctionId": int(aid), "category": None, "searchText": None, "zip": None, "miles": None,
                   "shippingOffered": False, "countryName": None, "status": None, "sortOrder": "LOT_NUMBER",
                   "filter": "ALL", "isArchive": False, "dateStart": None, "dateEnd": None, "countAsView": False,
                   "hideGoogle": False, "eventItemIds": None},
         "pageNumber": 1, "pageLength": 5, "sortDirection": "ASC"}
    body = json.dumps({"operationName": "LotSearch", "query": LOT_QUERY, "variables": v}).encode()
    req = urllib.request.Request(HIBID_HOST + "/graphql", body, {
        "User-Agent": UA, "Content-Type": "application/json", "Origin": HIBID_HOST, "Referer": HIBID_HOST + "/"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        return {"error": repr(e)}
    pr = (((d.get("data") or {}).get("lotSearch") or {}).get("pagedResults")) or {}
    res = pr.get("results") or []
    closed = [bool((x.get("lotState") or {}).get("isClosed")) for x in res]
    return {
        "checked_at": dt.datetime.now(ET).isoformat(timespec="seconds"),
        "totalCount": pr.get("totalCount"),
        "sample_isClosed": closed,
        "sample_status": [(x.get("lotState") or {}).get("status") for x in res],
        "closed": (all(closed) if closed else None),
        "eventDateEnd": (res[0].get("auction") or {}).get("eventDateEnd") if res else None,
    }

# ------------------------------------------------------------------ lot tags (keyword rules on title + start of description)
# Tags (at most one per lot):
#   "mower"             riding / zero-turn / stand-on mowers, lawn & garden tractors
#   "walk-behind mower" commercial walk-behinds (JD 632M/636M/648M, "pedestrian"/walk-behind + commercial brand,
#                       hydro, zero-turn or a 32"+ deck). Consumer push / self-propelled mowers get nothing.
#   "RC mower"          remote-control / crawler / robotic mowers (explicit words, or the LM1000Q/LM1200Q
#                       crawler-mower model family sold as SDLOOL SL-LMxxxxQ / Captok CK-LMxxxxQ, or egn EGxxx)
#   "tractor + mower"   farm/utility tractors sold with a mower deck, rotary cutter, bush hog, finish mower,
#                       flail mower or Land Pride RCF/RCR cutter
#   "mower parts"       decks, blades, belts etc. sold without the machine
# Never tagged: toys/models; skid steers, track/wheel loaders, backhoes, excavators, dozers, dumpers, mulchers,
# golf carts etc. (even with a brand/model match or "stand on" in the title). A plain "loader" only blocks
# tags other than "tractor + mower" (tractors with a front loader and a mower deck still count).
_MOW = r"mow(?:er|ers|ing)?"
_MOWISH = re.compile(_MOW + r"|zero[- ]?turn|\bZTR\b|ZTrak|quik ?trak", re.I)
_TOY = re.compile(r"\b(?:toys?|die-?cast|diecast|replica|ertl|1:\d+|1/\d+|scale model|figurine|ornament|decal|sticker|sign)\b", re.I)
_NEVER = re.compile(r"skid[- ]?steer|skidsteer|skid loader|track(?:ed)? loader|wheel(?:ed)? loader|compact track|"
                    r"backhoe|excavator|dozer|dumper|mulcher|compactor|tamper|trencher|golf cart|forklift|telehandler|"
                    r"\bUTV\b|\bRTV\b|to suit (?:a )?skid", re.I)
_LOADER = re.compile(r"\bloaders?\b", re.I)
_TRACTOR = re.compile(r"(?<!lawn )(?<!garden )(?<!yard )\btractors?\b", re.I)
_TRACTOR_IMPL = re.compile(r"mower deck|rotary cutter|bush ?hog|finish(?:ing)? mower|flail mower|brush cutter|"
                           r"\bRC[FR]\d{3,4}\b|land ?pride|with (?:a )?mower|w/ ?mower|\bmower\b", re.I)
_RC = re.compile(r"remote[- ]?control(?:led)?|\bRC\b|radio[- ]control|crawler|robotic|automower|slope mower", re.I)
_RC_MODEL = re.compile(r"\b(?:SL-|CK-)?LM1[02]00Q\b|\begn\b.{0,40}\bEG\d{3}\b", re.I)
_STAND_ON = re.compile(r"stand[- ]?on\b[^,;]{0,25}" + _MOW + r"|quik ?trak|grandstand|\bstander\b|\bstaris\b|v-ride", re.I)
_WALK = re.compile(r"walk[- ]?behind|pedestrian|\bhydro[- ]?walk", re.I)
_WALK_MODEL = re.compile(r"\bjohn deere\s+6[34]\dM?\b|\bJD\s*6[34]\dM\b|turf tracer|\bexmark\s+(?:viking|metro)|\bscag\s+SWZ?U?\d", re.I)
_COMMERCIAL = re.compile(r"john deere|exmark|scag|toro|ferris|wright|bobcat|gravely|hustler|kubota|snapper pro|"
                         r"bad boy|zero[- ]?turn|hydro(?:static)?|commercial|\b(?:3[2-9]|[4-6]\d)\s*(?:\"|”|in\b|inch)", re.I)
_RIDING = re.compile(r"zero[- ]?turn|\bZTR\b|\bz[- ]?turn\b|riding (?:lawn )?mower|ride[- ]on (?:lawn )?mower|"
                     r"lawn tractor|garden tractor|yard tractor|\bZTrak\b|time ?cutter|z[- ]?master|lazer z|turf tiger|"
                     r"tiger cat|\bscag\b.*\b(?:patriot|freedom|cheetah)\b|\bhustler\b.*\b(?:raptor|super z|fastrak|x-one)\b|"
                     r"\bbad boy\b.*" + _MOW + r"|\bkubota\s+Z[G]?\d{3}|\bjohn deere\s+(?:Z\d{3}[A-Z]?|X\d{3}|[DES]1\d{2}|L[ATX]\d{3})\b|"
                     r"\bcub cadet\b.*\b(?:ZT\d|XT\d|LTX)|\bhusqvarna\s+(?:MZ|Z2|YTH?|TS)\d|\bgravely\b.*\b(?:ZT|pro-?turn)|"
                     r"\bferris\b.*\b(?:IS|ISX)\s?\d|\bgrasshopper\b.*" + _MOW + r"|\bwalker\b.*" + _MOW, re.I)
_PARTS = re.compile(_MOW + r"\s+(?:deck|blades?|belts?|spindles?|parts?|tires?|seat|cover)|"
                    r"\b(?:deck|blades?|belts?|spindles?)\b.*\bfor\b.*" + _MOW, re.I)

def lot_tags(lot):
    title = str(lot.get("title") or "")
    head = str(lot.get("description") or "")[:300]
    full = title + " " + head
    if _TOY.search(title) or _NEVER.search(full):
        return []
    if _TRACTOR.search(full) and _TRACTOR_IMPL.search(full) and not _RIDING.search(title):
        return ["tractor + mower"]
    if _LOADER.search(full):
        return []
    if not (_MOWISH.search(full) or _RIDING.search(title) or _STAND_ON.search(title) or _WALK_MODEL.search(title)):
        return []
    if _MOWISH.search(full) and (_RC.search(full) or _RC_MODEL.search(title)):
        return ["RC mower"]
    if _PARTS.search(title):
        return ["mower parts"]
    if _STAND_ON.search(full):
        return ["mower"]
    if _WALK_MODEL.search(title) or _WALK.search(full):
        return ["walk-behind mower"] if (_WALK_MODEL.search(title) or _COMMERCIAL.search(full)) else []
    if _RIDING.search(title) or (_MOWISH.search(full) and _RIDING.search(head)):
        return ["mower"]
    return []


# ------------------------------------------------------------------ io helpers
def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)

def dump(path, data, compact=False):
    with open(path, "w") as f:
        if compact:
            json.dump(data, f, separators=(",", ":"), ensure_ascii=False)
        else:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")

def merge_incoming(base_list, key, pattern, src):
    by = {str(x.get(key)): x for x in base_list}
    added = []
    for p in sorted(glob.glob(os.path.join(src, "incoming", pattern))):
        doc = load(p, {}) or {}
        if doc.get("scraped_at"):
            added.append(("scraped_at", doc["scraped_at"]))
        for x in doc.get("auctions") or []:
            by[str(x.get(key))] = x
            added.append((os.path.basename(p), str(x.get(key))))
    return list(by.values()), added

# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=HERE)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(HERE), "pages-publish"))
    ap.add_argument("--now", help="ISO8601 override for build time (default: now, ET)")
    ap.add_argument("--check-hibid", choices=["none", "unknown", "all"], default="none")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    src, out = os.path.abspath(args.src), os.path.abspath(args.out)
    now = (dt.datetime.fromisoformat(args.now) if args.now else dt.datetime.now(ET))
    now = now.replace(tzinfo=ET) if now.tzinfo is None else now.astimezone(ET)
    year = now.year

    px_auc = load(os.path.join(src, "auctions.json"))
    hb_auc = load(os.path.join(src, "hibid-auctions.json"), {"auctions": []})
    px_lots = load(os.path.join(src, "lots.json"))
    hb_lots = load(os.path.join(src, "hibid-lots.json"), {"auctions": []})
    live_path = os.path.join(src, "hibid-live-state.json")
    live = load(live_path, {}) or {}
    live_aucs = live.setdefault("auctions", {})

    incoming = []
    for doc, key, pat in ((px_auc, "id", "proxibid-auctions-*.json"), (px_lots, "aid", "proxibid-lots-*.json"),
                          (hb_auc, "id", "hibid-auctions-*.json"), (hb_lots, "aid", "hibid-lots-*.json")):
        doc["auctions"], added = merge_incoming(doc.get("auctions") or [], key, pat, src)
        stamps = [v for k, v in added if k == "scraped_at"]
        added = [(k, v) for k, v in added if k != "scraped_at"]
        if stamps:  # show the newest data time in the UI's "scraped" label
            doc["scraped_at"] = max(stamps + ([doc["scraped_at"]] if doc.get("scraped_at") else []),
                                    key=lambda t: dt.datetime.fromisoformat(t.replace("Z", "+00:00")))
        incoming += added

    # Metadata used to date lot catalogs: map entries first, catalog fields as fallback.
    meta = {}
    for platform, doc, key in (("Proxibid", px_auc, "id"), ("HiBid", hb_auc, "id")):
        for a in doc["auctions"]:
            meta[(platform, str(a[key]))] = a
    for platform, doc in (("Proxibid", px_lots), ("HiBid", hb_lots)):
        for a in doc["auctions"]:
            meta.setdefault((platform, str(a["aid"])), a)

    # Optional polite live check against HiBid.
    if args.check_hibid != "none":
        targets = []
        for (platform, aid), a in meta.items():
            if platform != "HiBid":
                continue
            d, _ = auction_end(a, year)
            if args.check_hibid == "all" or d is None:
                targets.append(aid)
        for i, aid in enumerate(sorted(set(targets))):
            if i:
                time.sleep(1.0)
            live_aucs[aid] = hibid_live_state(aid)
            print(f"[hibid-live] {aid}: {live_aucs[aid]}")
        live["updated_at"] = now.isoformat(timespec="seconds")

    decisions = {}  # (platform, aid) -> dict

    def decide(platform, aid):
        k = (platform, str(aid))
        if k in decisions:
            return decisions[k]
        a = meta.get(k, {})
        lv = live_aucs.get(str(aid)) if platform == "HiBid" else None
        end, why = auction_end(a, year, lv)
        rec = {"platform": platform, "aid": str(aid), "title": a.get("title"), "seller": a.get("seller"),
               "end_date": end.isoformat() if end else None, "end_source": why}
        if lv and lv.get("closed") is True:
            rec.update(keep=False, reason="HiBid live state: lots isClosed=true")
        elif lv and lv.get("closed") is False and _fresh(lv, now):
            # "open" is only trusted for 24h; a stale snapshot must not keep an auction alive forever
            rec.update(keep=True, reason="HiBid live state: lots open (checked " + lv.get("checked_at", "?") + ")")
        elif end is None:
            rec.update(keep=True, reason="unknown end date, not confirmed closed (kept)")
        elif _eod(end) < now:
            rec.update(keep=False, reason=f"ended {end.isoformat()} (before {now:%Y-%m-%d %H:%M} ET)")
        else:
            rec.update(keep=True, reason=f"ends {end.isoformat()}")
        decisions[k] = rec
        return rec

    report = {"built_at": now.isoformat(timespec="seconds"), "rule": "drop auction if 23:59:59 ET of its end date < build time; drop lots of dropped auctions and lots with closed status; unknown end date kept unless HiBid live state says closed",
              "incoming_merged": incoming, "map_removed": [], "map_kept": [], "lots_removed": [], "lots_kept": [], "unknown_end_date": [], "tag_counts": {}}

    for platform, doc in (("Proxibid", px_auc), ("HiBid", hb_auc)):
        kept = []
        for a in doc["auctions"]:
            r = decide(platform, a["id"])
            (kept.append(a) if r["keep"] else None)
            report["map_kept" if r["keep"] else "map_removed"].append(r)
        doc["auctions"] = kept

    for platform, doc in (("Proxibid", px_lots), ("HiBid", hb_lots)):
        kept = []
        for a in doc["auctions"]:
            r = decide(platform, a["aid"])
            lots = a.get("lots") or []
            if not r["keep"]:
                report["lots_removed"].append(dict(r, lots=len(lots)))
                continue
            live_lots = [l for l in lots if str(l.get("status") or "").lower() not in CLOSED_LOT_STATUS]
            if len(live_lots) != len(lots):
                report["lots_removed"].append(dict(r, lots=len(lots) - len(live_lots), reason="lot status closed/sold/passed"))
            for l in live_lots:
                l["tags"] = lot_tags(l)
                for t in l["tags"]:
                    report["tag_counts"].setdefault(f"{platform}:{a['aid']}", {}).setdefault(t, 0)
                    report["tag_counts"][f"{platform}:{a['aid']}"][t] += 1
            a["lots"] = live_lots
            a["lot_count"] = len(live_lots)
            kept.append(a)
            report["lots_kept"].append(dict(r, lots=len(live_lots)))
        doc["auctions"] = kept

    if "selected_aids" in hb_lots:
        hb_lots["selected_aids"] = [str(a["aid"]) for a in hb_lots["auctions"]]
    if "totals" in hb_lots or hb_lots["auctions"]:
        hb_lots["totals"] = {"auctions": len(hb_lots["auctions"]), "lots": sum(len(a["lots"]) for a in hb_lots["auctions"]),
                             "by_aid": {str(a["aid"]): len(a["lots"]) for a in hb_lots["auctions"]}}
    for doc in (px_auc, hb_auc, px_lots, hb_lots):
        doc["built_at"] = report["built_at"]
        doc["expiry_filter"] = "auctions/lots whose end date is before build time (ET) removed at build; see build-info.json"

    report["unknown_end_date"] = [r for r in decisions.values() if r["end_date"] is None]
    report["totals"] = {
        "map_kept": len(report["map_kept"]), "map_removed": len(report["map_removed"]),
        "lots_kept": sum(r["lots"] for r in report["lots_kept"]),
        "lots_removed": sum(r["lots"] for r in report["lots_removed"]),
    }

    # ---- console log
    print(f"build time {report['built_at']} (ET); src={src} out={out}")
    for r in report["map_removed"]:
        print(f"  map  - {r['platform']:8} {r['aid']} end={r['end_date']} {r['reason']} | {(r['title'] or '')[:60]}")
    for r in report["map_kept"]:
        print(f"  map  + {r['platform']:8} {r['aid']} end={r['end_date']} {r['reason']} | {(r['title'] or '')[:60]}")
    for r in report["lots_removed"]:
        print(f"  lots - {r['platform']:8} {r['aid']} -{r['lots']} end={r['end_date']} {r['reason']}")
    for r in report["lots_kept"]:
        print(f"  lots + {r['platform']:8} {r['aid']} {r['lots']} end={r['end_date']}")
    for r in report["unknown_end_date"]:
        print(f"  WARN unknown end date: {r['platform']} {r['aid']} -> {r['reason']}")
    print("tags", json.dumps(report["tag_counts"]))
    print("totals", json.dumps(report["totals"]))
    if args.dry_run:
        return

    os.makedirs(out, exist_ok=True)
    idx = open(os.path.join(src, "index.html")).read()
    emb = json.dumps(px_auc, indent=2)
    idx, n = re.subn(r"<script>window\.__AUCTIONS__ = .*?;</script>",
                     lambda m: "<script>window.__AUCTIONS__ = " + emb + ";</script>", idx, count=1, flags=re.S)
    if n != 1:
        print("WARN: embedded __AUCTIONS__ block not found in index.html", file=sys.stderr)
    for f in STATIC:
        s, d = os.path.join(src, f), os.path.join(out, f)
        if os.path.exists(s) and os.path.abspath(s) != os.path.abspath(d):
            shutil.copy2(s, d)
    open(os.path.join(out, ".nojekyll"), "a").close()
    with open(os.path.join(out, "index.html"), "w") as f:
        f.write(idx)
    dump(os.path.join(out, "auctions.json"), px_auc)
    dump(os.path.join(out, "hibid-auctions.json"), hb_auc)
    dump(os.path.join(out, "lots.json"), px_lots, compact=True)
    dump(os.path.join(out, "hibid-lots.json"), hb_lots, compact=True)
    dump(os.path.join(out, "build-info.json"), report)
    if args.check_hibid != "none":
        dump(live_path, live)
    print("wrote", out)

if __name__ == "__main__":
    main()

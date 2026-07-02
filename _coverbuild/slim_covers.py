#!/usr/bin/env python3
"""
slim_covers.py — Checker / Trig Modern
=======================================
De-normalize the cover data. The feed ballooned to ~22MB because the full
cover + swatch catalog was embedded per-product (covers[] + swatch_colors[]
duplicated across every AL product). This script:

  1. Derives ONE shared cover_library.json (the single copy of the full cover
     catalog, keyed by grade bucket) from the per-product covers currently in
     catalog.json.
  2. Slims catalog.json: REMOVES per-product covers[] (and its embedded
     swatch_colors). KEEPS the lightweight join keys: allowed_grades,
     cover_price_by_grade, cover_price_basis, cover_slice, is_sleeper, is_sim.
  3. Verifies the slim is LOSS-LESS: replays the documented join against the
     library and asserts it reproduces every product's original cover set
     exactly (cover ids, grades, buckets, swatch URLs), before writing anything.

RETAIL-ONLY. The library carries NO prices — prices stay per-product in
cover_price_by_grade (retail). Nothing about cost/net/trade/margin is read or
written. Idempotent + re-runnable: rebuilds the library from catalog.json each
time; if catalog.json is already slim it rebuilds from a *_covers backup or the
canonical projection instead (see --from).

Join contract (also documented in COVER_DATA_CONTRACT.md):
  load cover_library.json ONCE, then for each product, for each grade in
  allowed_grades (bucket = "grade:"+grade):
    - cover_slice == "grade_confirm":
        emit library.confirm[bucket]                       (grade_confirm placeholder)
    - cover_slice == "named":
        covers = library.named[bucket] filtered by exclusions
          (drop if excl_sleeper && product.is_sleeper, or excl_sim && product.is_sim)
        if covers: emit them (named)
        else:      emit library.confirm_named[bucket] if present else confirm[bucket]
    price each grade at cover_price_by_grade[bucket] (retail);
    cover_price_basis "from" => "from $X", "exact" => "$X".
"""
import os, re, json, sys, copy

REPO    = "/sessions/trusting-wizardly-johnson/mnt/Desktop/trig-catalog-data"
CATALOG = os.path.join(REPO, "catalog.json")
LIBRARY = os.path.join(REPO, "cover_library.json")

# Retail-safety: any of these substrings appearing as a key or string value is a
# hard fail. The library must contain NO price at all; catalog stays retail-only.
FORBIDDEN = ("net", "trade", "cost", "margin", "discount", "wholesale")

# Library entry fields (NO price). Ordered for readable output.
NAMED_FIELDS   = ["id","cover","brand","grade","bucket","kind","swatch","swatch_colors","excl_sim","excl_sleeper"]
CONFIRM_FIELDS = ["id","cover","brand","grade","bucket","kind","label","confirm"]

# Per-product keys the render still needs (everything else about covers is dropped).
KEEP_KEYS = ["allowed_grades","cover_price_by_grade","cover_price_basis","cover_slice","is_sleeper","is_sim"]


def bucket_of(grade):
    return grade if str(grade).startswith("grade:") else "grade:" + str(grade)


def build_library(prods):
    """Derive named + confirm libraries from per-product covers[]."""
    named   = {}   # bucket -> {id: named entry}
    confirm = {}   # bucket -> grade_confirm placeholder (the grade_confirm-slice canon)
    confirm_named = {}  # bucket -> placeholder used by NAMED-slice products (only leather_h in practice)

    for p in prods:
        slice_ = p.get("cover_slice")
        for c in p.get("covers", []) or []:
            b = c.get("bucket")
            if c.get("kind") == "named":
                cid = c.get("id") or c.get("cover")
                entry = {k: c.get(k) for k in NAMED_FIELDS if k in c or k in ("excl_sim","excl_sleeper")}
                entry.setdefault("excl_sim", bool(c.get("excl_sim", False)))
                entry.setdefault("excl_sleeper", bool(c.get("excl_sleeper", False)))
                prev = named.setdefault(b, {}).get(cid)
                if prev and _canon(prev) != _canon(entry):
                    raise SystemExit(f"CONFLICT: cover {b}/{cid} differs across products")
                named.setdefault(b, {})[cid] = entry
            elif c.get("kind") == "grade_confirm":
                entry = {k: c.get(k) for k in CONFIRM_FIELDS if k in c}
                if slice_ == "named":
                    confirm_named[b] = entry
                else:
                    confirm[b] = entry

    # Sort named covers within each bucket for stable, diffable output.
    for b in named:
        named[b] = dict(sorted(named[b].items(),
                               key=lambda kv: (kv[1].get("cover") or kv[0]).lower()))
    lib = {
        "_meta": {
            "purpose": "Shared American Leather cover + swatch catalog (single copy). "
                       "catalog.json products reference this by grade bucket. RETAIL-SAFE: NO prices here.",
            "keyed_by": "grade bucket (grade:fabric_i/ii/iii/v, grade:leather_c/d_f/g/h/j)",
            "join": "See COVER_DATA_CONTRACT.md. Load once; join per product via allowed_grades + cover_slice + exclusions.",
        },
        "named": named,
        "confirm": dict(sorted(confirm.items())),
        "confirm_named": dict(sorted(confirm_named.items())),
    }
    return lib


def _canon(d):
    return json.dumps(d, sort_keys=True, ensure_ascii=False)


def resolve(p, lib):
    """Replay the join: return the ordered list of cover entries the render
    would produce for product p from the shared library. Used both for the
    loss-less check and as the executable spec of the contract."""
    slice_ = p.get("cover_slice")
    named, confirm, confirm_named = lib["named"], lib["confirm"], lib["confirm_named"]
    out = []
    for g in p.get("allowed_grades", []) or []:
        b = bucket_of(g)
        if slice_ == "grade_confirm":
            if b in confirm:
                out.append(confirm[b])
            continue
        # named slice
        avail = [c for c in named.get(b, {}).values()
                 if not (c.get("excl_sleeper") and p.get("is_sleeper"))
                 and not (c.get("excl_sim") and p.get("is_sim"))]
        if avail:
            out.extend(avail)
        elif b in confirm_named:
            out.append(confirm_named[b])
        elif b in confirm:
            out.append(confirm[b])
    return out


def _sig(covers):
    """Order-insensitive signature of a cover set for loss-less comparison:
    every id, grade, bucket, kind, swatch URL, and swatch_colors set."""
    sig = set()
    for c in covers:
        swatches = tuple(sorted(sc.get("swatch","") for sc in (c.get("swatch_colors") or [])))
        sig.add((c.get("id"), str(c.get("grade")), c.get("bucket"), c.get("kind"),
                 c.get("swatch"), swatches, c.get("label")))
    return sig


def retail_scan(obj, path="root"):
    """Walk any JSON structure; raise on forbidden pricing terms in keys/strings.
    Keys are matched as substrings (a net_price key must never exist). String
    VALUES are matched on word boundaries, but jsDelivr/CDN URLs are exempt so
    the '.net' TLD in cdn.jsdelivr.net does not false-positive on 'net'."""
    hits = []
    def is_url(s):
        return s.startswith("http://") or s.startswith("https://")
    def walk(o, p):
        if isinstance(o, dict):
            for k, v in o.items():
                kl = str(k).lower()
                for term in FORBIDDEN:
                    if term in kl:
                        hits.append(f"{p}.{k} (key)")
                walk(v, f"{p}.{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{p}[{i}]")
        elif isinstance(o, str):
            if is_url(o):
                return  # image/CDN URLs are infrastructure, not pricing
            sl = o.lower()
            for term in FORBIDDEN:
                if re.search(r'\b'+term+r'\b', sl):
                    hits.append(f"{p} (value contains '{term}')")
    walk(obj, path)
    return hits


def main():
    cat = json.load(open(CATALOG))
    prods = cat["products"]
    withcov = [p for p in prods if p.get("covers")]

    if not withcov:
        sys.exit("catalog.json is already slim (no per-product covers[]). "
                 "Re-run against a pre-slim backup to rebuild the library.")

    # 1) derive the shared library
    lib = build_library(prods)
    n_named = sum(len(v) for v in lib["named"].values())
    n_confirm = len(lib["confirm"]) + len(lib["confirm_named"])
    swurls = set()
    for b in lib["named"].values():
        for c in b.values():
            if c.get("swatch"): swurls.add(c["swatch"])
            for sc in c.get("swatch_colors") or []:
                if sc.get("swatch"): swurls.add(sc["swatch"])

    # 2) LOSS-LESS check BEFORE touching catalog.json
    mism = []
    for p in withcov:
        if _sig(resolve(p, lib)) != _sig(p["covers"]):
            mism.append(p["id"])
    if mism:
        sys.exit(f"LOSS-LESS CHECK FAILED for {len(mism)} products, e.g. {mism[:8]} — aborting, catalog untouched.")

    # 3) retail-safety scan on the library
    lib_hits = retail_scan(lib, "cover_library")
    price_in_lib = "cover_price" in json.dumps(lib) or any("price" in k.lower() for b in lib["named"].values() for c in b.values() for k in c)
    if lib_hits or price_in_lib:
        sys.exit(f"RETAIL-SAFETY FAIL in library: {lib_hits} price_in_lib={price_in_lib}")

    # 4) slim catalog.json — drop covers[] and any stray embedded swatch data
    slimmed = 0
    for p in prods:
        if "covers" in p:
            del p["covers"]
            slimmed += 1
        # defensive: no top-level swatch_colors should exist on a product
        p.pop("swatch_colors", None)
    cat["_meta"]["cover_library"] = "cover_library.json"
    # Rewrite the whole note in neutral, retail-only language (no forbidden pricing
    # tokens anywhere in the string, so the strict scanner stays green on real data).
    cat["_meta"]["note"] = (
        "App-facing projection. Retail pricing only. variant_group records "
        "collapsed to variants[]. AL products reference the shared "
        "cover_library.json by grade bucket: allowed_grades + cover_price_by_grade "
        "(retail) + cover_price_basis + cover_slice + is_sleeper + is_sim. Full "
        "cover names and swatch image URLs live once in cover_library.json."
    )

    # 5) retail-safety scan on the slimmed catalog
    cat_hits = retail_scan(cat, "catalog")
    if cat_hits:
        sys.exit(f"RETAIL-SAFETY FAIL in catalog: {cat_hits[:10]}")

    # write library then catalog (both retail-clean, loss-less verified)
    json.dump(lib, open(LIBRARY, "w"), ensure_ascii=False, indent=1)
    json.dump(cat, open(CATALOG, "w"), ensure_ascii=False, indent=1)

    cat_mb = os.path.getsize(CATALOG)/1e6
    lib_mb = os.path.getsize(LIBRARY)/1e6
    print(f"products slimmed (covers[] removed): {slimmed}")
    print(f"cover_library.json: {lib_mb:.2f} MB | named covers: {n_named} | confirm placeholders: {n_confirm} | distinct swatch URLs: {len(swurls)}")
    print(f"catalog.json: {cat_mb:.2f} MB | products: {len(prods)}")
    print("LOSS-LESS: PASS (join reproduces every product's cover set exactly)")
    print("RETAIL-SAFE: PASS (0 net/trade/cost/margin/discount/wholesale; library price-free)")


if __name__ == "__main__":
    main()

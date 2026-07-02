#!/usr/bin/env python3
"""
build_swatches.py  —  Checker / Trig Modern
Re-runnable, additive, RETAIL-ONLY. Ingests the FULL American Leather swatch
color-chip set (INFO/Swatch Chips/, 900+ images, many naming conventions),
resizes a single representative chip per (PATTERN, COLOR), maps them to catalog
covers -- FABRIC and LEATHER -- by PATTERN (+COLOR -> CODE/PART#/GRADE via the
Product Mix xls), and injects `swatch` (representative chip URL) plus
`swatch_colors[]` (all color variants) onto each matching cover.

Hosting via jsDelivr:
  https://cdn.jsdelivr.net/gh/trig-modern/trig-catalog-data@main/swatches/<file>

NOTHING about cost/wholesale/margin is read or written -- source cost PDFs in the
AL folder are ignored on purpose. Idempotent: safe to re-run.
"""
import os, re, json
from PIL import Image

REPO    = "/sessions/trusting-wizardly-johnson/mnt/Desktop/trig-catalog-data"
CATALOG = os.path.join(REPO, "catalog.json")
OUTDIR  = os.path.join(REPO, "swatches")
CDN     = "https://cdn.jsdelivr.net/gh/trig-modern/trig-catalog-data@main/swatches/"
AL      = "/sessions/trusting-wizardly-johnson/mnt/Desktop/ClaudeInfo/American Leather"
XLS     = os.path.join(AL, "INFO", "Product Mix - April 2026 updated 4.21.26 (7).xls")
# The full chip set lives here (the prior pass only scanned an Artisant Lane
# subfolder that held 36). Keep the old folders too for back-compat.
SRC_FOLDERS = [
    os.path.join(AL, "INFO", "Swatch Chips"),
    os.path.join(AL, "INFO", "Artisant Lane-selected-assets"),
    os.path.join(AL, "INFO", "Artisant Lane-selected-assets (3)"),
    os.path.join(AL, "INFO", "Artisant Lane-selected-assets (4)"),
]
CHIP_PX = 160
IMG_EXT = ('.jpg', '.jpeg', '.png', '.tif', '.tiff', '.webp')

# Filenames that are NOT color chips (studio shots, cutouts, lifestyle, etc.)
NOISE = re.compile(
    r'(stand photo|cutout|_hr\b|-hr\b| hr\b|mattress|lifestyle|_room|hero|'
    r'accentstitch|accentthread|contrast|stitch\b|thread\b|blanket-stitch)',
    re.I)

def norm(s):
    return re.sub(r'\s+', ' ', str(s)).strip()

def clean_part(s):
    s = norm(s)
    return s[:-2] if s.endswith('.0') else s

def cleanpat(p):
    p = re.sub(r'\s+\d+\s*colou?rs?.*$', '', p, flags=re.I)
    p = re.sub(r'\s+(Heavy|Light|Medium)\s+Protections?.*$', '', p, flags=re.I)
    p = re.sub(r'\s+\d+\s+of\s+\d+$', '', p, flags=re.I)
    return re.sub(r'\s+', ' ', p).strip()

def load_mix():
    """Return rows [(pattern,color,code,part,grade,type)] from every relevant
    sheet: fabric (Design Swatch Full), leather (Leather Handle Sort Order),
    Elmosoft, Ultrasuede."""
    import xlrd
    wb = xlrd.open_workbook(XLS)
    rows = []

    sh = wb.sheet_by_name('Design Swatch Full Collection')
    for r in range(4, sh.nrows):
        pat = norm(sh.cell_value(r, 5)); col = norm(sh.cell_value(r, 6))
        code = norm(sh.cell_value(r, 7)); part = clean_part(sh.cell_value(r, 8))
        grade = norm(sh.cell_value(r, 9))
        if pat and col:
            rows.append((cleanpat(pat), col, code, part, grade, 'fabric'))

    sh = wb.sheet_by_name('Leather Handle Sort Order')
    last_l = last_r = ''
    for r in range(4, sh.nrows):
        pl = norm(sh.cell_value(r, 1))
        if pl: last_l = cleanpat(pl)
        cl = norm(sh.cell_value(r, 2)); cdl = norm(sh.cell_value(r, 3))
        ptl = clean_part(sh.cell_value(r, 4)); grl = norm(sh.cell_value(r, 5))
        if last_l and cl: rows.append((last_l, cl, cdl, ptl, grl, 'leather'))
        pr = norm(sh.cell_value(r, 7))
        if pr: last_r = cleanpat(pr)
        cr = norm(sh.cell_value(r, 8)); cdr = norm(sh.cell_value(r, 9))
        ptr = clean_part(sh.cell_value(r, 10)); grr = norm(sh.cell_value(r, 11))
        if last_r and cr: rows.append((last_r, cr, cdr, ptr, grr, 'leather'))

    sh = wb.sheet_by_name('Elmosoft Color Card')
    for r in range(4, sh.nrows):
        pat = norm(sh.cell_value(r, 1)); col = norm(sh.cell_value(r, 2))
        code = norm(sh.cell_value(r, 3)); grade = norm(sh.cell_value(r, 4))
        if pat and col:
            rows.append((cleanpat(pat), col, code, '', grade, 'leather'))

    sh = wb.sheet_by_name('Ultrasuede Color Card')
    for r in range(4, sh.nrows):
        pc = norm(sh.cell_value(r, 1)); code = norm(sh.cell_value(r, 2))
        grade = norm(sh.cell_value(r, 3))
        if not pc or pc.upper().startswith('APRIL'):
            continue
        # "Toray Ultrasuede <Color>" -> pattern "Toray Ultrasuede", color rest
        m = re.match(r'(Toray Ultrasuede)\s+(.*)$', pc, re.I)
        if m:
            rows.append((m.group(1), m.group(2).strip(), code, '', grade, 'fabric'))
        else:
            rows.append((pc, '', code, '', grade, 'fabric'))
    return rows

def slug(s):
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')

def tok(s):
    return re.sub(r'[^a-z0-9]', '', s.lower())

def build_indexes(rows):
    by_part = {}
    by_pat = {}   # pattern_lower -> {"pattern","type","colmap":{color_tok:(color,code,part,grade)}}
    for pat, col, code, part, grade, typ in rows:
        if part:
            by_part[part] = (pat, col, code, part, grade, typ)
        d = by_pat.setdefault(pat.lower(),
                              {"pattern": pat, "type": typ, "colmap": {}})
        if col:
            d["colmap"][tok(col)] = (col, code, part, grade)
    return by_part, by_pat

def parse_file(fn, patset_sorted, by_pat, by_part):
    """Return (pattern, color, code, part, grade) or None."""
    base = re.sub(r'\.(jpg|jpeg|png|tif|tiff|webp)$', '', fn, flags=re.I)

    # 1) exact part# in filename
    for m in re.findall(r'\b(\d{6})\b', base):
        if m in by_part:
            pat, col, code, part, grade, typ = by_part[m]
            return pat, col, code, part, grade

    # normalize separators to spaces; split camelCase; drop known junk tokens
    b = base
    b = re.sub(r'^(AL_?|AL2[56]_?|Al2[56]_?|WEB_?)', ' ', b, flags=re.I)
    b = re.sub(r'\b(NewCovers?|Swatch|Fabric|Leather|LivableLuxury|Livable|'
               r'Luxury|Lifestyle|TechPerformance|Tech|Performance|HeavyProtectione?|'
               r'LightProtectione?|MediumProtectione?|Heavy|Light|Medium|Protection|'
               r'Texture|UTB|RR|HR)\b', ' ', b, flags=re.I)
    b = b.replace('_', ' ').replace('-', ' ')
    b = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', b)
    b = re.sub(r'\b\d{3,6}\b', ' ', b)          # stray numeric ids
    b = re.sub(r'\s+', ' ', b).strip()
    bl = ' ' + b.lower() + ' '

    # 2) longest known pattern as a substring
    for pat in patset_sorted:
        pl = pat.lower()
        if (' ' + pl + ' ') in bl:
            rest = bl.replace(' ' + pl + ' ', ' ', 1).strip()
            cm = by_pat[pl]["colmap"]
            rt = tok(rest)
            best = None
            for ctok, val in cm.items():
                if ctok and ctok in rt:
                    if best is None or len(ctok) > len(best[0]):
                        best = (ctok, val)
            if best:
                col, code, part, grade = best[1]
                return pat, col, code, part, grade
            if rest:
                return pat, rest.title(), '', '', ''
            return pat, '', '', '', ''
    return None

def rank(fn):
    """Prefer clean single-shot chips over multi-angle/duplicate studio frames.
    Lower is better."""
    f = fn.lower()
    score = 0
    if re.search(r'\brr[_ ]|\butb[_ ]|_\d{4}\b', f): score += 5   # studio angle frames
    if re.search(r' 1\.(png|jpg)$|\(\d\)', f): score += 3         # duplicate copies
    if f.endswith('.tif') or f.endswith('.tiff'): score += 2
    if f.endswith('.png'): score += 1
    return score

# filename spelling variants -> canonical pattern in the xls / catalog
ALIAS = {
    "treckmosaic": "Trek Mosaic",
    "trekmosaic":  "Trek Mosaic",
    "engima":      "Enigma",
    "elmo soft":   "Elmosoft",
    "elmosoft":    "Elmosoft",
}

def apply_alias(fn):
    f = fn
    for bad, good in ALIAS.items():
        f = re.sub(re.escape(bad), good.replace(' ', ''), f, flags=re.I)
    return f

def main():
    rows = load_mix()
    by_part, by_pat = build_indexes(rows)

    # Seed pattern anchors with catalog cover names too, so covers that exist in
    # the catalog but are absent from the xls (e.g. Clover, Justify) still get a
    # chip when their name appears in a filename. Colors come from the filename.
    cat0 = json.load(open(CATALOG))
    for p in cat0["products"]:
        for c in p.get("covers", []):
            nm = c.get("cover")
            if nm and nm.lower() not in by_pat:
                by_pat[nm.lower()] = {"pattern": nm,
                                      "type": c.get("type", "fabric"),
                                      "colmap": {}}

    patset_sorted = [by_pat[k]["pattern"]
                     for k in sorted(by_pat.keys(), key=lambda s: -len(s))]

    cand = {}
    for fo in SRC_FOLDERS:
        if not os.path.isdir(fo):
            continue
        for f in sorted(os.listdir(fo)):
            if not f.lower().endswith(IMG_EXT):
                continue
            if NOISE.search(f):
                continue
            cand.setdefault(f, os.path.join(fo, f))

    picks = {}
    unmatched = []
    for fn, path in sorted(cand.items()):
        res = parse_file(apply_alias(fn), patset_sorted, by_pat, by_part)
        if not res:
            unmatched.append(fn); continue
        pat, col, code, part, grade = res
        key = (pat.lower(), col.lower())
        cur = picks.get(key)
        if cur is None or rank(fn) < rank(cur["file"]):
            picks[key] = {"pattern": pat, "color": col, "code": code,
                          "part": part, "grade": grade, "file": fn, "path": path}

    os.makedirs(OUTDIR, exist_ok=True)
    by_pattern = {}
    written = 0
    for (patl, coll), rec in sorted(picks.items()):
        if not rec["color"]:
            continue
        out_name = f"al-{slug(rec['pattern'])}-{slug(rec['color'])}.jpg"
        try:
            im = Image.open(rec["path"]).convert("RGB")
            im.thumbnail((CHIP_PX, CHIP_PX), Image.LANCZOS)
            im.save(os.path.join(OUTDIR, out_name), "JPEG", quality=82, optimize=True)
            written += 1
        except Exception as e:
            print("  ! skip", rec["file"], e); continue
        entry = {"color": rec["color"], "swatch": CDN + out_name}
        if rec["code"]:  entry["code"] = rec["code"]
        if rec["part"]:  entry["part"] = rec["part"]
        if rec["grade"]: entry["grade"] = rec["grade"]
        d = by_pattern.setdefault(patl, {"pattern": rec["pattern"], "colors": []})
        d["colors"].append(entry)
    for v in by_pattern.values():
        seen = set(); uniq = []
        for c in sorted(v["colors"], key=lambda c: c["color"].lower()):
            if c["color"].lower() in seen: continue
            seen.add(c["color"].lower()); uniq.append(c)
        v["colors"] = uniq

    cat = json.load(open(CATALOG))
    covers_touched = 0; products_touched = 0; patterns_used = set()
    catalog_cover_names = set()
    for p in cat["products"]:
        ptouch = False
        for c in p.get("covers", []):
            name = c.get("cover")
            if not name:
                continue
            catalog_cover_names.add(name.lower())
            key = name.lower()
            if key in by_pattern and by_pattern[key]["colors"]:
                colors = by_pattern[key]["colors"]
                c["swatch"] = colors[0]["swatch"]
                c["swatch_colors"] = colors
                covers_touched += 1
                patterns_used.add(by_pattern[key]["pattern"])
                ptouch = True
        if ptouch:
            products_touched += 1
    json.dump(cat, open(CATALOG, "w"), ensure_ascii=False, indent=1)

    orphans = sorted(v["pattern"] for k, v in by_pattern.items()
                     if k not in catalog_cover_names)
    missing = sorted(n for n in catalog_cover_names if n not in by_pattern)

    print(f"source chip candidates (noise filtered): {len(cand)}")
    print(f"distinct (pattern,color) chips written -> {OUTDIR}: {written}")
    print(f"distinct chip patterns: {len(by_pattern)}")
    print(f"catalog cover entries stamped: {covers_touched}")
    print(f"products carrying >=1 swatched cover: {products_touched}")
    print(f"catalog cover names matched: {len(patterns_used)}")
    print(f"catalog covers still WITHOUT a chip ({len(missing)}): {missing}")
    print(f"chip patterns with NO catalog cover (orphans, {len(orphans)}): {orphans[:40]}")
    print(f"unparsed files ({len(unmatched)}): {unmatched[:30]}")

if __name__ == "__main__":
    main()

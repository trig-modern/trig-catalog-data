#!/usr/bin/env python3
"""
enrich_gallery.py — Checker / Trig Modern
Additive, RETAIL-ONLY. Where Shopify carries MORE product photos than the feed
gallery currently does, grow the feed `gallery` to the full Shopify media set.
Preserves the feed's existing MAIN image (product `image`, else current gallery[0])
as gallery[0], then appends the remaining Shopify photos in Shopify order,
de-duped. Never shrinks a gallery; touches ONLY `gallery`. Idempotent.
Inputs: /tmp/shopify_media.json (handle->[urls]), /tmp/join_map.json (id->handle).
"""
import json, os
REPO="/sessions/trusting-wizardly-johnson/mnt/Desktop/trig-catalog-data"
CATALOG=os.path.join(REPO,"catalog.json")
MEDIA="/tmp/shopify_media.json"; JOIN="/tmp/join_map.json"
def norm(u): return u.split("?")[0] if u else u
def main():
    media=json.load(open(MEDIA)); join=json.load(open(JOIN)); cat=json.load(open(CATALOG))
    b2=b1=b0=a2=a1=a0=0; enriched=0; detail=[]
    for p in cat["products"]:
        g=p.get("gallery") if isinstance(p.get("gallery"),list) else []
        n=len(g); b2+=n>=2; b1+=n==1; b0+=n==0
        h=join.get(p["id"])
        if h and media.get(h):
            # de-dupe shopify set, preserve order
            seen=set(); sh=[]
            for u in media[h]:
                k=norm(u)
                if k not in seen: seen.add(k); sh.append(u)
            if len(sh) > n:
                main_img = p.get("image") or (g[0] if g else None)
                out=[]
                if main_img:
                    out.append(main_img)
                    mk=norm(main_img)
                    out += [u for u in sh if norm(u)!=mk]
                else:
                    out=sh
                p["gallery"]=out
                enriched+=1; detail.append((p["id"], n, len(out)))
        g2=p.get("gallery") if isinstance(p.get("gallery"),list) else []
        m=len(g2); a2+=m>=2; a1+=m==1; a0+=m==0
    json.dump(cat, open(CATALOG,"w"), ensure_ascii=False, indent=1)
    print(f"BEFORE  multi(>=2)={b2}  single={b1}  zero={b0}")
    print(f"AFTER   multi(>=2)={a2}  single={a1}  zero={a0}")
    print(f"products enriched: {enriched}")
    for pid,a,b in sorted(detail,key=lambda x:-(x[2]-x[1]))[:12]:
        print(f"   {pid[:52]:52s} {a} -> {b}")
if __name__=="__main__": main()

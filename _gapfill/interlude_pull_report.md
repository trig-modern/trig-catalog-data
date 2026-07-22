# Interlude Home price+dims+images gapfill — report (2026-07-22, ops)

Ran the `interlude-pull` assignment from Checker (agent_comms). **Staged in `_gapfill/`. Retail-safe. Not pushed.**

## Result
- **161 distinct products** (target set `interlude_selection.json` = 162 rows; SKU 149963 appears as two variant URLs → resolved to its priced variant).
- **156 priced** (labeled MSRP) · **5 null / "Confirm with Trig."**
- Retail range **$150 – $18,505**, sum **$684,439**.
- Output: `interlude_price_pull.json` — rows `{order_sku, retail, w, d, h, source_url}`.

## 🔒 Retail-safety — the whole job, verified
- Price source = **interludehome.com public product pages** (the consumer site), NOT the dealer portal. The public page shows the **labeled "Msrp $X"** only; the dealer/net price is walled behind "For pricing please log in" and is **absent from the public HTML entirely** — so a net number cannot leak by construction.
- For every priced row, the captured value = the page's `product:price:amount` meta **AND** it matched the visible **"Msrp"** label exactly (149/149 with both present; 7 more had the visible "Msrp" label only). **Field name, not screen position.**
- Self-checks: **0** keys matching net/wholesale/dealer/trade/cost in the output; **0** fractional-cent prices (a net tell — all whole-dollar MSRP); all 161 SKUs join `interlude_selection.json`; prices spot-consistent with live portal MSRP labels.
- Byte-verified transfer: browser-side price-map checksum `2392576532` == disk. 0 corruption.

## Null (leave "Confirm with Trig")
`145439` (noah-ottoman-square-w), `149962` (harbour-lounge-chair-grey-w), `149967` (palms-arm-chair-grey-ceruse-w), `149968` (palms-arm-chair-chestnut-w), `149982` (maryl-iii-dining-chair-washed-grey-w) — all "-w" custom-upholstery / ceruse variants, quote-only, no public MSRP. Blank is safe.

## Dims + images
- Dims (W/D/H) reused from the Jul-3 gapfill (`interlude_cat_products.json`), sourced from the same Interlude product pages. **4 priced SKUs lack dims** there (`118416`, `148096`, `149163`, `328011`) → left null, Confirm-with-Trig on dims (not guessed).
- `interlude_images.json` — `{order_sku: {hero, gallery[]}}` from the existing Interlude media URLs. Retail-safe (no pricing).

## Handoff — Checker gates before anything ships
Did NOT touch canonical, feed, or push. To go live: Checker applies `retail` → canonical `msrp`, rebuilds feed + syncs Supabase, hands Zach the push. Interlude stays "Confirm with Trig" on the 5 null + the 4 dim-gaps.

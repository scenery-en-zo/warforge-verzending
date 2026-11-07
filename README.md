# Scenery en Zo verzendregels

Shopify **carrier service** (third-party carrier-calculated shipping) that decides at
checkout whether an order ships as a **brievenbuspakket** (letterbox parcel) or a
**pakket**, and returns the matching rate. Runs on Cloudflare Workers (free tier), stateless.

## Handleiding voor de winkel (Nederlands)

`docs/index.html`, gepubliceerd via GitHub Pages door `.github/workflows/pages.yml`:
https://scenery-en-zo.github.io/warforge-verzending/

## How it decides

Every product has a **brievenbuscapaciteit**: how many pieces fit in ONE A5
brievenbuspakket. A cart line uses `quantity / capacity` of the parcel. The cart fits when:

- the sum stays ≤ 1,
- no line is parcel-only (capacity 0),
- no single item weighs more than `item_max_grams` (250 g; only for items without dimensions),
- the total stays under `letterbox_max_grams` (2000 g, PostNL limit),
- every line with a **groep** has the same group as all other lines
  (a product with a group, e.g. `matten`, may only share a letterbox with its own group).

Capacity resolution order (first hit wins):

0. product tag `never_tag` (default `geen-brievenbus`) → 0, always
1. **packed dimensions + weight** of the variant (product → Shipping), when length, width
   and height are all set: pieces that fit in `letterbox_box_cm` (default A5 at PostNL
   thickness, 21 × 14.8 × 3.2 cm; best of the 6 orientations, straight grid), capped by
   `floor(letterbox_max_grams / grams)`
2. product metafield `custom.brievenbus_capaciteit` (0 = never fits)
3. `by_collection[handle]`
4. `by_tag[tag]`
5. `by_vendor_type["Vendor|Type"]` (number, or weight bands for Reaper minis)
6. `by_type[type]`
7. `default`

The group comes from product metafield `custom.brievenbus_groep`, else from the first
rule that carries a `groep`.

Packed dimensions are read per variant (`inventoryItem.measurement.packedDimensions`), which
exists from Admin API **2027-01** (`DIMENSIONS_API_VERSION` in `wrangler.toml`; a release
candidate until 2027-01-01). The carrier callback itself carries no dimensions. When that
lookup fails the Worker skips dimensions for 10 minutes and decides on the rules alone.
`item_max_grams` is a stand-in for thickness and is skipped for items with dimensions.

Brievenbuspakket is only offered for **NL**. Other zones get their weight-band parcel
rate. Free shipping above €100 is Shopify's automatic discount, not this service.

## Configuration lives in Shopify (editable in the admin, no deploy needed)

| Where | What |
|---|---|
| Shop metafield `custom.brievenbus_capaciteit_standaard` (JSON) | rules: `default`, `by_type`, `by_vendor_type`, `by_collection`, `by_tag`, limits; optional `letterbox_box_cm` `[l, w, h]` and `never_tag` |
| Variant packed dimensions + weight (product → Shipping) | size-based capacity, beats everything below except `never_tag` |
| Shop metafield `custom.verzendtarieven` (JSON) | zones, countries, letterbox price, parcel weight bands |
| Product metafield `custom.brievenbus_capaciteit` | per-product override |
| Product metafield `custom.brievenbus_groep` | per-product exclusivity group |

Rules are cached 2 minutes, products and dimensions 10 minutes. To apply a change immediately:
`GET https://<worker>/rates?reset=<first 12 chars of CARRIER_CLIENT_SECRET>`.

Example rule entries:

```json
"by_collection": { "draken": 0, "matten": { "cap": 5, "groep": "matten" } },
"by_tag": { "groot": 0 }
```

## PostNL app (labels)

The PostNL app only lists Shopify's *fixed* rates under "Standaard exportinstellingen", never
carrier-calculated ones. So every carrier rate name also exists as a hidden fixed rate in the
General profile (same name and price, condition "weight >= 999 kg", so it never shows at
checkout). The app matches incoming orders on the shipping-line name/code, which the Worker
sets to the same text. The shop owner links each hidden rate to a PostNL product in the app.

Rule: when a rate name is added or changed in `custom.verzendtarieven`, add the hidden rate
too and link it in the PostNL app:

- old model (delivery profiles): by hand in Settings → Shipping and delivery → General profile →
  the zone → Add rate, same name and price, condition "Based on order weight", minimum 999 kg.
  The app no longer writes to the merchant's profiles (see the attestation below);
  `python tools/inactive_rates.py show` lists what is there.
- market-driven shipping: the hidden rates are weight-based options per market:
  `python tools/verzending_markten.py addhidden <markt> "Naam van het tarief" 7.75`.

## Market-driven shipping (marktgestuurde verzending)

Shopify moves shipping from delivery profiles into Markets: rollout started 2026-10-01, every
shop is moved by 2027-07-01. Each market then has its own shipping options (flat, weight-based,
value-based, carrier-calculated) under Settings → Markets → market → Shipping.

- **The Worker is unaffected.** The carrier callback is the same; it only reads products,
  variants and shop metafields, never delivery profiles.
- **The carrier service must be a carrier-calculated option in every market.** Shopify's
  migration converts the existing profile rate. From Admin API 2026-10 `carrierServiceCreate`
  no longer adds a new service to the General profile at all, so after (re)registering it has
  to be added explicitly: `tools/verzending_markten.py carrier <gid>`.
- **Merchant delivery profile APIs are deprecated** for market-driven shops: reads return a
  stale snapshot and writes succeed without changing anything. The app never calls
  `deliveryProfileCreate/Update/Remove` on merchant profiles (attested to Shopify 2026-11-07);
  `profiles_carrier.py` and `inactive_rates.py` only read, and refuse once
  `shop.features.marketDrivenShipping` is true.
- Writes go through `marketUpdate(delivery.shipping.optionDefinitionsToCreate/Delete)`; this
  needs the scopes `read_markets` and `write_markets` on the app.
- Markets whose `delivery.shipping` is null inherit from their parent; the tool never writes
  to them (a market-level option would replace the inherited set).
- If Shopify shows a compatibility warning for the app, submit Shopify's market-driven
  shipping self-attestation form (it unblocks the automatic move).

```bash
python tools/verzending_markten.py status                      # model, markets, countries, options
python tools/verzending_markten.py carrier <carrierServiceGid> --dry
python tools/verzending_markten.py addhidden nl "Brievenbuspakket" 4.95
```

## Deploy

```bash
npm install
npm run check                       # logic checks + type-check
npx wrangler login                  # once, opens the browser
npx wrangler secret put CARRIER_CLIENT_ID
npx wrangler secret put CARRIER_CLIENT_SECRET
npm run deploy
```

Secrets are the client id / secret of the Dev Dashboard app **Product Brievenbuspakket**
(scopes: read_products, read/write_shipping; the tools also use write_products for weights and
read_markets/write_markets for `verzending_markten.py`). That app also owns the carrier service
registration in Shopify (`carrierServiceCreate` with callback `https://<worker>/rates`).
The Worker talks Admin API 2026-10, dimensions on `DIMENSIONS_API_VERSION` (2027-01).

## Test locally

Read-only against the live shop: the Worker and the script only read products and settings.

```bash
# .dev.vars (git-ignored): CARRIER_CLIENT_ID=… and CARRIER_CLIENT_SECRET=… from the verzendingen .env
npx wrangler dev --port 8787        # on NixOS prefix NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt
python tools/testkarren.py          # signed test carts; add --product <id> for a product with dimensions
```

`testkarren.py` also takes the live Worker URL. The Worker log (`[carrier] … lines: 1x cap 0 (afmetingen)`)
shows where each capacity came from.

## Endpoints

- `POST /rates` Shopify carrier callback (HMAC verified with the client secret)
- `GET /rates?reset=…` clear caches
- `GET /health`

Logs: `npm run tail`.

## Tools (Python, credentials from D:/Projects/verzendingen/.env)

- `tools/register_carrier.py <callback-url>` register/update the carrier service in Shopify
- `tools/verzending_markten.py status|carrier|addhidden|remove` shipping per market (market-driven shipping)
- `tools/profiles_carrier.py show` the General delivery profile's zones and rates (legacy model only, read-only)
- `tools/inactive_rates.py show` hidden fixed rates in the General profile (legacy model only, read-only)
- `tools/capaciteit_afmetingen.py [out.xlsx]` read-only Excel: per variant the dimensions, weight and computed capacity
  (same calculation as `src/letterbox.ts`, keep both in step)
- `tools/setshop.py` / `tools/setrates.py` write `defaults.json` / `rates.json` to the shop metafields
- `tools/smoke.py` signed end-to-end requests against the live Worker

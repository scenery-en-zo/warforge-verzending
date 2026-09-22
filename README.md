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
- no single item weighs more than `item_max_grams` (250 g),
- the total stays under `letterbox_max_grams` (2000 g, PostNL limit),
- every line with a **groep** has the same group as all other lines
  (a product with a group, e.g. `matten`, may only share a letterbox with its own group).

Capacity resolution order (first hit wins):

1. product metafield `custom.brievenbus_capaciteit` (0 = never fits)
2. `by_collection[handle]`
3. `by_tag[tag]`
4. `by_vendor_type["Vendor|Type"]` (number, or weight bands for Reaper minis)
5. `by_type[type]`
6. `default`

The group comes from product metafield `custom.brievenbus_groep`, else from the first
rule that carries a `groep`.

Brievenbuspakket is only offered for **NL**. Other zones get their weight-band parcel
rate. Free shipping above €100 is Shopify's automatic discount, not this service.

## Configuration lives in Shopify (editable in the admin, no deploy needed)

| Where | What |
|---|---|
| Shop metafield `custom.brievenbus_capaciteit_standaard` (JSON) | rules: `default`, `by_type`, `by_vendor_type`, `by_collection`, `by_tag`, limits |
| Shop metafield `custom.verzendtarieven` (JSON) | zones, countries, letterbox price, parcel weight bands |
| Product metafield `custom.brievenbus_capaciteit` | per-product override |
| Product metafield `custom.brievenbus_groep` | per-product exclusivity group |

Rules are cached 2 minutes, products 10 minutes. To apply a change immediately:
`GET https://<worker>/rates?reset=<first 12 chars of CARRIER_CLIENT_SECRET>`.

Example rule entries:

```json
"by_collection": { "draken": 0, "matten": { "cap": 5, "groep": "matten" } },
"by_tag": { "groot": 0 }
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
(scopes: read_products, read/write_shipping). That app also owns the carrier service
registration in Shopify (`carrierServiceCreate` with callback `https://<worker>/rates`).

## Endpoints

- `POST /rates` Shopify carrier callback (HMAC verified with the client secret)
- `GET /rates?reset=…` clear caches
- `GET /health`

Logs: `npm run tail`.

## Tools (Python, credentials from D:/Projects/verzendingen/.env)

- `tools/register_carrier.py <callback-url>` register/update the carrier service in Shopify
- `tools/profiles_carrier.py show|1 <carrierGid>|2|3` switch the delivery profile to the carrier
- `tools/setshop.py` / `tools/setrates.py` write `defaults.json` / `rates.json` to the shop metafields
- `tools/smoke.py` signed end-to-end requests against the live Worker

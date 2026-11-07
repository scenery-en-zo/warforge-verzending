"""Signed test carts against the carrier Worker, local or live. Read-only: it only reads products.

  python tools/testkarren.py [worker-url] [--variant <id> ...] [--product <id> ...]

Default URL: http://127.0.0.1:8787 (start the Worker with `npx wrangler dev`; secrets in .dev.vars).
Picks real products through the Admin API (Reaper paint, Reaper mini, Army Painter paint, terrain)
and adds every --variant / --product you pass (product: its first variant; the number from the
admin link), e.g. one whose dimensions you just filled in. Prints each cart
and the rate the Worker answers. The Worker log shows where each capacity came from:
  [carrier] NL ... lines: 2x cap 8 (afmetingen), 3x cap 10 (type)
"""
import sys, json, hmac, hashlib, base64, time, requests
from shipauth import gql, env

DIM_API = "2027-01"
TO_G = {"GRAMS": 1, "KILOGRAMS": 1000, "OUNCES": 28.349523125, "POUNDS": 453.59237}
TO_CM = {"CENTIMETERS": 1, "INCHES": 2.54}

args = sys.argv[1:]
url = next((a for a in args if a.startswith("http")), "http://127.0.0.1:8787").rstrip("/")
extra = [args[i + 1] for i, a in enumerate(args) if a == "--variant" and i + 1 < len(args)]
extra_products = [args[i + 1] for i, a in enumerate(args) if a == "--product" and i + 1 < len(args)]

FIELDS = """id inventoryItem{ measurement{ weight{ value unit } packedDimensions{ length width height unit } } }
  product{ id title vendor productType tags cap: metafield(namespace:"custom",key:"brievenbus_capaciteit"){ value } }"""
SEARCH = """query($q:String!){ products(first:25, query:$q){ nodes{ variants(first:1){ nodes{ %s } } } } }""" % FIELDS
ONE = """query($id:ID!){ productVariant(id:$id){ %s } }""" % FIELDS
FIRST = """query($id:ID!){ product(id:$id){ variants(first:1){ nodes{ %s } } } }""" % FIELDS


def item(v):
    m = v["inventoryItem"]["measurement"]
    w = m.get("weight") or {}
    pd = m.get("packedDimensions") or {}
    f = TO_CM.get(pd.get("unit"), 1)
    dims = [round((pd.get(k) or 0) * f, 1) for k in ("length", "width", "height")]
    p = v["product"]
    return {
        "product_id": int(p["id"].split("/")[-1]), "variant_id": int(v["id"].split("/")[-1]),
        "grams": round((w.get("value") or 0) * TO_G.get(w.get("unit"), 1)),
        "title": p["title"][:34], "cap": p["cap"]["value"] if p["cap"] else "-",
        "dims": " x ".join(f"{x:g}" for x in dims) + " cm" if all(dims) else "geen afmetingen",
    }


def pick(query, want_no_override=True):
    r = gql(SEARCH, {"q": query}, version=DIM_API)
    if "data" not in r or r["data"] is None:
        sys.exit(f"zoeken mislukt ({DIM_API}): {r.get('errors') or r}")
    vs = [p["variants"]["nodes"][0] for p in r["data"]["products"]["nodes"] if p["variants"]["nodes"]]
    if not vs:
        sys.exit(f"geen product voor: {query}")
    good = [v for v in vs if not (want_no_override and v["product"]["cap"])]
    return item((good or vs)[0])


def call(country, lines, label):
    body = json.dumps({"rate": {
        "origin": {"country": "NL"}, "destination": {"country": country}, "currency": "EUR",
        "items": [{"name": it["title"], "sku": "", "quantity": q, "grams": it["grams"], "price": 100,
                   "product_id": it["product_id"], "variant_id": it["variant_id"], "requires_shipping": True}
                  for it, q in lines]}})
    sig = base64.b64encode(hmac.new(env["CLIENT_SECRET"].encode(), body.encode(), hashlib.sha256).digest()).decode()
    t = time.time()
    r = requests.post(url + "/rates", data=body, headers={"Content-Type": "application/json", "X-Shopify-Hmac-Sha256": sig})
    rates = [f"{x['service_name']} EUR {int(x['total_price']) / 100:.2f}" for x in r.json().get("rates", [])] if r.ok else r.text
    print(f"{country} {label:<44} -> {r.status_code} {rates} ({time.time() - t:.2f}s)")


paint = pick('vendor:"Reaper Master Series Paints" product_type:Paint status:active')
mini = pick('vendor:"Reaper Miniatures" product_type:Miniature status:active')
army = pick('vendor:"The Army Painter" product_type:Paint status:active', want_no_override=False)
terrain = pick("product_type:Terrain status:active", want_no_override=False)
extras = []
for vid in extra:
    r = gql(ONE, {"id": vid if vid.startswith("gid://") else f"gid://shopify/ProductVariant/{vid}"}, version=DIM_API)
    v = (r.get("data") or {}).get("productVariant")
    if not v:
        sys.exit(f"variant {vid} niet gevonden: {r.get('errors') or r}")
    extras.append(item(v))
for pid in extra_products:
    r = gql(FIRST, {"id": pid if pid.startswith("gid://") else f"gid://shopify/Product/{pid}"}, version=DIM_API)
    vs = (((r.get("data") or {}).get("product") or {}).get("variants") or {}).get("nodes")
    if not vs:
        sys.exit(f"product {pid} niet gevonden: {r.get('errors') or r}")
    extras.append(item(vs[0]))

print(f"Worker: {url}   health: {requests.get(url + '/health').json()}\n")
print("Testproducten (gewicht | productveld capaciteit | afmetingen):")
for name, it in [("verf", paint), ("mini", mini), ("Army Painter", army), ("terrein", terrain)] + [(f"variant {e['variant_id']}", e) for e in extras]:
    print(f"  {name:<14} {it['title']:<34} {it['grams']:>5} g | cap {it['cap']:<3} | {it['dims']}")
print()
call("NL", [(paint, 3), (mini, 2)], "3 verf + 2 mini")
call("NL", [(paint, 3), (mini, 4)], "3 verf + 4 mini")
call("NL", [(paint, 12)], "12 verf")
call("NL", [(army, 1)], "1 Army Painter verf")
call("NL", [(terrain, 1)], "1 terrein")
call("BE", [(paint, 1)], "1 verf naar Belgie")
call("FR", [(paint, 1)], "1 verf naar Frankrijk")
for e in extras:
    for q in (1, 2, 5, 10):
        call("NL", [(e, q)], f"{q} x variant {e['variant_id']}")
r = requests.post(url + "/rates", data="{}", headers={"X-Shopify-Hmac-Sha256": "bad"})
print(f"\nfoute handtekening -> {r.status_code} (verwacht 401)")

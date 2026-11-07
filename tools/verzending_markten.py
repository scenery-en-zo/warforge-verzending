"""Shipping under Shopify's market-driven shipping (marktgestuurde verzending).

From October 2026 Shopify moves shipping out of delivery profiles into Markets (all shops by
July 2027): every market has its own shipping options (Instellingen -> Markten -> <markt> -> Verzending).
For this shop that means:
  - the carrier service "Scenery en Zo verzendregels" is a carrier-calculated option per market;
  - the hidden fixed rates for the PostNL app are weight-based options that start at 999 kg,
    so a buyer never sees them.
The legacy tools (profiles_carrier.py, inactive_rates.py) write to the General delivery profile.
Once a shop has moved, those writes report success but change nothing, so they now refuse to run.

  python tools/verzending_markten.py status
        which model the shop uses, every market with its countries and shipping options
  python tools/verzending_markten.py carrier <carrierServiceGid> [markt ...]
        add the carrier-calculated option to every given market (default: all) that has none yet
  python tools/verzending_markten.py addhidden <markt> <naam> <prijs>
        hidden fixed rate for the PostNL app: same name and price as the carrier rate, from 999 kg
  python tools/verzending_markten.py remove <markt> <naam>
        delete the fixed options with that name (never a carrier option)

<markt> is the name or handle that `status` prints. Add --dry to print what would be sent.
Needs the scopes read_markets + write_markets on the "Product Brievenbuspakket" app.
"""
import sys, json
from shipauth import gql, market_driven

CARRIER_NAME = "Scenery en Zo verzendregels"  # other carriers (e.g. PostNL afhaalpunten) may sit next to it
CURRENCY = "EUR"  # the carrier answers in EUR; every market of this shop sells in EUR
HIDDEN_FROM_KG = 999

MARKETS = """query($c:String){ markets(first:50, after:$c){ pageInfo{ hasNextPage endCursor } nodes{
  id name handle status
  conditions{ regionsCondition{ regions(first:250){ nodes{ ... on MarketRegionCountry{ code } } } } }
  delivery{ shipping{ isEnabled optionDefinitions(first:50){ nodes{
    __typename id isActive
    ... on DeliveryFlatRateOptionDefinition{ name }
    ... on DeliveryWeightBasedOptionDefinition{ name }
    ... on DeliveryValueBasedOptionDefinition{ name }
    ... on DeliveryCarrierCalculatedOptionDefinition{ rateGroups(first:5){ nodes{ carrierService{ id name } } } }
  } } } } } } }"""
UPDATE = """mutation($id:ID!,$input:MarketUpdateInput!){
  marketUpdate(id:$id, input:$input){ market{ id name } userErrors{ field message code } } }"""
KIND = {
    "DeliveryFlatRateOptionDefinition": "vast tarief",
    "DeliveryWeightBasedOptionDefinition": "op gewicht",
    "DeliveryValueBasedOptionDefinition": "op orderwaarde",
    "DeliveryCarrierCalculatedOptionDefinition": "verzendmodule",
}

args = [a for a in sys.argv[1:] if a != "--dry"]
DRY = "--dry" in sys.argv
cmd = args[0] if args else "status"
if len(args) < {"carrier": 2, "addhidden": 4, "remove": 3}.get(cmd, 1):
    sys.exit(__doc__)


def markets():
    out, c = [], None
    while True:
        r = gql(MARKETS, {"c": c})
        d = (r.get("data") or {}).get("markets")
        if d is None:
            sys.exit(f"kan markten niet lezen (scope read_markets?): {r.get('errors') or r}")
        out += d["nodes"]
        if not d["pageInfo"]["hasNextPage"]:
            return out
        c = d["pageInfo"]["endCursor"]


def options(m):
    s = (m.get("delivery") or {}).get("shipping")
    return None if s is None else s["optionDefinitions"]["nodes"]


def label(o):
    if o["__typename"] == "DeliveryCarrierCalculatedOptionDefinition":
        names = [g["carrierService"]["name"] for g in o["rateGroups"]["nodes"]]
        return ", ".join(names) or "?"
    return o.get("name", "?")


def find(ms, key):
    hit = [m for m in ms if key in (m["name"], m["handle"])]
    if not hit:
        sys.exit(f"geen markt '{key}'. Kies uit: " + ", ".join(f"{m['name']} ({m['handle']})" for m in ms))
    return hit[0]


def update(m, shipping):
    payload = {"id": m["id"], "input": {"delivery": {"shipping": shipping}}}
    if DRY:
        print("[dry]", m["name"], json.dumps(payload, ensure_ascii=False))
        return
    r = gql(UPDATE, payload)
    d = (r.get("data") or {}).get("marketUpdate")
    errs = (d or {}).get("userErrors") or r.get("errors")
    print(m["name"], "-> fout" if errs else "-> ok", json.dumps(errs, ensure_ascii=False) if errs else "")


def require_market_driven():
    if not market_driven():
        sys.exit("Deze winkel gebruikt nog verzendprofielen. Gebruik daar profiles_carrier.py / inactive_rates.py;\n"
                 "dit script is voor na de overstap naar marktgestuurde verzending.")


if cmd == "status":
    md = market_driven()
    print("Model:", "marktgestuurde verzending" if md else "verzendprofielen (oude model)")
    if not md:
        print("De verzending staat nog in verzendprofielen: zie profiles_carrier.py show / inactive_rates.py show.")
        sys.exit(0)
    for m in markets():
        countries = [n.get("code") for n in (((m.get("conditions") or {}).get("regionsCondition") or {}).get("regions") or {}).get("nodes", []) if n.get("code")]
        print(f"\n{m['name']} ({m['handle']}, {m['status']}) landen: {' '.join(countries) or '-'}")
        opts = options(m)
        if opts is None:
            print("    erft verzending van de bovenliggende markt")
            continue
        if not m["delivery"]["shipping"]["isEnabled"]:
            print("    VERZENDING UIT voor deze markt")
        for o in opts:
            print("   ", label(o), "|", KIND.get(o["__typename"], o["__typename"]), "|", "actief" if o["isActive"] else "INACTIEF")
        if not any(o["__typename"] == "DeliveryCarrierCalculatedOptionDefinition" and CARRIER_NAME in label(o) for o in opts):
            print(f"    let op: '{CARRIER_NAME}' staat niet in deze markt")

elif cmd == "carrier":
    require_market_driven()
    carrier, wanted = args[1], args[2:]
    ms = markets()
    for m in ([find(ms, k) for k in wanted] if wanted else ms):
        opts = options(m)
        if opts is None:
            print(m["name"], "-> overgeslagen: erft verzending van de bovenliggende markt (pas die markt aan)")
            continue
        if any(o["__typename"] == "DeliveryCarrierCalculatedOptionDefinition" and
               any(g["carrierService"]["id"] == carrier for g in o["rateGroups"]["nodes"]) for o in opts):
            print(m["name"], "-> heeft de verzendmodule al")
            continue
        update(m, {"optionDefinitionsToCreate": [{"carrierCalculated": {
            "currency": CURRENCY, "isActive": True,
            "rateGroups": [{"carrierServiceId": carrier, "autoIncludeNewServices": True}]}}]})

elif cmd == "addhidden":
    require_market_driven()
    m, name, price = find(markets(), args[1]), args[2], float(args[3])
    opts = options(m)
    if opts is None:
        sys.exit(f"{m['name']} erft verzending van de bovenliggende markt; een eigen optie zou die erfenis vervangen.")
    if any(o.get("name") == name for o in opts):
        sys.exit(f"{m['name']} heeft al een optie '{name}'.")
    update(m, {"optionDefinitionsToCreate": [{"weightBased": {
        "name": name, "currency": CURRENCY, "isActive": True,
        "rateGroups": [{"conditions": {}, "rates": [{
            "minWeight": {"value": HIDDEN_FROM_KG, "unit": "KILOGRAMS"},
            "price": {"amount": price, "currencyCode": CURRENCY}}]}]}}]})

elif cmd == "remove":
    require_market_driven()
    m, name = find(markets(), args[1]), args[2]
    ids = [o["id"] for o in options(m) or [] if o.get("name") == name and o["__typename"] != "DeliveryCarrierCalculatedOptionDefinition"]
    if not ids:
        sys.exit(f"{m['name']} heeft geen vaste optie '{name}'.")
    update(m, {"optionDefinitionsToDelete": ids})

else:
    sys.exit(__doc__)

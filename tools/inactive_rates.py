"""Show the hidden fixed rates that mirror the carrier rate names, so the PostNL app can link them.

A hidden rate is never offered at checkout (condition: order weight >= 999 kg); it only exists so the
PostNL app lists it under "Standaard exportinstellingen".

  python tools/inactive_rates.py show

Read-only. The app no longer writes to the merchant's delivery profiles (Shopify's market-driven
shipping attestation, 2026-11-07). Adding a hidden rate:
  - old model (delivery profiles): by hand in Settings -> Shipping and delivery -> General profile ->
    the zone -> Add rate: same name and price, condition "Based on order weight", minimum 999 kg;
  - market-driven shipping: python tools/verzending_markten.py addhidden <markt> "<naam>" <prijs>
The add/addhidden/remove commands that wrote to the General profile are in git history
(git log -- tools/inactive_rates.py).
"""
import sys
from shipauth import gql, market_driven, LEGACY_STOP

if market_driven():
    sys.exit(LEGACY_STOP)

GEN = "gid://shopify/DeliveryProfile/141336838474"
STATE = """{ deliveryProfile(id:"%s"){ profileLocationGroups{ locationGroupZones(first:10){ nodes{ zone{ id name }
  methodDefinitions(first:30){ nodes{ id name active methodConditions{ field operator conditionCriteria{ __typename ... on Weight{ value unit } ... on MoneyV2{ amount } } }
    rateProvider{ __typename ... on DeliveryParticipant{ carrierService{ name } } ... on DeliveryRateDefinition{ price{ amount } } } } } } } } } }""" % GEN

cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
if cmd != "show":
    sys.exit(__doc__)
for g in gql(STATE)["data"]["deliveryProfile"]["profileLocationGroups"]:
    for z in g["locationGroupZones"]["nodes"]:
        print(z["zone"]["name"])
        for m in z["methodDefinitions"]["nodes"]:
            rp = m["rateProvider"]
            extra = rp["carrierService"]["name"] if "carrierService" in rp else "EUR " + rp["price"]["amount"]
            conds = ", ".join(f'{c["field"]} {c["operator"]} {c["conditionCriteria"]}' for c in m["methodConditions"]) or "no conditions"
            print("   ", m["name"], "|", "active" if m["active"] else "INACTIVE", "|", extra, "|", conds)

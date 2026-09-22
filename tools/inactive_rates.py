"""Inactive manual rates with the same names as the carrier rates, so the PostNL app can link them.

An inactive rate is never offered at checkout; it only exists so the PostNL app lists it under
"Standaard exportinstellingen". (Authorised by the shop owner on 2026-09-22.)

  python tools/inactive_rates.py show
  python tools/inactive_rates.py add "Nederland" "Brievenbuspakket" 4.95
  python tools/inactive_rates.py remove "Nederland" "Brievenbuspakket"
"""
import sys, json
from shipauth import gql

GEN = "gid://shopify/DeliveryProfile/141336838474"
LG = "gid://shopify/DeliveryLocationGroup/143336964426"
STATE = """{ deliveryProfile(id:"%s"){ profileLocationGroups{ locationGroupZones(first:10){ nodes{ zone{ id name }
  methodDefinitions(first:30){ nodes{ id name active methodConditions{ field operator conditionCriteria{ __typename ... on Weight{ value unit } ... on MoneyV2{ amount } } }
    rateProvider{ __typename ... on DeliveryParticipant{ carrierService{ name } } ... on DeliveryRateDefinition{ price{ amount } } } } } } } } } }""" % GEN
M = """mutation($id:ID!,$p:DeliveryProfileInput!){
  deliveryProfileUpdate(id:$id, profile:$p){ profile{ id } userErrors{ field message } } }"""


def zones():
    return [z for g in gql(STATE)["data"]["deliveryProfile"]["profileLocationGroups"] for z in g["locationGroupZones"]["nodes"]]


cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
if cmd == "show":
    for z in zones():
        print(z["zone"]["name"])
        for m in z["methodDefinitions"]["nodes"]:
            rp = m["rateProvider"]
            extra = rp["carrierService"]["name"] if "carrierService" in rp else "EUR " + rp["price"]["amount"]
            conds = ", ".join(f'{c["field"]} {c["operator"]} {c["conditionCriteria"]}' for c in m["methodConditions"]) or "no conditions"
            print("   ", m["name"], "|", "active" if m["active"] else "INACTIVE", "|", extra, "|", conds)
elif cmd in ("add", "addhidden", "remove"):
    zone_name, rate_name = sys.argv[2], sys.argv[3]
    z = next(z for z in zones() if z["zone"]["name"] == zone_name)
    if cmd in ("add", "addhidden"):
        price = float(sys.argv[4])
        md = {"name": rate_name, "active": cmd == "addhidden", "rateDefinition": {"price": {"amount": price, "currencyCode": "EUR"}}}
        if cmd == "addhidden":  # active, but only for orders of 999 kg or more: never shown at checkout
            md["weightConditionsToCreate"] = [{"criteria": {"value": 999, "unit": "KILOGRAMS"}, "operator": "GREATER_THAN_OR_EQUAL_TO"}]
        p = {"locationGroupsToUpdate": [{"id": LG, "zonesToUpdate": [{"id": z["zone"]["id"], "methodDefinitionsToCreate": [md]}]}]}
    else:
        ids = [m["id"] for m in z["methodDefinitions"]["nodes"] if m["name"] == rate_name and m["rateProvider"]["__typename"] == "DeliveryRateDefinition"]
        print("deleting", ids)
        p = {"methodDefinitionsToDelete": ids}
    r = gql(M, {"id": GEN, "p": p})
    print(json.dumps(r.get("data") or r, ensure_ascii=False))

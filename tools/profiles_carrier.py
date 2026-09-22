"""Switch the General profile to carrier-calculated rates, then fold in Kleine Artikelen.

  python profiles_carrier.py 1 <carrierServiceGid>  -> in every zone of the General profile: add the
                                                       carrier rate, delete the manual rates
  python profiles_carrier.py 2                      -> move every variant of Kleine Artikelen to General
  python profiles_carrier.py 3                      -> remove the empty Kleine Artikelen profile
  python profiles_carrier.py show                   -> print the current state
"""
import sys, json, time
from shipauth import gql

GEN = "gid://shopify/DeliveryProfile/141336838474"
KLEIN = "gid://shopify/DeliveryProfile/142752514378"
LG = "gid://shopify/DeliveryLocationGroup/143336964426"
M = """mutation($id:ID!,$p:DeliveryProfileInput!){
  deliveryProfileUpdate(id:$id, profile:$p){ profile{ id } userErrors{ field message } } }"""
STATE = """{ deliveryProfile(id:"%s"){ profileLocationGroups{ locationGroupZones(first:10){ nodes{ zone{ id name }
  methodDefinitions(first:20){ nodes{ id name active rateProvider{ __typename ... on DeliveryParticipant{ carrierService{ id name } } ... on DeliveryRateDefinition{ price{ amount } } } } } } } } } }""" % GEN

def state():
    zones = []
    for g in gql(STATE)["data"]["deliveryProfile"]["profileLocationGroups"]:
        for z in g["locationGroupZones"]["nodes"]:
            zones.append(z)
    return zones

phase = sys.argv[1] if len(sys.argv) > 1 else "show"
if phase == "show":
    for z in state():
        print(z["zone"]["name"])
        for m in z["methodDefinitions"]["nodes"]:
            rp = m["rateProvider"]
            print("   ", m["name"], rp["__typename"], rp.get("price", {}).get("amount") or rp.get("carrierService", {}).get("name"))
elif phase == "1":
    carrier = sys.argv[2]
    zones_to_update = []
    to_delete = []
    for z in state():
        manual = [m["id"] for m in z["methodDefinitions"]["nodes"] if m["rateProvider"]["__typename"] == "DeliveryRateDefinition"]
        has_carrier = any(m["rateProvider"]["__typename"] == "DeliveryParticipant" for m in z["methodDefinitions"]["nodes"])
        to_delete += manual
        if not has_carrier:
            zones_to_update.append({"id": z["zone"]["id"], "methodDefinitionsToCreate": [{
                "name": "Scenery en Zo verzendregels", "active": True,
                "participant": {"carrierServiceId": carrier, "fixedFee": {"amount": 0, "currencyCode": "EUR"}, "percentageOfRateFee": 0}}]})
    print("zones getting the carrier rate:", len(zones_to_update), "| manual rates to delete:", len(to_delete))
    r = gql(M, {"id": GEN, "p": {"locationGroupsToUpdate": [{"id": LG, "zonesToUpdate": zones_to_update}], "methodDefinitionsToDelete": to_delete}})
    print(r.get("data") or r)
elif phase == "2":
    vids = json.load(open("kleine_items.json"))["variants"]
    for i in range(0, len(vids), 100):
        r = gql(M, {"id": GEN, "p": {"variantsToAssociate": vids[i:i + 100]}})
        d = r.get("data", {}).get("deliveryProfileUpdate") if r.get("data") else r
        print(i, "ok" if d and not d.get("userErrors") else d)
        time.sleep(0.5)
elif phase == "3":
    left = gql("""{ deliveryProfile(id:"%s"){ profileItems(first:1){ nodes{ product{ title } } } } }""" % KLEIN)["data"]["deliveryProfile"]["profileItems"]["nodes"]
    print("items left in Kleine Artikelen:", len(left))
    if not left:
        print(gql("""mutation($id:ID!){ deliveryProfileRemove(id:$id){ job{ id } userErrors{ field message } } }""", {"id": KLEIN}))

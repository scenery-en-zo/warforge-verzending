"""Show the General delivery profile: every zone with its carrier and manual rates.

  python tools/profiles_carrier.py show

Read-only. The one-time switch to the carrier service (September 2026: carrier rate in every zone,
Kleine Artikelen folded into General) is done; its write phases 1-3 are in git history
(git log -- tools/profiles_carrier.py).
The app no longer writes to the merchant's delivery profiles (Shopify's market-driven shipping
attestation, 2026-11-07). Adding the carrier to shipping:
  - old model: by hand in Settings -> Shipping and delivery -> General profile -> the zone -> Add rate ->
    "Use carrier or app to calculate rates" -> Scenery en Zo verzendregels;
  - market-driven shipping: python tools/verzending_markten.py carrier <carrierServiceGid>
"""
import sys
from shipauth import gql, market_driven, LEGACY_STOP

if market_driven():
    sys.exit(LEGACY_STOP)

GEN = "gid://shopify/DeliveryProfile/141336838474"
STATE = """{ deliveryProfile(id:"%s"){ profileLocationGroups{ locationGroupZones(first:10){ nodes{ zone{ id name }
  methodDefinitions(first:20){ nodes{ id name active rateProvider{ __typename ... on DeliveryParticipant{ carrierService{ id name } } ... on DeliveryRateDefinition{ price{ amount } } } } } } } } } }""" % GEN

if (sys.argv[1] if len(sys.argv) > 1 else "show") != "show":
    sys.exit(__doc__)
for g in gql(STATE)["data"]["deliveryProfile"]["profileLocationGroups"]:
    for z in g["locationGroupZones"]["nodes"]:
        print(z["zone"]["name"])
        for m in z["methodDefinitions"]["nodes"]:
            rp = m["rateProvider"]
            print("   ", m["name"], rp["__typename"], rp.get("price", {}).get("amount") or rp.get("carrierService", {}).get("name"))

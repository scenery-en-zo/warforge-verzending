"""Register (or update) the carrier service as the 'Product Brievenbuspakket' app.

  python register_carrier.py https://sceneryenzo-verzendregels.<account>.workers.dev/rates
"""
import sys
from shipauth import gql

NAME = "Scenery en Zo verzendregels"
callback = sys.argv[1]
existing = gql("{ carrierServices(first: 20) { nodes { id name callbackUrl active } } }")
nodes = (existing.get("data") or {}).get("carrierServices", {}).get("nodes")
if nodes is None:
    print("cannot list carrier services:", existing); sys.exit(1)
print("existing:", nodes)
mine = next((c for c in nodes if c["name"] == NAME), None)
if mine:
    r = gql("""mutation($i: DeliveryCarrierServiceUpdateInput!) { carrierServiceUpdate(input: $i) {
              carrierService { id callbackUrl active } userErrors { field message } } }""",
            {"i": {"id": mine["id"], "callbackUrl": callback, "active": True}})
else:
    r = gql("""mutation($i: DeliveryCarrierServiceCreateInput!) { carrierServiceCreate(input: $i) {
              carrierService { id callbackUrl active } userErrors { field message } } }""",
            {"i": {"name": NAME, "callbackUrl": callback, "active": True, "supportsServiceDiscovery": False}})
print(r.get("data") or r)

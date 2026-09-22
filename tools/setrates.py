import sys, json, requests, types
sys.modules["openai"]=types.SimpleNamespace(api_key=None)
sys.path.insert(0, "D:/Projects/product-beschrijvingen")
import beschrijving as b
tok=b.get_access_token(); H={"X-Shopify-Access-Token":tok,"Content-Type":"application/json"}
def gql(q,v=None): return requests.post(f"https://{b.SHOPIFY_STORE}/admin/api/2026-01/graphql.json",headers=H,json={"query":q,"variables":v or {}}).json()
sid=gql("{ shop { id } }")["data"]["shop"]["id"]
M="""mutation($m:[MetafieldsSetInput!]!){ metafieldsSet(metafields:$m){ metafields{ id key } userErrors{ field message } } }"""
r=gql(M,{"m":[{"ownerId":sid,"namespace":"custom","key":"verzendtarieven","type":"json","value":open(__import__("os").path.join(__import__("os").path.dirname(__file__),"rates.json")).read()}]})
print(r.get("data") or r)

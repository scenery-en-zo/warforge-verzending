import re, requests
env={}
for l in open('D:/Projects/verzendingen/.env',encoding='utf-8'):
    m=re.match(r'\s*([A-Z_]+)\s*=\s*["\']?([^"\'\s]*)',l)
    if m: env[m.group(1)]=m.group(2)
STORE=env["SHOPIFY_STORE"]
API="2026-10"
tok=requests.post(f"https://{STORE}/admin/oauth/access_token",data={"grant_type":"client_credentials","client_id":env["CLIENT_ID"],"client_secret":env["CLIENT_SECRET"]}).json()["access_token"]
H={"X-Shopify-Access-Token":tok,"Content-Type":"application/json"}
def gql(q,v=None,version=API):
    return requests.post(f"https://{STORE}/admin/api/{version}/graphql.json",headers=H,json={"query":q,"variables":v or {}}).json()

def market_driven():
    """True when the shop is on market-driven shipping (rates per market, delivery profiles no longer live)."""
    r=gql("{ shop { features { marketDrivenShipping } } }")
    f=((r.get("data") or {}).get("shop") or {}).get("features")
    if f is None:
        raise SystemExit(f"cannot read shop.features.marketDrivenShipping: {r.get('errors') or r}")
    return f["marketDrivenShipping"]

LEGACY_STOP=("Deze winkel gebruikt marktgestuurde verzending. Verzendprofielen zijn daar niet meer de echte instellingen:\n"
             "schrijven lijkt te lukken maar verandert niets. Gebruik tools/verzending_markten.py.")

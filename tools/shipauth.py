import re, requests
env={}
for l in open('D:/Projects/verzendingen/.env',encoding='utf-8'):
    m=re.match(r'\s*([A-Z_]+)\s*=\s*["\']?([^"\'\s]*)',l)
    if m: env[m.group(1)]=m.group(2)
STORE=env["SHOPIFY_STORE"]
tok=requests.post(f"https://{STORE}/admin/oauth/access_token",data={"grant_type":"client_credentials","client_id":env["CLIENT_ID"],"client_secret":env["CLIENT_SECRET"]}).json()["access_token"]
H={"X-Shopify-Access-Token":tok,"Content-Type":"application/json"}
def gql(q,v=None):
    return requests.post(f"https://{STORE}/admin/api/2026-01/graphql.json",headers=H,json={"query":q,"variables":v or {}}).json()

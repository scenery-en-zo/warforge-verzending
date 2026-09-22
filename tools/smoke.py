import re, json, hmac, hashlib, base64, requests, time, sys
env={}
for l in open("D:/Projects/verzendingen/.env",encoding="utf-8"):
    m=re.match(r'\s*([A-Z_]+)\s*=\s*["\']?([^"\'\s]*)',l)
    if m: env[m.group(1)]=m.group(2)
URL="https://sceneryenzo-verzendregels.sceneryenzo.workers.dev"
print("health:",requests.get(URL+"/health").json())
vars_=[v for v in json.load(open("variants.json")) if v["product"]["status"]=="ACTIVE"]
def pid(pred):
    v=next(v for v in vars_ if pred(v)); return v["product"]["id"].split("/")[-1], v["product"]["title"][:30]
K=set(json.load(open("kleine_items.json"))["variants"])
paint=pid(lambda v: v["product"]["vendor"]=="Reaper Master Series Paints" and v["id"] in K and "Kit" not in v["product"]["title"])
mini=pid(lambda v: v["product"]["vendor"]=="Reaper Miniatures" and v["product"]["productType"]=="Miniature" and v["sku"] and v["sku"].isdigit() and v["id"] in set(json.load(open("kleine_items.json"))["variants"]))
terrain=pid(lambda v: v["product"]["productType"]=="Terrain")
print("test products:",paint,mini,terrain)
def call(country, items):
    body=json.dumps({"rate":{"origin":{"country":"NL"},"destination":{"country":country},"items":[{"name":"x","sku":"x","quantity":q,"grams":g,"product_id":int(p),"requires_shipping":True} for p,q,g in items],"currency":"EUR"}})
    sig=base64.b64encode(hmac.new(env["CLIENT_SECRET"].encode(),body.encode(),hashlib.sha256).digest()).decode()
    t=time.time(); r=requests.post(URL+"/rates",data=body,headers={"Content-Type":"application/json","X-Shopify-Hmac-Sha256":sig})
    print(f"{country} {[(q,g) for _,q,g in items]} -> {r.status_code} {[(x['service_name'],x['total_price']) for x in r.json().get('rates',[])]} ({time.time()-t:.2f}s)")
call("NL",[(paint[0],3,27),(mini[0],2,16)])
call("NL",[(paint[0],3,27),(mini[0],4,16)])
call("NL",[(terrain[0],1,40)])
call("BE",[(paint[0],1,27)])
call("FR",[(paint[0],1,27)])
r=requests.post(URL+"/rates",data="{}",headers={"X-Shopify-Hmac-Sha256":"bad"}); print("bad hmac ->",r.status_code)

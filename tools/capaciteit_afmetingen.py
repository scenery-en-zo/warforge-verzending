"""Excel report: per variant the capacity the Worker computes, and where it comes from.

  python tools/capaciteit_afmetingen.py [uitvoer.xlsx]

Default output: capaciteit_afmetingen_<datum>.xlsx in the verzendingen folder (next to .env)
Read-only: changes nothing in Shopify. Uses the shop's rules (custom.brievenbus_capaciteit_standaard)
and the Worker's own logic through tools/resolve_capacity.ts, so it needs Node (npm install).
Packed dimensions need Admin API 2027-01 (a release candidate until 1 January 2027).
"""
import sys, os, json, shutil, subprocess, datetime
from collections import Counter
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from shipauth import gql, STORE, OUT_DIR

DIM_API = "2027-01"
TO_CM = {"CENTIMETERS": 1, "INCHES": 2.54}
TO_G = {"GRAMS": 1, "KILOGRAMS": 1000, "OUNCES": 28.349523125, "POUNDS": 453.59237}
STATUS = {"ACTIVE": "actief", "DRAFT": "concept", "ARCHIVED": "gearchiveerd", "UNLISTED": "niet in lijst"}
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def bron(source):
    """The Worker's source code in words for the shop owner."""
    if source == "afmetingen":
        return "eigen afmetingen"
    if source.startswith("afmetingen:"):
        rest = source.split(":", 1)[1]
        return {"vendor_type": "maat per soort (leverancier + type)", "type": "maat per soort (type)"}.get(
            rest, "maat per " + rest.replace("collection:", "collectie ").replace("tag:", "tag ").replace("title:", "titelgroep "))
    if source == "product":
        return "productveld (met de hand)"
    if source == "onbekend":
        return "niet gemeten: pakket"
    if source == "default":
        return "standaardregel"
    if source == "unknown":
        return "product onbekend"
    return "regel " + source.replace("collection:", "collectie ").replace("tag:", "tag ").replace("title:", "titelgroep ").replace("vendor_type", "leverancier + type")


r = gql("""{ shop{ m: metafield(namespace:"custom",key:"brievenbus_capaciteit_standaard"){ value } } }""")
field = ((r.get("data") or {}).get("shop") or {}).get("m")
rules = json.loads(field["value"]) if field else {}

Q = """query($c:String){ products(first:20, after:$c){ pageInfo{ hasNextPage endCursor } nodes{
  legacyResourceId title productType vendor status tags
  collections(first:10){ nodes{ handle } }
  cap: metafield(namespace:"custom",key:"brievenbus_capaciteit"){ value }
  grp: metafield(namespace:"custom",key:"brievenbus_groep"){ value }
  variants(first:30){ nodes{ title sku inventoryItem{ measurement{
    weight{ value unit } packedDimensions{ length width height unit } } } } } } } }"""

rows, items, c = [], [], None
while True:
    r = gql(Q, {"c": c}, version=DIM_API)
    d = (r.get("data") or {}).get("products")
    if d is None:
        sys.exit(f"kan producten niet lezen met API {DIM_API}: {r.get('errors') or r}")
    for p in d["nodes"]:
        cap = None
        if p["cap"]:
            try:
                cap = float(p["cap"]["value"])
            except ValueError:
                pass
        info = {"title": p["title"], "productType": p["productType"] or "", "vendor": p["vendor"] or "", "tags": p["tags"],
                "collections": [n["handle"] for n in p["collections"]["nodes"]],
                "capacityOverride": cap, "groupOverride": p["grp"]["value"] if p["grp"] else None}
        for v in p["variants"]["nodes"]:
            m = v["inventoryItem"]["measurement"]
            w = m.get("weight") or {}
            grams = round((w.get("value") or 0) * TO_G.get(w.get("unit"), 1), 1)
            pd = m.get("packedDimensions") or {}
            f = TO_CM.get(pd.get("unit"), 1)
            dims = [round((pd.get(k) or 0) * f, 2) for k in ("length", "width", "height")]
            has = all(x > 0 for x in dims)
            items.append({"product": info, "grams": grams,
                          "dims": {"length": dims[0], "width": dims[1], "height": dims[2]} if has else None})
            rows.append([
                p["title"], "" if v["title"] == "Default Title" else v["title"], v["sku"] or "",
                p["productType"], p["vendor"], STATUS.get(p["status"], p["status"]),
                *(dims if has else ["", "", ""]), grams or "",
                None, None, None,  # capacity, source, group: filled in below
                int(cap) if cap is not None else "",
                f"https://admin.shopify.com/store/{STORE.split('.')[0]}/products/{p['legacyResourceId']}",
            ])
    if not d["pageInfo"]["hasNextPage"]:
        break
    c = d["pageInfo"]["endCursor"]

npx = shutil.which("npx") or "npx"
res = subprocess.run([npx, "tsx", os.path.join(REPO, "tools", "resolve_capacity.ts")], cwd=REPO,
                     input=json.dumps({"rules": rules, "items": items}), capture_output=True, text=True)
if res.returncode != 0:
    sys.exit("resolve_capacity.ts mislukt (npm install gedaan?):\n" + res.stderr[-2000:])
for row, out in zip(rows, json.loads(res.stdout)):
    row[10] = out["capacity"]
    row[11] = bron(out["source"])
    row[12] = out["group"] or ""

rows.sort(key=lambda r: (r[5] != "actief", r[10] == 0, r[3], r[4], r[0], r[1]))
out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(OUT_DIR, f"capaciteit_afmetingen_{datetime.date.today():%Y-%m-%d}.xlsx")

wb = Workbook()
ws = wb.active
ws.title = "Capaciteit"
ws.append(["Product", "Variant", "SKU", "Type", "Leverancier", "Status", "Lengte (cm)", "Breedte (cm)", "Hoogte (cm)",
           "Gewicht (g)", "Capaciteit per brievenbuspakket", "Waar komt het vandaan", "Groep",
           "Productveld capaciteit", "Admin link"])
for r in rows:
    ws.append(r)
for cell in ws[1]:
    cell.font = Font(name="Arial", bold=True)
green = PatternFill("solid", fgColor="E3EDE7")
for row in ws.iter_rows(min_row=2):
    for cell in row:
        cell.font = Font(name="Arial")
    if isinstance(row[10].value, int) and row[10].value > 0:
        row[10].fill = green
    row[14].hyperlink = row[14].value
    row[14].font = Font(name="Arial", color="0000FF", underline="single")
for i, w in enumerate([48, 22, 16, 12, 22, 10, 11, 11, 11, 11, 14, 34, 12, 14, 60], 1):
    ws.column_dimensions[get_column_letter(i)].width = w
ws.freeze_panes = "A2"
ws.auto_filter.ref = ws.dimensions

box = rules.get("letterbox_box_cm") or [21, 14.8, 3.2]
strict = rules.get("unmeasured_parcel_only", True)
active = [r for r in rows if r[5] == "actief"]
lg = wb.create_sheet("Uitleg")
for l in [
    f"Brievenbuspakket: {box[0]} x {box[1]} x {box[2]} cm, maximaal {rules.get('letterbox_max_grams', 2000)} gram in totaal.",
    "Capaciteit = hoeveel stuks van dit product in een brievenbuspakket passen; 0 = altijd een pakket.",
    "Volgorde: tag geen-brievenbus, eigen afmetingen (Productpagina > Verzending), productveld Brievenbus capaciteit,",
    "  dan de maat per soort in Brievenbus capaciteit standaard (collectie, tag, leverancier + type, type).",
    ("Niet gemeten = pakket (unmeasured_parcel_only staat aan)." if strict
     else "unmeasured_parcel_only staat uit: niet gemeten producten volgen de oude capaciteitsregels."),
    f"Gemaakt op {datetime.date.today():%d-%m-%Y}. Varianten: {len(rows)}, actief: {len(active)}, "
    f"actief en past in een brievenbuspakket: {sum(1 for r in active if isinstance(r[10], int) and r[10] > 0)}.",
]:
    lg.append([l])
lg.column_dimensions["A"].width = 130
wb.save(out)
print(len(rows), "varianten ->", out)
for k, n in Counter(r[11] for r in active).most_common():
    print(f"  actief, {k}: {n}")

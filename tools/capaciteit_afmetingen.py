"""Excel report: what the Worker computes from the packed dimensions of every variant.

  python tools/capaciteit_afmetingen.py [uitvoer.xlsx]

Default output: D:/Projects/verzendingen/capaciteit_afmetingen_<datum>.xlsx
Read-only: changes nothing in Shopify. Box size, weight limit and never-tag come from the shop field
custom.brievenbus_capaciteit_standaard (letterbox_box_cm, letterbox_max_grams, never_tag).

The calculation is a copy of piecesInBox / capacityFromDims in src/letterbox.ts; change both together.
Packed dimensions need Admin API 2027-01 (a release candidate until 1 January 2027).
"""
import sys, json, math, datetime
from itertools import permutations
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from shipauth import gql, STORE

DIM_API = "2027-01"
TO_CM = {"CENTIMETERS": 1, "INCHES": 2.54}
TO_G = {"GRAMS": 1, "KILOGRAMS": 1000, "OUNCES": 28.349523125, "POUNDS": 453.59237}

STATUS = {"ACTIVE": "actief", "DRAFT": "concept", "ARCHIVED": "gearchiveerd", "UNLISTED": "niet in lijst"}

r = gql("""{ shop{ m: metafield(namespace:"custom",key:"brievenbus_capaciteit_standaard"){ value } } }""")
field = ((r.get("data") or {}).get("shop") or {}).get("m")
rules = json.loads(field["value"]) if field else {}
box = rules.get("letterbox_box_cm")
if not (isinstance(box, list) and len(box) == 3 and all(isinstance(x, (int, float)) and x > 0 for x in box)):
    box = [21, 14.8, 3.2]
max_g = rules.get("letterbox_max_grams", 2000)
never = rules.get("never_tag", "geen-brievenbus")


def pieces_in_box(d):
    if len(d) != 3 or not all(x > 0 for x in d):
        return 0
    return max(math.floor(box[0] / a + 1e-9) * math.floor(box[1] / b + 1e-9) * math.floor(box[2] / c + 1e-9)
               for a, b, c in permutations(d))


Q = """query($c:String){ products(first:50, after:$c){ pageInfo{ hasNextPage endCursor } nodes{
  legacyResourceId title productType vendor status tags
  cap: metafield(namespace:"custom",key:"brievenbus_capaciteit"){ value }
  variants(first:50){ nodes{ title sku inventoryItem{ measurement{
    weight{ value unit } packedDimensions{ length width height unit } } } } } } } }"""

rows, c = [], None
while True:
    r = gql(Q, {"c": c}, version=DIM_API)
    d = (r.get("data") or {}).get("products")
    if d is None:
        sys.exit(f"kan producten niet lezen met API {DIM_API}: {r.get('errors') or r}")
    for p in d["nodes"]:
        for v in p["variants"]["nodes"]:
            m = v["inventoryItem"]["measurement"]
            w = m.get("weight") or {}
            grams = round((w.get("value") or 0) * TO_G.get(w.get("unit"), 1), 1)
            pd = m.get("packedDimensions") or {}
            f = TO_CM.get(pd.get("unit"), 1)
            dims = [round((pd.get(k) or 0) * f, 2) for k in ("length", "width", "height")]
            has = all(x > 0 for x in dims)
            by_size = pieces_in_box(dims) if has else None
            by_weight = math.floor(max_g / grams) if has and grams > 0 else None
            cap = None if not has else (by_size if by_weight is None else min(by_size, by_weight))
            if never in p["tags"]:
                result = f"0 (tag {never})"
            elif has:
                result = cap
            else:
                result = "geen afmetingen: regels/productveld"
            rows.append([
                p["title"], "" if v["title"] == "Default Title" else v["title"], v["sku"] or "",
                p["productType"], p["vendor"], STATUS.get(p["status"], p["status"]),
                *(dims if has else ["", "", ""]), grams or "",
                by_size if has else "", by_weight if by_weight is not None else "", result,
                int(p["cap"]["value"]) if p["cap"] else "",
                f"https://admin.shopify.com/store/{STORE.split('.')[0]}/products/{p['legacyResourceId']}",
            ])
    if not d["pageInfo"]["hasNextPage"]:
        break
    c = d["pageInfo"]["endCursor"]

rows.sort(key=lambda r: (r[6] == "", r[5] != "actief", r[3], r[4], r[0], r[1]))
out = sys.argv[1] if len(sys.argv) > 1 else f"D:/Projects/verzendingen/capaciteit_afmetingen_{datetime.date.today():%Y-%m-%d}.xlsx"

wb = Workbook()
ws = wb.active
ws.title = "Capaciteit"
ws.append(["Product", "Variant", "SKU", "Type", "Leverancier", "Status", "Lengte (cm)", "Breedte (cm)", "Hoogte (cm)",
           "Gewicht (g)", "Past op maat", "Past op gewicht", "Capaciteit per brievenbuspakket", "Productveld (wordt overschreven door afmetingen)", "Admin link"])
for r in rows:
    ws.append(r)
for cell in ws[1]:
    cell.font = Font(name="Arial", bold=True)
green = PatternFill("solid", fgColor="E3EDE7")
for row in ws.iter_rows(min_row=2):
    for cell in row:
        cell.font = Font(name="Arial")
    if isinstance(row[12].value, int):
        row[12].fill = green
    row[14].hyperlink = row[14].value
    row[14].font = Font(name="Arial", color="0000FF", underline="single")
for i, w in enumerate([48, 22, 16, 12, 22, 10, 11, 11, 11, 11, 12, 13, 22, 18, 60], 1):
    ws.column_dimensions[get_column_letter(i)].width = w
ws.freeze_panes = "A2"
ws.auto_filter.ref = ws.dimensions

lg = wb.create_sheet("Uitleg")
for l in [
    f"Brievenbuspakket: {box[0]} x {box[1]} x {box[2]} cm, maximaal {max_g} gram in totaal.",
    "Heeft een variant lengte, breedte en hoogte (Productpagina > Verzending), dan rekent de verzendmodule zelf uit hoeveel stuks er in passen.",
    "Past op maat: hoeveel stuks naast en op elkaar in het pakket passen, in de beste ligging (rechtop, plat of op de zijkant).",
    "Past op gewicht: hoeveel stuks onder het maximale totaalgewicht blijven. De capaciteit is de kleinste van de twee.",
    "0 = past niet (te groot of te dik). Een product met de tag '" + never + "' gaat altijd als pakket.",
    "Zonder (complete) afmetingen gelden de oude regels: het productveld Brievenbus capaciteit, daarna de standaarden.",
    f"Gemaakt op {datetime.date.today():%d-%m-%Y}. Varianten: {len(rows)}, met afmetingen: {sum(1 for r in rows if r[6] != '')}.",
]:
    lg.append([l])
lg.column_dimensions["A"].width = 130
wb.save(out)
print(len(rows), "varianten,", sum(1 for r in rows if r[6] != ""), "met afmetingen ->", out)

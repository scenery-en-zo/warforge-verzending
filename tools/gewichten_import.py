"""Apply the weights filled in with gewichten_export.py.

  python tools/gewichten_import.py D:/Projects/verzendingen/producten_zonder_gewicht_2026-09-22.xlsx

Reads column "Gewicht (gram)" (and the hidden GID columns) and writes the weight to every
variant that has a number there. Empty cells are skipped. Prints a summary.
"""
import sys
from openpyxl import load_workbook
from shipauth import gql

M = """mutation($pid:ID!,$v:[ProductVariantsBulkInput!]!){
  productVariantsBulkUpdate(productId:$pid, variants:$v){ userErrors{ field message } } }"""
PQ = """query($id:ID!){ productVariant(id:$id){ product{ id } } }"""

ws = load_workbook(sys.argv[1], data_only=True)["Zonder gewicht"]
head = [c.value for c in ws[1]]
col = {h: i for i, h in enumerate(head)}
todo = {}
for row in ws.iter_rows(min_row=2, values_only=True):
    g = row[col["Gewicht (gram)"]]
    if g in (None, ""):
        continue
    try:
        g = float(str(g).replace(",", "."))
    except ValueError:
        print("overgeslagen (geen getal):", row[col["Product"]], row[col["Variant"]], g); continue
    if g <= 0:
        continue
    todo[row[col["Variant GID"]]] = g

print(len(todo), "varianten met een ingevuld gewicht")
by_product = {}
for vid, g in todo.items():
    pid = gql(PQ, {"id": vid})["data"]["productVariant"]["product"]["id"]
    by_product.setdefault(pid, []).append({"id": vid, "inventoryItem": {"measurement": {"weight": {"value": g, "unit": "GRAMS"}}}})

ok = err = 0
for pid, variants in by_product.items():
    r = gql(M, {"pid": pid, "v": variants})
    e = (r.get("data") or {}).get("productVariantsBulkUpdate", {}).get("userErrors") or r.get("errors")
    if e:
        err += len(variants); print("fout", pid, e)
    else:
        ok += len(variants)
print("bijgewerkt:", ok, "| fouten:", err)

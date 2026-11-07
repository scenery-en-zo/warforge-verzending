"""Set the size and weight once per group of products, in bulk, through Excel.

  python tools/soorten_afmetingen.py export [uitvoer.xlsx]
  python tools/soorten_afmetingen.py import <bestand.xlsx> [--dry]

export: sheets with yellow columns to fill in (length, width, height in cm, weight in g;
        measure ONE example, with its packaging), best sellers first when the app may read orders
        (scope read_orders; without read_all_orders Shopify gives the last 60 days):
          Verpakkingsgroepen  product lines found from the titles, e.g. every "Reaper MSP Core Colors"
                              pot, plus SUGGESTED groups: unmeasured light products with the same
                              supplier, type, name stem and a weight within 30% (check before filling
                              in). With the number of products the Worker will match and the products
                              whose weight does not fit (check those first). Add your own title texts
                              in the empty rows. A new product whose title contains the text is covered
                              automatically.
          Losse producten     unmeasured light products in no group: a worklist (not imported).
          Soorten             one row per supplier + product type, for kinds whose products all ship
                              in the same packaging (see the weight range).
          Maatklassen         size classes per product tag (maat-klein, maat-plat, ...), for products
                              that differ: give them the tag in bulk in the Shopify product list.
        Default output: soorten_afmetingen_<datum>.xlsx in the verzendingen folder (next to .env)
import: writes every row with length, width and height into the shop field
        custom.brievenbus_capaciteit_standaard as {"cm": [l, b, h], "gram": g} under by_title,
        by_vendor_type or by_tag. An old capacity number for that key is replaced; a "groep" is kept.
        Empty rows are skipped; nothing is ever deleted. --dry shows the changes without writing.
        It refuses when the field was changed in the admin after it was read (compareDigest).

Read-only except `import` without --dry, which only the shop owner runs.
"""
import os, re, sys, json, statistics, datetime
from collections import defaultdict
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from shipauth import gql, STORE, OUT_DIR

TO_G = {"GRAMS": 1, "KILOGRAMS": 1000, "OUNCES": 28.349523125, "POUNDS": 453.59237}
FIELD = """{ shop{ id m: metafield(namespace:"custom",key:"brievenbus_capaciteit_standaard"){ value compareDigest } } }"""
SET = """mutation($m:[MetafieldsSetInput!]!){ metafieldsSet(metafields:$m){ metafields{ id } userErrors{ field message code } } }"""
SIZE = ["Lengte (cm)", "Breedte (cm)", "Hoogte (cm)", "Gewicht (g)"]
SKU = re.compile(r"\b\d{2,3}\.\d{3}\b|\b\d{4,6}\b")  # 09241, 76.503: the variable part of a product-line title


def read_field():
    d = gql(FIELD)["data"]["shop"]
    m = d["m"]
    return d["id"], (json.loads(m["value"]) if m else {}), (m["compareDigest"] if m else None)


def title_pattern(title):
    """The product-line words after the last SKU number: '<colour> 09241 Reaper MSP Core Colors' -> 'Reaper MSP Core Colors'."""
    parts = SKU.split(title)
    after = parts[-1].strip(" -:") if len(parts) > 1 else ""
    return after if len(after.split()) >= 2 else None


def title_match(title, patterns):
    """Same as titleMatch in src/letterbox.ts: the longest pattern the title contains, any case."""
    t = title.lower()
    hits = [p for p in patterns if p.strip() and p.strip().lower() in t]
    return max(hits, key=lambda p: len(p.strip())) if hits else None


def measurement(rule):
    if isinstance(rule, dict) and isinstance(rule.get("cm"), list) and len(rule["cm"]) == 3:
        return rule["cm"] + [rule.get("gram", "")]
    return ["", "", "", ""]


def describe(rule):
    if rule is None:
        return ""
    if isinstance(rule, (int, float)):
        return f"capaciteit {rule:g}" + (" (nooit)" if rule == 0 else "")
    if "cm" in rule:
        return "maat " + " x ".join(f"{x:g}" for x in rule["cm"]) + (f", {rule['gram']:g} g" if rule.get("gram") else "")
    if "weight_bands" in rule:
        return "capaciteit op gewicht"
    return f"capaciteit {rule.get('cap', '?')}" + (f", groep {rule['groep']}" if rule.get("groep") else "")


def style(ws, widths, yellow_cols, link_col=None):
    for cell in ws[1]:
        cell.font = Font(name="Arial", bold=True)
    fill = PatternFill("solid", fgColor="FFFF00")
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = Font(name="Arial")
        for i in yellow_cols:
            row[i].fill = fill
        if link_col is not None and row[link_col].value:
            row[link_col].hyperlink = row[link_col].value
            row[link_col].font = Font(name="Arial", color="0000FF", underline="single")
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"


def load_products():
    Q = """query($c:String){ products(first:100, after:$c){ pageInfo{ hasNextPage endCursor } nodes{
      id legacyResourceId title productType vendor status tags
      cap: metafield(namespace:"custom",key:"brievenbus_capaciteit"){ value }
      variants(first:50){ nodes{ inventoryItem{ measurement{ weight{ value unit } } } } } } } }"""
    out, c = [], None
    while True:
        d = gql(Q, {"c": c})["data"]["products"]
        for p in d["nodes"]:
            if p["status"] == "ARCHIVED":
                continue
            ws = []
            for v in p["variants"]["nodes"]:
                w = v["inventoryItem"]["measurement"].get("weight") or {}
                ws.append((w.get("value") or 0) * TO_G.get(w.get("unit"), 1))
            out.append({"id": p["id"], "title": p["title"], "vendor": p["vendor"] or "", "type": p["productType"] or "", "tags": p["tags"],
                        "active": p["status"] == "ACTIVE", "variants": len(ws), "weights": [g for g in ws if g > 0],
                        "has_cap": p["cap"] is not None, "sold": 0,
                        "link": f"https://admin.shopify.com/store/{STORE.split('.')[0]}/products/{p['legacyResourceId']}"})
        if not d["pageInfo"]["hasNextPage"]:
            return out
        c = d["pageInfo"]["endCursor"]


def load_sales(days=365):
    """Units sold per product id in the last `days`; None when the app may not read orders (scope read_orders).
    Without read_all_orders Shopify only returns the last 60 days, whatever `days` says."""
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    Q = """query($c:String,$q:String){ orders(first:100, after:$c, query:$q){ pageInfo{ hasNextPage endCursor }
      nodes{ createdAt lineItems(first:50){ nodes{ quantity product{ id } } } } } }"""
    sold, first, c = defaultdict(int), None, None
    while True:
        r = gql(Q, {"c": c, "q": f"created_at:>={since}"})
        d = (r.get("data") or {}).get("orders")
        if d is None:
            return None, None
        for o in d["nodes"]:
            first = min(first or o["createdAt"], o["createdAt"])
            for li in o["lineItems"]["nodes"]:
                if li["product"]:
                    sold[li["product"]["id"]] += li["quantity"]
        if not d["pageInfo"]["hasNextPage"]:
            return sold, (first or since)[:10]
        c = d["pageInfo"]["endCursor"]


LIGHT = 250  # grams: heavier products are left as parcels, not worth measuring first


def decided(p, rules):
    """Does the Worker already have an answer for this product without a new measurement? Mirrors the
    strict path of resolveCapacity in src/letterbox.ts (collection rules and a variant's own dimensions
    are left out: the shop has no collection rules and only a handful of dimensions)."""
    if rules.get("never_tag", "geen-brievenbus") in p["tags"] or p["has_cap"]:
        return True
    if rules.get("unmeasured_parcel_only", True) is False:
        return True  # the capacity rules and the default answer for everything
    g = p["weights"][0] if p["weights"] else 0
    hit = title_match(p["title"], rules.get("by_title") or {})
    for rule in [(rules.get("by_tag") or {}).get(t) for t in p["tags"]] + [
            (rules.get("by_title") or {}).get(hit) if hit else None,
            (rules.get("by_vendor_type") or {}).get(f"{p['vendor']}|{p['type']}"),
            (rules.get("by_type") or {}).get(p["type"])]:
        if rule is None:
            continue
        if isinstance(rule, (int, float)):
            if rule <= 0:
                return True
            continue
        if isinstance(rule.get("cm"), list) or ("weight_bands" in rule and g > 0) or rule.get("cap", 1) <= 0:
            return True
    return False


def name_stem(title):
    """The last two words before the first number: 'Grass TUFTS - 12mm ...' -> 'grass tufts'."""
    words = [w for w in re.findall(r"[a-zà-ÿ]+", re.split(r"\b\d", title)[0].lower()) if len(w) > 2]
    return " ".join(words[-2:]) if len(words) >= 2 else None


def suggest_groups(candidates, taken, everyone):
    """Suggested packaging groups among unmeasured light products: same supplier, type and name stem,
    3 or more products whose weights all lie within 30% of their median, and no other active product
    whose title contains the same text weighs differently. Returns {title text: [products]}."""
    clusters = defaultdict(list)
    for p in candidates:
        s = name_stem(p["title"])
        if s:
            clusters[(p["vendor"], p["type"], s)].append(p)
    out = {}
    for (_, _, stem), ps in clusters.items():
        ws = [p["weights"][0] for p in ps if p["weights"]]
        if len(ps) < 3 or len(ws) < len(ps) or not all(stem in p["title"].lower() for p in ps):
            continue
        med = statistics.median(ws)
        if not all(0.7 * med <= w <= 1.3 * med for w in ws):
            continue
        t = ps[0]["title"]
        i = t.lower().find(stem)
        key = re.sub(r"\s+", " ", t[i:i + len(stem)])  # the stem as it is written in the title
        reach = [p["weights"][0] for p in everyone if stem in p["title"].lower() and p["weights"]]
        if not all(0.7 * med <= w <= 1.3 * med for w in reach):
            continue  # the text also catches products of another size: not one packaging
        if key.lower() not in {k.lower() for k in taken} | {k.lower() for k in out}:
            out[key] = ps
    return out


def export(out):
    _, rules, _ = read_field()
    products = load_products()
    active = [p for p in products if p["active"]]
    sales, since = load_sales()
    if sales is None:
        print("verkoopcijfers niet beschikbaar: de app heeft read_orders nodig; gesorteerd op aantal producten")
    else:
        for p in products:
            p["sold"] = sales.get(p["id"], 0)
    wb = Workbook()

    # Verpakkingsgroepen: product lines from the titles (3+ active products), those already in the rules,
    # and suggestions: unmeasured light products with the same name stem and weight.
    by_title = rules.get("by_title") or {}
    found = defaultdict(int)
    for p in active:
        pat = title_pattern(p["title"])
        if pat:
            found[pat] += 1
    lines = {k for k, n in found.items() if n >= 3}
    open_light = [p for p in active if not decided(p, rules) and not title_match(p["title"], lines | set(by_title))
                  and (not p["weights"] or p["weights"][0] <= LIGHT)]
    suggested = suggest_groups([p for p in open_light if p["weights"]], lines | set(by_title), active)
    patterns = sorted(lines | set(by_title) | set(suggested))
    members = defaultdict(list)
    for p in active:
        hit = title_match(p["title"], patterns)
        if hit:
            members[hit].append(p)
    origin = lambda k: ("al ingesteld" if k in by_title else
                        "productlijn (titel)" if k in lines else "voorstel: eerst controleren")
    sold_col = f"Verkocht sinds {since}" if sales is not None else "Verkocht (app mist read_orders)"
    vg = wb.active
    vg.title = "Verpakkingsgroepen"
    vg.append(["Titel bevat", "Herkomst", "Producten", sold_col, "Gewicht mediaan (g)", "Afwijkend gewicht",
               "Afwijkende producten (controleren)", "Voorbeeldproduct", "Admin link", "Nu ingesteld", *SIZE])
    order = lambda k: (-sum(p["sold"] for p in members[k]), -len(members[k]), k)
    for pat in sorted(patterns, key=order):
        ps = members[pat]
        weights = [p["weights"][0] for p in ps if p["weights"]]
        med = statistics.median(weights) if weights else 0
        odd = [p for p in ps if p["weights"] and med and not 0.7 * med <= p["weights"][0] <= 1.3 * med]
        odd_txt = "; ".join(f"{p['title'][:40]} ({p['weights'][0]:g} g)" for p in odd[:3]) + (" ..." if len(odd) > 3 else "")
        ex = ps[0] if ps else {"title": "", "link": ""}
        vg.append([pat, origin(pat), len(ps), sum(p["sold"] for p in ps) if sales is not None else "",
                   round(med, 1) if med else "", len(odd), odd_txt, ex["title"], ex["link"],
                   describe(by_title.get(pat)), *measurement(by_title.get(pat))])
    for _ in range(10):
        vg.append([""] * 14)
    style(vg, [30, 22, 10, 12, 12, 10, 56, 40, 28, 20, 10, 10, 10, 10], [0, 10, 11, 12, 13], link_col=8)
    vg.auto_filter.ref = vg.dimensions

    # Losse producten: unmeasured light products in no group, best sellers first. A worklist, not imported:
    # measure the top ones on the product page, or give them a size-class tag.
    grouped = {id(p) for ps in members.values() for p in ps}
    singles = sorted((p for p in open_light if id(p) not in grouped),
                     key=lambda p: (-p["sold"], not p["weights"], p["type"], p["vendor"], p["title"]))
    lp = wb.create_sheet("Losse producten")
    lp.append(["Product", "Leverancier", "Type", "Gewicht (g)", sold_col, "Admin link"])
    for p in singles:
        lp.append([p["title"], p["vendor"], p["type"], round(p["weights"][0], 1) if p["weights"] else "geen gewicht",
                   p["sold"] if sales is not None else "", p["link"]])
    style(lp, [56, 24, 14, 12, 14, 60], [], link_col=5)
    lp.auto_filter.ref = lp.dimensions

    # Soorten: supplier + product type.
    kinds = defaultdict(lambda: {"active": 0, "weights": [], "example": None})
    for p in products:
        k = kinds[(p["vendor"], p["type"])]
        if p["active"]:
            k["active"] += p["variants"]
            k["weights"] += p["weights"]
            k["example"] = k["example"] or (p["title"], p["link"])
    so = wb.create_sheet("Soorten")
    so.append(["Leverancier", "Type", "Actieve varianten", "Gewicht min-max (g)", "Voorbeeldproduct", "Admin link",
               "Nu ingesteld", *SIZE, "Sleutel"])
    for (vendor, ptype), k in sorted(kinds.items(), key=lambda kv: (-kv[1]["active"], kv[0])):
        key = f"{vendor}|{ptype}"
        rule = (rules.get("by_vendor_type") or {}).get(key)
        spread = f"{min(k['weights']):g}-{max(k['weights']):g}" if k["weights"] else "geen gewicht"
        title, link = k["example"] or ("", "")
        so.append([vendor, ptype, k["active"], spread, title, link, describe(rule), *measurement(rule), key])
    style(so, [26, 14, 10, 14, 44, 30, 26, 10, 10, 10, 10, 30], [7, 8, 9, 10], link_col=5)
    so.column_dimensions["L"].hidden = True
    so.auto_filter.ref = so.dimensions

    # Maatklassen: size classes per tag.
    mk = wb.create_sheet("Maatklassen")
    mk.append(["Tag", "Omschrijving (voor jezelf)", *SIZE])
    for tag, rule in (rules.get("by_tag") or {}).items():
        if isinstance(rule, dict) and "cm" in rule:
            mk.append([tag, "", *measurement(rule)])
    for _ in range(8):
        mk.append(["", "", "", "", "", ""])
    style(mk, [22, 40, 10, 10, 10, 10], [0, 2, 3, 4, 5])

    covered = sum(len(v) for v in members.values())
    lg = wb.create_sheet("Uitleg")
    for l in [
        "Vul de maat en het gewicht EEN keer in voor een hele groep producten; de verzendmodule gebruikt ze voor elk product in die groep.",
        "Meet een voorbeeldproduct met verpakking, in centimeters. Gewicht mag leeg: dan telt het eigen gewicht van elk product.",
        "Verpakkingsgroepen: een product hoort bij de langste titeltekst die in zijn titel staat. Bestverkochte groepen staan bovenaan.",
        "  Herkomst 'productlijn (titel)': herkend aan het artikelnummer in de titel, zoals alle Reaper MSP Core Colors-potjes.",
        "  Herkomst 'voorstel: eerst controleren': producten met dezelfde naam en ongeveer hetzelfde gewicht (binnen 30%).",
        "    Kijk of ze echt in dezelfde verpakking gaan voordat je een maat invult; zo niet, laat de rij leeg.",
        "  Kijk ook naar 'Afwijkende producten': meestal een verkeerd ingevuld gewicht, soms een ander product (een set).",
        "  Eigen groep? Vul in een lege rij een stukje titel in dat alleen die producten hebben, plus de maat.",
        f"Losse producten: lichte producten (tot {LIGHT} g) zonder maat en zonder groep, bestverkochte eerst. Dit tabblad wordt niet",
        "  ingelezen: meet de bovenste en vul de maat in op de productpagina, of geef ze een maatklasse-tag (zie Maatklassen).",
        "  Zwaardere producten staan er niet in: die gaan als pakket, en dat is meestal goed.",
        "Soorten: leverancier + type. Alleen invullen als alle producten van die soort dezelfde verpakking hebben (zie Gewicht min-max).",
        "Maatklassen: verzin een tag (bijv. maat-klein), vul de maat in, en geef producten die tag in Shopify:",
        "  Producten > selecteer producten > Meer acties > Tags toevoegen.",
        "Wat voorgaat: tag geen-brievenbus, eigen afmetingen van het product, het productveld Brievenbus capaciteit,",
        "  dan collectie, tag, titel, leverancier + type, type. Producten zonder enige maat gaan als pakket.",
        "Lege rijen worden overgeslagen; er wordt niets gewist.",
        "Toepassen (Hylke): python tools/soorten_afmetingen.py import <dit bestand> --dry, en daarna zonder --dry.",
        f"Gemaakt op {datetime.date.today():%d-%m-%Y}. Actieve producten: {len(active)}, in een verpakkingsgroep: {covered}, "
        f"losse lichte producten zonder maat: {len(singles)}."
        + ("" if sales is not None else " Verkoopcijfers ontbreken: de app heeft het recht read_orders nodig."),
    ]:
        lg.append([l])
    lg.column_dimensions["A"].width = 130
    wb.save(out)
    print(f"{len(patterns)} verpakkingsgroepen ({len(lines)} productlijnen, {len(suggested)} voorstellen; "
          f"{covered} actieve producten), {len(singles)} losse producten, {len(kinds)} soorten -> {out}")


def number(v):
    if v in (None, ""):
        return None
    try:
        x = float(str(v).replace(",", "."))
    except ValueError:
        return None
    return x if x > 0 else None


def read_sheet(ws, key_col):
    head = [c.value for c in ws[1]]
    col = {h: i for i, h in enumerate(head)}
    out = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        key = row[col[key_col]]
        if not key or not str(key).strip():
            continue
        l, b, h, g = (number(row[col[s]]) for s in SIZE)
        if l and b and h:
            out[str(key).strip()] = {"cm": [l, b, h], **({"gram": g} if g else {})}
        elif any((l, b, h)):
            print("overgeslagen (niet alle drie de maten):", key)
    return out


def do_import(path, dry):
    wb = load_workbook(path, data_only=True)
    sheets = {"by_title": ("Verpakkingsgroepen", "Titel bevat"), "by_vendor_type": ("Soorten", "Sleutel"), "by_tag": ("Maatklassen", "Tag")}
    plan = {table: read_sheet(wb[name], key) for table, (name, key) in sheets.items() if name in wb.sheetnames}
    shop_id, rules, digest = read_field()
    new = json.loads(json.dumps(rules))
    changes = 0
    for table, entries in plan.items():
        for key, m in entries.items():
            old = (rules.get(table) or {}).get(key)
            entry = dict(m)
            if isinstance(old, dict) and old.get("groep"):
                entry["groep"] = old["groep"]
            if old != entry:
                new.setdefault(table, {})[key] = entry
                changes += 1
                print(f"{table}[{key}]: {describe(old) or 'niets'} -> {describe(entry)}")
    if not changes:
        print("niets te veranderen")
        return
    if dry:
        print(f"[dry] {changes} wijzigingen, niets geschreven")
        return
    m = {"ownerId": shop_id, "namespace": "custom", "key": "brievenbus_capaciteit_standaard", "type": "json",
         "value": json.dumps(new, ensure_ascii=False, indent=2)}
    if digest:
        m["compareDigest"] = digest
    r = gql(SET, {"m": [m]})
    errs = ((r.get("data") or {}).get("metafieldsSet") or {}).get("userErrors") or r.get("errors")
    print("fout:", errs) if errs else print(f"{changes} wijzigingen geschreven; de verzendmodule gebruikt ze binnen 2 minuten")


args = [a for a in sys.argv[1:] if a != "--dry"]
cmd = args[0] if args else ""
if cmd == "export":
    export(args[1] if len(args) > 1 else os.path.join(OUT_DIR, f"soorten_afmetingen_{datetime.date.today():%Y-%m-%d}.xlsx"))
elif cmd == "import" and len(args) > 1:
    do_import(args[1], "--dry" in sys.argv)
else:
    sys.exit(__doc__)

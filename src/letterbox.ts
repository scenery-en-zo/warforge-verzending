/**
 * Brievenbus-capaciteit: pure decision logic, no I/O.
 *
 * Every product has a capacity: how many pieces fit in ONE A5 brievenbuspakket.
 * A cart "uses" quantity / capacity of the parcel per line; it fits when the
 * sum stays <= 1, no line is parcel-only (capacity 0), no single item is
 * heavier than `item_max_grams`, the total stays under `letterbox_max_grams`,
 * and all lines that carry a group carry the SAME group as every other line
 * (a product with a group may only share a letterbox with its own group).
 *
 * Resolution order for the capacity of a product:
 *   1. product metafield custom.brievenbus_capaciteit (0 = never fits)
 *   2. rules.by_collection[handle]
 *   3. rules.by_tag[tag]
 *   4. rules.by_vendor_type["Vendor|Type"]  (number, or weight bands)
 *   5. rules.by_type[type]
 *   6. rules.default
 * The group comes from the product metafield custom.brievenbus_groep, else
 * from the first rule (collection/tag/vendor-type/type) that carries a group.
 */

export type Band = [maxGrams: number, capacity: number];
export type Rule =
  | number
  | { cap?: number; groep?: string; weight_bands?: Band[]; else?: number };

export type Rules = {
  letterbox_max_grams?: number;
  item_max_grams?: number;
  default?: number;
  by_type?: Record<string, Rule>;
  by_vendor_type?: Record<string, Rule>;
  by_collection?: Record<string, Rule>;
  by_tag?: Record<string, Rule>;
};

export type ProductInfo = {
  productType: string;
  vendor: string;
  tags: string[];
  collections: string[]; // handles
  capacityOverride: number | null; // custom.brievenbus_capaciteit
  groupOverride: string | null; // custom.brievenbus_groep
};

export type Line = { quantity: number; grams: number; product: ProductInfo | null };

export type Resolved = { capacity: number; group: string | null; source: string };

const FALLBACK = { letterbox_max_grams: 2000, item_max_grams: 250, default: 2 };

function applyRule(rule: Rule | undefined, grams: number): { cap: number; group: string | null } | null {
  if (rule == null) return null;
  if (typeof rule === "number") return { cap: rule, group: null };
  if (rule.weight_bands) {
    for (const [maxGrams, cap] of rule.weight_bands) {
      if (grams <= maxGrams) return { cap, group: rule.groep ?? null };
    }
    return { cap: rule.else ?? 0, group: rule.groep ?? null };
  }
  if (typeof rule.cap === "number") return { cap: rule.cap, group: rule.groep ?? null };
  return null;
}

export function resolveCapacity(p: ProductInfo | null, grams: number, rules: Rules): Resolved {
  // Unknown product (lookup failed): be safe, treat as parcel-only.
  if (!p) return { capacity: 0, group: null, source: "unknown" };

  let group: string | null = p.groupOverride?.trim() || null;
  const pick = (r: { cap: number; group: string | null } | null, source: string): Resolved | null => {
    if (!r) return null;
    if (group == null && r.group) group = r.group;
    return { capacity: Math.max(0, Math.floor(r.cap)), group, source };
  };

  if (p.capacityOverride != null && Number.isFinite(p.capacityOverride)) {
    // Group may still come from a rule when the product only overrides the number.
    if (group == null) {
      for (const h of p.collections) {
        const r = applyRule(rules.by_collection?.[h], grams);
        if (r?.group) { group = r.group; break; }
      }
    }
    return { capacity: Math.max(0, Math.floor(p.capacityOverride)), group, source: "product" };
  }
  for (const h of p.collections) {
    const r = pick(applyRule(rules.by_collection?.[h], grams), `collection:${h}`);
    if (r) return r;
  }
  for (const t of p.tags) {
    const r = pick(applyRule(rules.by_tag?.[t], grams), `tag:${t}`);
    if (r) return r;
  }
  const vt = pick(applyRule(rules.by_vendor_type?.[`${p.vendor}|${p.productType}`], grams), "vendor_type");
  if (vt) return vt;
  const t = pick(applyRule(rules.by_type?.[p.productType], grams), "type");
  if (t) return t;
  return { capacity: rules.default ?? FALLBACK.default, group, source: "default" };
}

export type FitResult = {
  fits: boolean;
  used: number;
  totalGrams: number;
  reasons: string[];
};

export function cartFitsLetterbox(lines: Line[], rules: Rules): FitResult {
  const letterboxMax = rules.letterbox_max_grams ?? FALLBACK.letterbox_max_grams;
  const itemMax = rules.item_max_grams ?? FALLBACK.item_max_grams;
  const reasons: string[] = [];
  let used = 0;
  let totalGrams = 0;
  const groups = new Set<string>();
  let ungrouped = 0;

  for (const line of lines) {
    if (line.quantity <= 0) continue;
    totalGrams += line.grams * line.quantity;
    const r = resolveCapacity(line.product, line.grams, rules);
    if (r.capacity === 0) reasons.push(`parcel-only (${r.source})`);
    else if (line.grams > itemMax) reasons.push(`item ${line.grams} g > ${itemMax} g`);
    else used += line.quantity / r.capacity;
    if (r.group) groups.add(r.group);
    else ungrouped += line.quantity;
  }
  if (used > 1) reasons.push(`capacity ${used.toFixed(2)} > 1`);
  if (totalGrams > letterboxMax) reasons.push(`total ${totalGrams} g > ${letterboxMax} g`);
  if (groups.size > 1) reasons.push(`mixed groups ${[...groups].join(",")}`);
  if (groups.size === 1 && ungrouped > 0) reasons.push(`group ${[...groups][0]} mixed with other products`);
  return { fits: reasons.length === 0 && lines.some((l) => l.quantity > 0), used, totalGrams, reasons };
}

/** Rates in EUR. Every list is ordered; the first band whose max_kg >= weight wins. */
export type RateBand = { max_kg: number; price: number; name?: string };
export type ZoneRates = { countries: string[]; letterbox?: number; parcel: RateBand[] };
export type RatesConfig = { currency: string; zones: ZoneRates[] };

export type RateOut = { service_name: string; service_code: string; total_price: string; currency: string; description?: string };

export function ratesFor(countryCode: string, totalGrams: number, fits: boolean, cfg: RatesConfig): RateOut[] {
  const zone = cfg.zones.find((z) => z.countries.includes(countryCode));
  if (!zone) return [];
  const out: RateOut[] = [];
  const cents = (eur: number) => String(Math.round(eur * 100));
  if (fits && typeof zone.letterbox === "number") {
    out.push({ service_name: "Brievenbuspakket", service_code: "BRIEVENBUS", total_price: cents(zone.letterbox), currency: cfg.currency, description: "Past door de brievenbus" });
    return out; // letterbox is the only option when it fits
  }
  const kg = totalGrams / 1000;
  const band = zone.parcel.find((b) => kg <= b.max_kg) ?? zone.parcel[zone.parcel.length - 1];
  if (band) out.push({ service_name: band.name ?? "Pakket", service_code: `PAKKET_${band.max_kg}`, total_price: cents(band.price), currency: cfg.currency });
  return out;
}

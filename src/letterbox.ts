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
 *   0. product tag rules.never_tag ("geen-brievenbus") -> 0, always
 *   1. packed dimensions + weight of the variant (Shopify: product > Shipping),
 *      when length, width and height are all filled in: how many pieces fit in
 *      the box (rules.letterbox_box_cm), capped by the weight limit
 *   2. product metafield custom.brievenbus_capaciteit (0 = never fits), set by hand
 *   3. the rules, first match in this order:
 *        rules.by_collection[handle], rules.by_tag[tag],
 *        rules.by_title[text] (title contains the text, any case; the longest text wins),
 *        rules.by_vendor_type["Vendor|Type"], rules.by_type[type]
 *      A rule is either a MEASUREMENT for every product of that kind,
 *      { "cm": [l, w, h], "gram": g }  -> capacity as in step 1 (gram is used
 *      when the variant has no weight of its own), or a CAPACITY: a number,
 *      { "cap": n }, or weight bands.
 *   4. nothing measured:
 *      rules.unmeasured_parcel_only (default true) -> 0, a parcel. Capacity
 *      numbers > 0 from rules are then guesses and are skipped; a rule of 0
 *      still means "never", and weight bands still count for a product that
 *      HAS a weight (the weight is the measurement). With false, capacity rules
 *      count and rules.default is the last resort (the behaviour before measurements).
 * The group comes from the product metafield custom.brievenbus_groep, else
 * from the first rule (collection/tag/vendor-type/type) that carries a group.
 *
 * `item_max_grams` is a stand-in for thickness ("a heavy thing is usually a
 * thick thing"), so it only applies to pieces WITHOUT measurements. Measured
 * pieces are judged on their real size and the total weight limit.
 */

export type Band = [maxGrams: number, capacity: number];
export type Rule =
  | number
  | { cap?: number; groep?: string; weight_bands?: Band[]; else?: number; cm?: number[]; gram?: number };

export type Rules = {
  letterbox_max_grams?: number;
  item_max_grams?: number;
  /** Inner size of the brievenbuspakket in cm, any order. Default A5 at the PostNL thickness limit. */
  letterbox_box_cm?: number[];
  /** Product tag that forces a parcel, even when the dimensions fit. */
  never_tag?: string;
  /** Products without a measurement (own or per kind) go as a parcel. Default true. */
  unmeasured_parcel_only?: boolean;
  default?: number;
  by_type?: Record<string, Rule>;
  by_vendor_type?: Record<string, Rule>;
  by_collection?: Record<string, Rule>;
  by_tag?: Record<string, Rule>;
  /** Packaging groups by title text, e.g. "Reaper MSP Core Colors": every pot of that line. */
  by_title?: Record<string, Rule>;
};

/** Packed (ready-to-ship) size of ONE piece, in centimetres. */
export type Dims = { length: number; width: number; height: number };

export type ProductInfo = {
  title?: string;
  productType: string;
  vendor: string;
  tags: string[];
  collections: string[]; // handles
  capacityOverride: number | null; // custom.brievenbus_capaciteit
  groupOverride: string | null; // custom.brievenbus_groep
};

export type Line = { quantity: number; grams: number; product: ProductInfo | null; dims?: Dims | null };

/** `grams` is set when the weight came from a rule because the variant has none. */
export type Resolved = { capacity: number; group: string | null; source: string; grams?: number };

const FALLBACK = {
  letterbox_max_grams: 2000,
  item_max_grams: 250,
  default: 2,
  letterbox_box_cm: [21, 14.8, 3.2], // A5 sheet, 3.2 cm = PostNL brievenbus thickness
  never_tag: "geen-brievenbus",
  unmeasured_parcel_only: true,
};

/** True when length, width and height are all known (Shopify returns 0 for unset dimensions). */
export function hasDims(d: Dims | null | undefined): d is Dims {
  return !!d && [d.length, d.width, d.height].every((x) => Number.isFinite(x) && x > 0);
}

const ORIENTATIONS = [[0, 1, 2], [0, 2, 1], [1, 0, 2], [1, 2, 0], [2, 0, 1], [2, 1, 0]];

/**
 * How many identical pieces fit in the box. Tries the 6 ways to lay a piece and
 * stacks them in a straight grid, so the answer never exceeds what really fits
 * (a mixed arrangement could sometimes squeeze in one more; we don't count on it).
 */
export function piecesInBox(item: Dims, box: number[]): number {
  if (!hasDims(item) || box.length !== 3) return 0;
  const d = [item.length, item.width, item.height];
  const along = (room: number, size: number) => Math.floor(room / size + 1e-9);
  let best = 0;
  for (const [a, b, c] of ORIENTATIONS) {
    best = Math.max(best, along(box[0], d[a]) * along(box[1], d[b]) * along(box[2], d[c]));
  }
  return best;
}

/** Capacity from the real size and weight: pieces that fit by size, capped by the weight limit. */
export function capacityFromDims(dims: Dims, grams: number, rules: Rules) {
  const configured = rules.letterbox_box_cm;
  const valid = Array.isArray(configured) && configured.length === 3 && configured.every((x) => typeof x === "number" && x > 0);
  const box = valid ? configured : FALLBACK.letterbox_box_cm; // a typo in the shop field must not turn everything into parcels
  const maxGrams = rules.letterbox_max_grams ?? FALLBACK.letterbox_max_grams;
  const bySize = piecesInBox(dims, box);
  const byWeight = grams > 0 ? Math.floor(maxGrams / grams) : null;
  return { capacity: byWeight == null ? bySize : Math.min(bySize, byWeight), bySize, byWeight };
}

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

/** A measurement rule { cm: [l, w, h], gram? } for every product of a kind; null for capacity rules. */
export function ruleMeasurement(rule: Rule | undefined): { dims: Dims; gram: number | null } | null {
  if (rule == null || typeof rule !== "object" || !Array.isArray(rule.cm) || rule.cm.length !== 3) return null;
  const [length, width, height] = rule.cm.map(Number);
  const dims = { length, width, height };
  if (!hasDims(dims)) return null;
  return { dims, gram: typeof rule.gram === "number" && rule.gram > 0 ? rule.gram : null };
}

/** The by_title key whose text the title contains (any case); the longest, most specific one wins. */
export function titleMatch(title: string | undefined, byTitle: Rules["by_title"]): string | null {
  const t = (title ?? "").toLowerCase();
  if (!t || !byTitle) return null;
  const hits = Object.keys(byTitle).filter((k) => k.trim() && t.includes(k.trim().toLowerCase()));
  return hits.sort((a, b) => b.trim().length - a.trim().length)[0] ?? null;
}

/** The rule lookups in resolution order: collection, tag, title, vendor|type, type. */
function ruleCandidates(p: ProductInfo, rules: Rules): Array<[Rule | undefined, string]> {
  const title = titleMatch(p.title, rules.by_title);
  return [
    ...p.collections.map((h): [Rule | undefined, string] => [rules.by_collection?.[h], `collection:${h}`]),
    ...p.tags.map((t): [Rule | undefined, string] => [rules.by_tag?.[t], `tag:${t}`]),
    ...(title ? [[rules.by_title?.[title], `title:${title}`] as [Rule | undefined, string]] : []),
    [rules.by_vendor_type?.[`${p.vendor}|${p.productType}`], "vendor_type"],
    [rules.by_type?.[p.productType], "type"],
  ];
}

export function resolveCapacity(p: ProductInfo | null, grams: number, rules: Rules, dims?: Dims | null): Resolved {
  // Unknown product (lookup failed): be safe, treat as parcel-only.
  if (!p) return { capacity: 0, group: null, source: "unknown" };

  let group: string | null = p.groupOverride?.trim() || null;
  const pick = (r: { cap: number; group: string | null }, source: string): Resolved => {
    if (group == null && r.group) group = r.group;
    return { capacity: Math.max(0, Math.floor(r.cap)), group, source };
  };
  // Capacity decided elsewhere (tag, dimensions, product field): the group may still come from a rule.
  const withRuleGroup = (capacity: number, source: string): Resolved => {
    if (group == null) {
      const hit = ruleCandidates(p, rules).find(([r]) => r != null && typeof r === "object" && r.groep);
      group = (hit?.[0] as { groep?: string } | undefined)?.groep ?? null;
    }
    return { capacity: Math.max(0, Math.floor(capacity)), group, source };
  };

  const neverTag = rules.never_tag ?? FALLBACK.never_tag;
  if (neverTag && p.tags.includes(neverTag)) return withRuleGroup(0, `tag:${neverTag}`);
  if (hasDims(dims)) return withRuleGroup(capacityFromDims(dims, grams, rules).capacity, "afmetingen");
  if (p.capacityOverride != null && Number.isFinite(p.capacityOverride)) return withRuleGroup(p.capacityOverride, "product");

  const strict = rules.unmeasured_parcel_only ?? FALLBACK.unmeasured_parcel_only;
  for (const [rule, source] of ruleCandidates(p, rules)) {
    const m = ruleMeasurement(rule);
    if (m) {
      const g = grams > 0 ? grams : m.gram ?? 0;
      const res = withRuleGroup(capacityFromDims(m.dims, g, rules).capacity, `afmetingen:${source}`);
      return g !== grams ? { ...res, grams: g } : res;
    }
    const r = applyRule(rule, grams);
    if (!r) continue;
    // Strict: a capacity number from a rule is a guess, not a measurement. Keep looking for a
    // measurement; an explicit 0 ("never") still decides, and so do weight bands for a product
    // that has a weight.
    const byWeight = typeof rule === "object" && rule != null && Array.isArray(rule.weight_bands) && grams > 0;
    if (!strict || r.cap <= 0 || byWeight) return pick(r, source);
    if (group == null && r.group) group = r.group;
  }
  return strict ? withRuleGroup(0, "onbekend") : { capacity: rules.default ?? FALLBACK.default, group, source: "default" };
}

export type FitResult = {
  fits: boolean;
  used: number;
  totalGrams: number;
  reasons: string[];
  /** Per line "quantity x cap (source)", for the log. */
  lines: string[];
};

export function cartFitsLetterbox(lines: Line[], rules: Rules): FitResult {
  const letterboxMax = rules.letterbox_max_grams ?? FALLBACK.letterbox_max_grams;
  const itemMax = rules.item_max_grams ?? FALLBACK.item_max_grams;
  const reasons: string[] = [];
  const details: string[] = [];
  let used = 0;
  let totalGrams = 0;
  const groups = new Set<string>();
  let ungrouped = 0;

  for (const line of lines) {
    if (line.quantity <= 0) continue;
    const r = resolveCapacity(line.product, line.grams, rules, line.dims);
    const grams = r.grams ?? line.grams; // a variant without weight takes its kind's weight
    totalGrams += grams * line.quantity;
    details.push(`${line.quantity}x cap ${r.capacity} (${r.source})`);
    if (r.capacity === 0) reasons.push(`parcel-only (${r.source})`);
    else if (!r.source.startsWith("afmetingen") && grams > itemMax) reasons.push(`item ${grams} g > ${itemMax} g`);
    else used += line.quantity / r.capacity;
    if (r.group) groups.add(r.group);
    else ungrouped += line.quantity;
  }
  if (used > 1) reasons.push(`capacity ${used.toFixed(2)} > 1`);
  if (totalGrams > letterboxMax) reasons.push(`total ${totalGrams} g > ${letterboxMax} g`);
  if (groups.size > 1) reasons.push(`mixed groups ${[...groups].join(",")}`);
  if (groups.size === 1 && ungrouped > 0) reasons.push(`group ${[...groups][0]} mixed with other products`);
  return { fits: reasons.length === 0 && lines.some((l) => l.quantity > 0), used, totalGrams, reasons, lines: details };
}

/** Rates in EUR. Every list is ordered; the first band whose max_kg >= weight wins. */
export type RateBand = { max_kg: number; price: number; name?: string };
export type ZoneRates = { countries: string[]; letterbox?: number; parcel: RateBand[] };
export type RatesConfig = { currency: string; zones: ZoneRates[] };

export type RateOut = { service_name: string; service_code: string; total_price: string; currency: string; description?: string };

export function ratesFor(countryCode: string, totalGrams: number, fits: boolean, cfg: RatesConfig): RateOut[] {
  const zone = cfg.zones.find((z) => z.countries.includes(countryCode));
  if (!zone) return [];
  // service_code equals the visible name: the PostNL app may match orders on the shipping line code.
  const out: RateOut[] = [];
  const cents = (eur: number) => String(Math.round(eur * 100));
  if (fits && typeof zone.letterbox === "number") {
    out.push({ service_name: "Brievenbuspakket", service_code: "Brievenbuspakket", total_price: cents(zone.letterbox), currency: cfg.currency, description: "Past door de brievenbus" });
    return out; // letterbox is the only option when it fits
  }
  const kg = totalGrams / 1000;
  const band = zone.parcel.find((b) => kg <= b.max_kg) ?? zone.parcel[zone.parcel.length - 1];
  if (band) out.push({ service_name: band.name ?? "Pakket", service_code: band.name ?? `PAKKET_${band.max_kg}`, total_price: cents(band.price), currency: cfg.currency });
  return out;
}

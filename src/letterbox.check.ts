/* Run with: npx tsx src/letterbox.check.ts  (part of npm run check) */
import assert from "node:assert/strict";
import { capacityFromDims, cartFitsLetterbox, piecesInBox, ratesFor, resolveCapacity, titleMatch, type Dims, type ProductInfo, type RatesConfig, type Rules } from "./letterbox";

// The capacity-rule tests below describe the behaviour with unmeasured_parcel_only: false;
// the strict default (unmeasured products are parcels) is tested further down.
const rules: Rules = {
  unmeasured_parcel_only: false,
  letterbox_max_grams: 2000,
  item_max_grams: 250,
  default: 2,
  by_type: { Paint: 10, Miniature: 5, Terrain: 0, Brush: 8 },
  by_vendor_type: { "Reaper Miniatures|Miniature": { weight_bands: [[30, 5], [85, 2]], else: 0 } },
  by_collection: { draken: 0, matten: { cap: 5, groep: "matten" } },
  by_tag: { groot: 0 },
};
const P = (o: Partial<ProductInfo>): ProductInfo => ({ productType: "", vendor: "", tags: [], collections: [], capacityOverride: null, groupOverride: null, ...o });
const paint = P({ productType: "Paint", vendor: "Reaper Master Series Paints" });
const mini = P({ productType: "Miniature", vendor: "Reaper Miniatures" });
const dragon = P({ productType: "Miniature", vendor: "Reaper Miniatures", collections: ["draken"] });
const smallDragon = P({ productType: "Miniature", vendor: "Reaper Miniatures", collections: ["draken"], capacityOverride: 5 });
const mat = P({ productType: "Material", vendor: "Scenery en Zo", collections: ["matten"] });
const terrain = P({ productType: "Terrain", vendor: "Green Stuff World" });

// resolution order
assert.equal(resolveCapacity(dragon, 20, rules).capacity, 0, "collection rule beats vendor/type");
assert.equal(resolveCapacity(smallDragon, 20, rules).capacity, 5, "product override beats collection");
assert.equal(resolveCapacity(P({ tags: ["groot"], productType: "Paint" }), 20, rules).capacity, 0, "tag beats type");
assert.equal(resolveCapacity(mini, 20, rules).capacity, 5, "weight band 1");
assert.equal(resolveCapacity(mini, 60, rules).capacity, 2, "weight band 2");
assert.equal(resolveCapacity(mini, 120, rules).capacity, 0, "weight band else");
assert.equal(resolveCapacity(mat, 100, rules).group, "matten", "group from collection rule");
assert.equal(resolveCapacity(null, 10, rules).capacity, 0, "unknown product is parcel-only");

// fits
const fit = (lines: Array<[number, number, ProductInfo | null]>) => cartFitsLetterbox(lines.map(([quantity, grams, product]) => ({ quantity, grams, product })), rules);
assert.equal(fit([[5, 27, paint], [2, 16, mini]]).fits, true, "0.5 + 0.4 fits");
assert.equal(fit([[5, 27, paint], [3, 16, mini]]).fits, false, "0.5 + 0.6 overflows");
assert.equal(fit([[1, 20, terrain]]).fits, false, "terrain never fits");
assert.equal(fit([[1, 20, smallDragon]]).fits, true, "override 5 fits");
assert.equal(fit([[5, 100, mat]]).fits, true, "five mats fit together");
assert.equal(fit([[1, 100, mat], [1, 16, mini]]).fits, false, "mat may not mix with a mini");
assert.equal(fit([[20, 110, P({ capacityOverride: 100 })]]).fits, false, "2.2 kg total is too heavy");
assert.equal(fit([[1, 300, P({ capacityOverride: 2 })]]).fits, false, "single item over 250 g");
assert.equal(fit([]).fits, false, "empty cart never letterbox");

// dimensions (default box A5 21 x 14.8 x 3.2 cm)
const A5: number[] = [21, 14.8, 3.2];
const D = (length: number, width: number, height: number): Dims => ({ length, width, height });
const flat = D(10, 7, 1.5);
assert.equal(piecesInBox(flat, A5), 8, "2 x 2 x 2 in the best orientation");
assert.equal(piecesInBox(D(1.5, 10, 7), A5), 8, "order of the sizes does not matter");
assert.equal(piecesInBox(D(10.5, 7.4, 1.6), A5), 8, "exact fits survive floating point (14.8 / 7.4)");
assert.equal(piecesInBox(D(21, 14.8, 3.2), A5), 1, "an A5-sized piece fills the box");
assert.equal(piecesInBox(D(5, 5, 4), A5), 0, "thicker than 3.2 cm every way round");
assert.equal(piecesInBox(D(25, 2, 2), A5), 0, "longer than the box");
assert.equal(piecesInBox(D(10, 7, 0), A5), 0, "incomplete dimensions never fit by size");
assert.equal(piecesInBox(flat, [30, 20, 3]), 16, "box size is configurable (7 along 30, 10 along 20)");
assert.deepEqual(capacityFromDims(flat, 300, rules), { capacity: 6, bySize: 8, byWeight: 6 }, "weight caps the count: 2000 / 300");
assert.deepEqual(capacityFromDims(flat, 0, rules), { capacity: 8, bySize: 8, byWeight: null }, "no weight, size decides");

const parcelOnly = P({ productType: "Terrain", capacityOverride: 0 });
assert.deepEqual(resolveCapacity(parcelOnly, 50, rules, flat), { capacity: 8, group: null, source: "afmetingen" }, "dimensions beat the product field");
assert.equal(resolveCapacity(P({ tags: ["geen-brievenbus"] }), 50, rules, flat).capacity, 0, "never-tag beats dimensions");
assert.equal(resolveCapacity(P({ tags: ["nooit"] }), 50, { ...rules, never_tag: "nooit" }, flat).capacity, 0, "never-tag is configurable");
assert.equal(resolveCapacity(mat, 100, rules, flat).group, "matten", "group still comes from the rules");
assert.equal(resolveCapacity(P({ capacityOverride: 2, tags: ["groot"] }), 50, { ...rules, by_tag: { groot: { cap: 0, groep: "groot" } } }).group, "groot", "product field keeps a group from any rule");
assert.equal(resolveCapacity(parcelOnly, 50, rules, D(10, 7, 0)).source, "product", "incomplete dimensions fall back to the rules");
assert.equal(resolveCapacity(null, 50, rules, flat).capacity, 0, "unknown product stays parcel-only");

const fitD = (lines: Array<[number, number, ProductInfo, Dims | null]>) => cartFitsLetterbox(lines.map(([quantity, grams, product, dims]) => ({ quantity, grams, product, dims })), rules);
assert.equal(fitD([[8, 50, parcelOnly, flat]]).fits, true, "eight flat pieces fit");
assert.equal(fitD([[9, 50, parcelOnly, flat]]).fits, false, "nine do not");
assert.equal(fitD([[1, 300, parcelOnly, flat]]).fits, true, "a 300 g piece with dimensions skips the 250 g stand-in");
assert.equal(fitD([[1, 300, P({ capacityOverride: 2 }), null]]).fits, false, "without dimensions the 250 g limit still applies");
assert.equal(fitD([[4, 50, parcelOnly, flat], [5, 27, paint, null]]).fits, true, "4/8 + 5/10 mixes with rule-based lines");
assert.equal(fitD([[1, 50, parcelOnly, D(5, 5, 4)]]).fits, false, "too thick");
assert.equal(fitD([[7, 300, parcelOnly, flat]]).fits, false, "2.1 kg total is too heavy");
assert.deepEqual(fitD([[2, 50, parcelOnly, flat]]).lines, ["2x cap 8 (afmetingen)"], "log line per cart line");

// strict default: only measured products (own dimensions, a measurement per kind, or the product field) fit
const pot = [2.6, 2.6, 7.6]; // lying down: 2 along 21, 5 along 14.8, 1 along 3.2 -> 10
const strict: Rules = {
  by_type: { Paint: 10, Miniature: 5, Terrain: 0 },
  by_vendor_type: {
    "Reaper Master Series Paints|Paint": { cm: pot, gram: 28 },
    "Reaper Miniatures|Miniature": { weight_bands: [[30, 5], [85, 2]], else: 0 },
  },
  by_collection: { verfsets: { cm: [20, 14, 3], gram: 250 }, matten: { cap: 5, groep: "matten" } },
  by_tag: { "maat-plat": { cm: [10, 7, 1.5] }, groot: 0 },
};
const R = (p: ProductInfo, grams: number, d: Dims | null = null, r: Rules = strict) => resolveCapacity(p, grams, r, d);
const msp = P({ productType: "Paint", vendor: "Reaper Master Series Paints" });
const otherPaint = P({ productType: "Paint", vendor: "Vallejo" });
assert.deepEqual(R(msp, 28), { capacity: 10, group: null, source: "afmetingen:vendor_type" }, "one measurement covers every MSP pot");
assert.deepEqual(R(msp, 0), { capacity: 10, group: null, source: "afmetingen:vendor_type", grams: 28 }, "the kind's weight fills a missing variant weight");
assert.equal(R(otherPaint, 20).source, "onbekend", "type number 10 is a guess: parcel");
assert.equal(R(otherPaint, 20).capacity, 0);
assert.deepEqual(R(mini, 20), { capacity: 5, group: null, source: "vendor_type" }, "weight bands count for a mini that has a weight");
assert.equal(R(mini, 0).source, "onbekend", "...but not for a mini without weight");
assert.deepEqual(R(mini, 120), { capacity: 0, group: null, source: "vendor_type" }, "a rule of 0 still means never");
assert.equal(R(terrain, 20).source, "type", "type rule 0 still decides");
assert.equal(R(P({ productType: "Paint", vendor: "Reaper Master Series Paints", capacityOverride: 3 }), 28).source, "product", "Peter's number beats the kind");
assert.equal(R(P({ productType: "Paint", vendor: "Reaper Master Series Paints", capacityOverride: 0 }), 28).capacity, 0, "Peter's 0 beats the kind");
assert.equal(R(msp, 28, D(21, 14.8, 3.2)).capacity, 1, "own dimensions beat the kind");
assert.equal(R(P({ productType: "Paint", vendor: "Reaper Master Series Paints", collections: ["verfsets"] }), 0).source, "afmetingen:collection:verfsets", "collection measurement comes first");
assert.equal(R(P({ productType: "Paint", vendor: "Reaper Master Series Paints", collections: ["verfsets"] }), 0).capacity, 1, "set 20x14x3 cm: 1, and 250 g caps at 8");
assert.deepEqual(R(P({ productType: "Miniature", vendor: "Reaper Miniatures", tags: ["maat-plat"] }), 20), { capacity: 8, group: null, source: "afmetingen:tag:maat-plat" }, "size class by tag, no gram: variant weight");
assert.equal(R(P({ productType: "Material", collections: ["matten"] }), 100).group, "matten", "group survives a skipped capacity rule");
assert.equal(R(P({ productType: "Material", collections: ["matten"] }), 100).capacity, 0, "...but the mat itself is unmeasured");
assert.equal(R(msp, 28, null, { ...strict, by_vendor_type: { "Reaper Master Series Paints|Paint": { cm: [2.6, 0, 7.6] } } }).source, "onbekend", "an incomplete measurement is no measurement");
assert.equal(R(otherPaint, 20, null, { by_type: { Paint: 10 } }).source, "onbekend", "strict is the default");
assert.equal(R(otherPaint, 20, null, { ...strict, unmeasured_parcel_only: false }).source, "type", "the switch brings the type rules back");
assert.equal(R(msp, 28, null, { ...strict, unmeasured_parcel_only: false }).source, "afmetingen:vendor_type", "measurements count in both modes");

// packaging groups by title text: the longest matching text wins, any case
const byTitle: Rules = { ...strict, by_title: { "Reaper MSP Core Colors": { cm: pot, gram: 28 }, "Reaper MSP": { cm: [21, 14.8, 3.2] }, "Arte Deco 60ml": 0 } };
const T = (title: string, extra: Partial<ProductInfo> = {}) => P({ title, productType: "Paint", vendor: "Reaper Master Series Paints", ...extra });
assert.equal(titleMatch("Auburn Shadow 09241 Reaper MSP Core Colors", byTitle.by_title), "Reaper MSP Core Colors", "longest text wins");
assert.equal(titleMatch("mermaid scale 09497 REAPER MSP", byTitle.by_title), "Reaper MSP", "any case");
assert.equal(titleMatch("Learn To Paint Kit 08906", byTitle.by_title), null, "no match");
assert.deepEqual(R(T("Auburn Shadow 09241 Reaper MSP Core Colors"), 28, null, byTitle), { capacity: 10, group: null, source: "afmetingen:title:Reaper MSP Core Colors" }, "title group measured once");
assert.equal(R(T("Mermaid Scale 09497 Reaper MSP"), 3, null, byTitle).capacity, 1, "the shorter group for other MSP titles");
assert.equal(R(T("Auburn Shadow 09241 Reaper MSP Core Colors", { tags: ["maat-plat"] }), 28, null, byTitle).source, "afmetingen:tag:maat-plat", "a tag comes before the title");
assert.equal(R(T("Learn To Paint Kit 08906"), 726, null, byTitle).source, "afmetingen:vendor_type", "no title group: the kind's measurement");
assert.deepEqual(R(T("Red 70.001 Arte Deco 60ml", { vendor: "Vallejo" }), 110, null, byTitle), { capacity: 0, group: null, source: "title:Arte Deco 60ml" }, "a title rule of 0 means never");

const fitS = (lines: Array<[number, number, ProductInfo]>) => cartFitsLetterbox(lines.map(([quantity, grams, product]) => ({ quantity, grams, product })), strict);
assert.equal(fitS([[10, 28, msp]]).fits, true, "ten MSP pots fill one letterbox");
assert.equal(fitS([[11, 28, msp]]).fits, false, "eleven do not");
assert.equal(fitS([[3, 28, msp], [1, 20, otherPaint]]).fits, false, "one unmeasured product makes it a parcel");
assert.equal(fitS([[10, 0, msp]]).totalGrams, 280, "the kind's weight counts toward the 2 kg limit");

// rates
const cfg: RatesConfig = { currency: "EUR", zones: [
  { countries: ["NL"], letterbox: 4.95, parcel: [{ max_kg: 10, price: 7.75 }, { max_kg: 23, price: 12.5, name: "Pakket zwaar" }] },
  { countries: ["BE"], parcel: [{ max_kg: 10, price: 9.95 }] },
  { countries: ["AT", "FR"], parcel: [{ max_kg: 2, price: 12.95 }, { max_kg: 5, price: 17.5 }] },
] };
assert.deepEqual(ratesFor("NL", 500, true, cfg).map((r) => [r.service_code, r.total_price]), [["Brievenbuspakket", "495"]]);
assert.deepEqual(ratesFor("NL", 500, false, cfg).map((r) => [r.service_code, r.total_price]), [["PAKKET_10", "775"]], "unnamed band keeps the PAKKET_<kg> code");
assert.deepEqual(ratesFor("NL", 12000, false, cfg).map((r) => r.total_price), ["1250"]);
assert.deepEqual(ratesFor("BE", 500, true, cfg).map((r) => r.service_code), ["PAKKET_10"], "no letterbox outside NL even if it fits");
assert.deepEqual(ratesFor("FR", 2500, false, cfg).map((r) => r.total_price), ["1750"]);
assert.deepEqual(ratesFor("US", 500, false, cfg), [], "no zone, no rates");

console.log("letterbox checks: all passed");

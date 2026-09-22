/* Run with: npx tsx app/services/shipping/letterbox.check.ts */
import assert from "node:assert/strict";
import { cartFitsLetterbox, ratesFor, resolveCapacity, type ProductInfo, type RatesConfig, type Rules } from "./letterbox";

const rules: Rules = {
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

// rates
const cfg: RatesConfig = { currency: "EUR", zones: [
  { countries: ["NL"], letterbox: 4.95, parcel: [{ max_kg: 10, price: 7.75 }, { max_kg: 23, price: 12.5, name: "Pakket zwaar" }] },
  { countries: ["BE"], parcel: [{ max_kg: 10, price: 9.95 }] },
  { countries: ["AT", "FR"], parcel: [{ max_kg: 2, price: 12.95 }, { max_kg: 5, price: 17.5 }] },
] };
assert.deepEqual(ratesFor("NL", 500, true, cfg).map((r) => [r.service_code, r.total_price]), [["BRIEVENBUS", "495"]]);
assert.deepEqual(ratesFor("NL", 500, false, cfg).map((r) => [r.service_code, r.total_price]), [["PAKKET_10", "775"]]);
assert.deepEqual(ratesFor("NL", 12000, false, cfg).map((r) => r.total_price), ["1250"]);
assert.deepEqual(ratesFor("BE", 500, true, cfg).map((r) => r.service_code), ["PAKKET_10"], "no letterbox outside NL even if it fits");
assert.deepEqual(ratesFor("FR", 2500, false, cfg).map((r) => r.total_price), ["1750"]);
assert.deepEqual(ratesFor("US", 500, false, cfg), [], "no zone, no rates");

console.log("letterbox checks: all passed");

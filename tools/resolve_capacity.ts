/**
 * The Worker's own capacity logic (src/letterbox.ts) for the Python tools, so a report never
 * computes differently from checkout. Reads JSON on stdin:
 *   { "rules": {...}, "items": [{ "product": ProductInfo, "grams": n, "dims": {length, width, height} | null }] }
 * and prints one { capacity, group, source, grams? } per item, in the same order.
 *
 *   npx tsx tools/resolve_capacity.ts < input.json
 */
import { resolveCapacity, type Dims, type ProductInfo, type Rules } from "../src/letterbox";

let raw = "";
for await (const chunk of process.stdin) raw += chunk;
const input = JSON.parse(raw) as { rules: Rules; items: Array<{ product: ProductInfo; grams: number; dims: Dims | null }> };
process.stdout.write(JSON.stringify(input.items.map((it) => resolveCapacity(it.product, it.grams, input.rules, it.dims))));

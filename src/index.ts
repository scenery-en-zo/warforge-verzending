import { cartFitsLetterbox, ratesFor, type Line } from "./letterbox";
import { clearCaches, loadProducts, loadRules, type Env } from "./catalog";

/**
 * Scenery en Zo verzendregels: Shopify CarrierService callback on Cloudflare Workers.
 *
 *   POST /rates          Shopify sends the cart + destination, we answer with rates.
 *   GET  /rates?reset=…  empties the caches after a rule change (prefix of the client secret).
 *   GET  /health         liveness.
 *
 * NL and the cart fits ONE A5 brievenbuspakket -> only "Brievenbuspakket".
 * Otherwise the weight-band parcel rate of the destination zone. Free shipping
 * above the threshold is Shopify's automatic discount, not ours.
 */

type CarrierItem = { name?: string; sku?: string; quantity: number; grams: number; product_id?: number | string; requires_shipping?: boolean };
type CarrierRequest = { rate?: { destination?: { country?: string }; items?: CarrierItem[]; currency?: string } };

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

async function verifyHmac(raw: string, header: string | null, secret: string): Promise<boolean> {
  if (!header || !secret) return false;
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(raw)));
  const digest = btoa(String.fromCharCode(...sig));
  if (digest.length !== header.length) return false;
  let diff = 0;
  for (let i = 0; i < digest.length; i++) diff |= digest.charCodeAt(i) ^ header.charCodeAt(i);
  return diff === 0;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/health") return json({ ok: true });
    if (url.pathname !== "/rates") return json({ error: "not found" }, 404);

    if (request.method === "GET") {
      const reset = url.searchParams.get("reset");
      if (reset && reset === env.CARRIER_CLIENT_SECRET.slice(0, 12)) {
        clearCaches();
        return json({ ok: true, reset: true });
      }
      return json({ ok: true, hint: "Shopify POSTs carrier rate requests here." });
    }
    if (request.method !== "POST") return json({ error: "method not allowed" }, 405);

    const raw = await request.text();
    if (!(await verifyHmac(raw, request.headers.get("x-shopify-hmac-sha256"), env.CARRIER_CLIENT_SECRET))) {
      return json({ error: "invalid hmac" }, 401);
    }
    const started = Date.now();
    let body: CarrierRequest;
    try {
      body = JSON.parse(raw);
    } catch {
      return json({ rates: [] });
    }
    const country = body.rate?.destination?.country ?? "";
    const items = (body.rate?.items ?? []).filter((i) => i.requires_shipping !== false && i.quantity > 0);

    const { rules, rates } = await loadRules(env);
    if (!rates) {
      console.error("[carrier] no rates config (shop metafield custom.verzendtarieven missing)");
      return json({ rates: [] });
    }
    const ids = items.map((i) => String(i.product_id ?? "")).filter(Boolean);
    const infos = await loadProducts(env, ids);
    const lines: Line[] = items.map((i) => ({
      quantity: i.quantity,
      grams: Number(i.grams) || 0,
      product: infos.get(String(i.product_id ?? "")) ?? null,
    }));

    const fit = cartFitsLetterbox(lines, rules);
    const letterboxAllowed = country === "NL" && fit.fits;
    const out = ratesFor(country, fit.totalGrams, letterboxAllowed, rates);
    console.log(`[carrier] ${country} items=${items.length} grams=${fit.totalGrams} used=${fit.used.toFixed(2)} fits=${fit.fits} -> ${out.map((r) => r.service_code).join(",") || "none"} (${Date.now() - started} ms)${fit.reasons.length ? " reasons: " + fit.reasons.join("; ") : ""}`);
    return json({ rates: out });
  },
} satisfies ExportedHandler<Env>;

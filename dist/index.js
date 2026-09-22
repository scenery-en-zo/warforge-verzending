var __defProp = Object.defineProperty;
var __name = (target, value) => __defProp(target, "name", { value, configurable: true });

// src/letterbox.ts
var FALLBACK = { letterbox_max_grams: 2e3, item_max_grams: 250, default: 2 };
function applyRule(rule, grams) {
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
__name(applyRule, "applyRule");
function resolveCapacity(p, grams, rules) {
  if (!p) return { capacity: 0, group: null, source: "unknown" };
  let group = p.groupOverride?.trim() || null;
  const pick = /* @__PURE__ */ __name((r, source) => {
    if (!r) return null;
    if (group == null && r.group) group = r.group;
    return { capacity: Math.max(0, Math.floor(r.cap)), group, source };
  }, "pick");
  if (p.capacityOverride != null && Number.isFinite(p.capacityOverride)) {
    if (group == null) {
      for (const h of p.collections) {
        const r = applyRule(rules.by_collection?.[h], grams);
        if (r?.group) {
          group = r.group;
          break;
        }
      }
    }
    return { capacity: Math.max(0, Math.floor(p.capacityOverride)), group, source: "product" };
  }
  for (const h of p.collections) {
    const r = pick(applyRule(rules.by_collection?.[h], grams), `collection:${h}`);
    if (r) return r;
  }
  for (const t2 of p.tags) {
    const r = pick(applyRule(rules.by_tag?.[t2], grams), `tag:${t2}`);
    if (r) return r;
  }
  const vt = pick(applyRule(rules.by_vendor_type?.[`${p.vendor}|${p.productType}`], grams), "vendor_type");
  if (vt) return vt;
  const t = pick(applyRule(rules.by_type?.[p.productType], grams), "type");
  if (t) return t;
  return { capacity: rules.default ?? FALLBACK.default, group, source: "default" };
}
__name(resolveCapacity, "resolveCapacity");
function cartFitsLetterbox(lines, rules) {
  const letterboxMax = rules.letterbox_max_grams ?? FALLBACK.letterbox_max_grams;
  const itemMax = rules.item_max_grams ?? FALLBACK.item_max_grams;
  const reasons = [];
  let used = 0;
  let totalGrams = 0;
  const groups = /* @__PURE__ */ new Set();
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
__name(cartFitsLetterbox, "cartFitsLetterbox");
function ratesFor(countryCode, totalGrams, fits, cfg) {
  const zone = cfg.zones.find((z) => z.countries.includes(countryCode));
  if (!zone) return [];
  const out = [];
  const cents = /* @__PURE__ */ __name((eur) => String(Math.round(eur * 100)), "cents");
  if (fits && typeof zone.letterbox === "number") {
    out.push({ service_name: "Brievenbuspakket", service_code: "BRIEVENBUS", total_price: cents(zone.letterbox), currency: cfg.currency, description: "Past door de brievenbus" });
    return out;
  }
  const kg = totalGrams / 1e3;
  const band = zone.parcel.find((b) => kg <= b.max_kg) ?? zone.parcel[zone.parcel.length - 1];
  if (band) out.push({ service_name: band.name ?? "Pakket", service_code: `PAKKET_${band.max_kg}`, total_price: cents(band.price), currency: cfg.currency });
  return out;
}
__name(ratesFor, "ratesFor");

// src/catalog.ts
var PRODUCT_TTL_MS = 10 * 60 * 1e3;
var RULES_TTL_MS = 2 * 60 * 1e3;
var API_VERSION = "2026-01";
var products = /* @__PURE__ */ new Map();
var rulesCache = null;
var token = null;
async function accessToken(env) {
  if (token && Date.now() < token.expiresAt - 6e4) return token.value;
  const res = await fetch(`https://${env.CARRIER_SHOP}/admin/oauth/access_token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ grant_type: "client_credentials", client_id: env.CARRIER_CLIENT_ID, client_secret: env.CARRIER_CLIENT_SECRET })
  });
  if (!res.ok) throw new Error(`token request failed: ${res.status}`);
  const data = await res.json();
  token = { value: data.access_token, expiresAt: Date.now() + (data.expires_in ?? 86400) * 1e3 };
  return token.value;
}
__name(accessToken, "accessToken");
async function graphql(env, query, variables) {
  const res = await fetch(`https://${env.CARRIER_SHOP}/admin/api/${API_VERSION}/graphql.json`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Shopify-Access-Token": await accessToken(env) },
    body: JSON.stringify({ query, variables: variables ?? {} })
  });
  const json2 = await res.json();
  if (!json2.data) throw new Error(`GraphQL error: ${JSON.stringify(json2.errors ?? json2)}`);
  return json2.data;
}
__name(graphql, "graphql");
var PRODUCTS_QUERY = `
  query LetterboxProducts($ids: [ID!]!) {
    nodes(ids: $ids) {
      ... on Product {
        id
        productType
        vendor
        tags
        collections(first: 25) { nodes { handle } }
        capaciteit: metafield(namespace: "custom", key: "brievenbus_capaciteit") { value }
        groep: metafield(namespace: "custom", key: "brievenbus_groep") { value }
      }
    }
  }`;
var RULES_QUERY = `
  query LetterboxRules {
    shop {
      rules: metafield(namespace: "custom", key: "brievenbus_capaciteit_standaard") { value }
      rates: metafield(namespace: "custom", key: "verzendtarieven") { value }
    }
  }`;
function parseJson(raw) {
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}
__name(parseJson, "parseJson");
async function loadRules(env) {
  if (rulesCache && Date.now() - rulesCache.at < RULES_TTL_MS) return rulesCache.value;
  try {
    const data = await graphql(env, RULES_QUERY);
    const value = { rules: parseJson(data.shop.rules?.value) ?? {}, rates: parseJson(data.shop.rates?.value) };
    rulesCache = { value, at: Date.now() };
    return value;
  } catch (err) {
    console.error("[carrier] rules lookup failed", err);
    if (rulesCache) return rulesCache.value;
    return { rules: {}, rates: null };
  }
}
__name(loadRules, "loadRules");
async function loadProducts(env, productIds) {
  const out = /* @__PURE__ */ new Map();
  const missing = [];
  const now = Date.now();
  for (const id of new Set(productIds)) {
    const hit = products.get(id);
    if (hit && now - hit.at < PRODUCT_TTL_MS) out.set(id, hit.value);
    else missing.push(id);
  }
  if (missing.length === 0) return out;
  try {
    const data = await graphql(env, PRODUCTS_QUERY, { ids: missing.map((id) => `gid://shopify/Product/${id}`) });
    for (const node of data.nodes) {
      if (!node?.id) continue;
      const id = node.id.split("/").pop();
      const cap = node.capaciteit?.value != null ? Number(node.capaciteit.value) : null;
      const info = {
        productType: node.productType ?? "",
        vendor: node.vendor ?? "",
        tags: node.tags ?? [],
        collections: node.collections?.nodes.map((c) => c.handle) ?? [],
        capacityOverride: cap != null && Number.isFinite(cap) ? cap : null,
        groupOverride: node.groep?.value ?? null
      };
      products.set(id, { value: info, at: now });
      out.set(id, info);
    }
    for (const id of missing) {
      if (!out.has(id)) {
        products.set(id, { value: null, at: now });
        out.set(id, null);
      }
    }
  } catch (err) {
    console.error("[carrier] product lookup failed", err);
    for (const id of missing) out.set(id, products.get(id)?.value ?? null);
  }
  return out;
}
__name(loadProducts, "loadProducts");
function clearCaches() {
  products.clear();
  rulesCache = null;
}
__name(clearCaches, "clearCaches");

// src/index.ts
var json = /* @__PURE__ */ __name((body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }), "json");
async function verifyHmac(raw, header, secret) {
  if (!header || !secret) return false;
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(raw)));
  const digest = btoa(String.fromCharCode(...sig));
  if (digest.length !== header.length) return false;
  let diff = 0;
  for (let i = 0; i < digest.length; i++) diff |= digest.charCodeAt(i) ^ header.charCodeAt(i);
  return diff === 0;
}
__name(verifyHmac, "verifyHmac");
var index_default = {
  async fetch(request, env) {
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
    if (!await verifyHmac(raw, request.headers.get("x-shopify-hmac-sha256"), env.CARRIER_CLIENT_SECRET)) {
      return json({ error: "invalid hmac" }, 401);
    }
    const started = Date.now();
    let body;
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
    const lines = items.map((i) => ({
      quantity: i.quantity,
      grams: Number(i.grams) || 0,
      product: infos.get(String(i.product_id ?? "")) ?? null
    }));
    const fit = cartFitsLetterbox(lines, rules);
    const letterboxAllowed = country === "NL" && fit.fits;
    const out = ratesFor(country, fit.totalGrams, letterboxAllowed, rates);
    console.log(`[carrier] ${country} items=${items.length} grams=${fit.totalGrams} used=${fit.used.toFixed(2)} fits=${fit.fits} -> ${out.map((r) => r.service_code).join(",") || "none"} (${Date.now() - started} ms)${fit.reasons.length ? " reasons: " + fit.reasons.join("; ") : ""}`);
    return json({ rates: out });
  }
};
export {
  index_default as default
};
//# sourceMappingURL=index.js.map

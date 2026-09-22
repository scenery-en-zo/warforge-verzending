import type { ProductInfo, RatesConfig, Rules } from "./letterbox";

/**
 * Product + rule lookups with an in-memory cache (per Worker isolate). A rate
 * request normally answers without touching the Admin API; only unknown
 * products or expired rules cause a fetch. Talks to Shopify as the
 * "Product Brievenbuspakket" app via client credentials.
 */

export type Env = {
  CARRIER_SHOP: string; // scenery-en-zo.myshopify.com
  CARRIER_CLIENT_ID: string; // secret
  CARRIER_CLIENT_SECRET: string; // secret
};

const PRODUCT_TTL_MS = 10 * 60 * 1000;
const RULES_TTL_MS = 2 * 60 * 1000;
const API_VERSION = "2026-01";

type Cached<T> = { value: T; at: number };
const products = new Map<string, Cached<ProductInfo | null>>();
let rulesCache: Cached<{ rules: Rules; rates: RatesConfig | null }> | null = null;
let token: { value: string; expiresAt: number } | null = null;

async function accessToken(env: Env): Promise<string> {
  if (token && Date.now() < token.expiresAt - 60_000) return token.value;
  const res = await fetch(`https://${env.CARRIER_SHOP}/admin/oauth/access_token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ grant_type: "client_credentials", client_id: env.CARRIER_CLIENT_ID, client_secret: env.CARRIER_CLIENT_SECRET }),
  });
  if (!res.ok) throw new Error(`token request failed: ${res.status}`);
  const data = (await res.json()) as { access_token: string; expires_in?: number };
  token = { value: data.access_token, expiresAt: Date.now() + (data.expires_in ?? 86_400) * 1000 };
  return token.value;
}

async function graphql<T>(env: Env, query: string, variables?: Record<string, unknown>): Promise<T> {
  const res = await fetch(`https://${env.CARRIER_SHOP}/admin/api/${API_VERSION}/graphql.json`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Shopify-Access-Token": await accessToken(env) },
    body: JSON.stringify({ query, variables: variables ?? {} }),
  });
  const json = (await res.json()) as { data?: T; errors?: unknown };
  if (!json.data) throw new Error(`GraphQL error: ${JSON.stringify(json.errors ?? json)}`);
  return json.data;
}

const PRODUCTS_QUERY = `
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

const RULES_QUERY = `
  query LetterboxRules {
    shop {
      rules: metafield(namespace: "custom", key: "brievenbus_capaciteit_standaard") { value }
      rates: metafield(namespace: "custom", key: "verzendtarieven") { value }
    }
  }`;

function parseJson<T>(raw: string | null | undefined): T | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

export async function loadRules(env: Env): Promise<{ rules: Rules; rates: RatesConfig | null }> {
  if (rulesCache && Date.now() - rulesCache.at < RULES_TTL_MS) return rulesCache.value;
  try {
    const data = await graphql<{ shop: { rules: { value: string } | null; rates: { value: string } | null } }>(env, RULES_QUERY);
    const value = { rules: parseJson<Rules>(data.shop.rules?.value) ?? {}, rates: parseJson<RatesConfig>(data.shop.rates?.value) };
    rulesCache = { value, at: Date.now() };
    return value;
  } catch (err) {
    console.error("[carrier] rules lookup failed", err);
    if (rulesCache) return rulesCache.value; // stale beats nothing
    return { rules: {}, rates: null };
  }
}

/** Product info per numeric product id; null when unknown (treated as parcel-only). */
export async function loadProducts(env: Env, productIds: string[]): Promise<Map<string, ProductInfo | null>> {
  const out = new Map<string, ProductInfo | null>();
  const missing: string[] = [];
  const now = Date.now();
  for (const id of new Set(productIds)) {
    const hit = products.get(id);
    if (hit && now - hit.at < PRODUCT_TTL_MS) out.set(id, hit.value);
    else missing.push(id);
  }
  if (missing.length === 0) return out;
  try {
    const data = await graphql<{ nodes: Array<null | {
      id: string; productType: string | null; vendor: string | null; tags: string[];
      collections: { nodes: { handle: string }[] };
      capaciteit: { value: string } | null; groep: { value: string } | null;
    }> }>(env, PRODUCTS_QUERY, { ids: missing.map((id) => `gid://shopify/Product/${id}`) });
    for (const node of data.nodes) {
      if (!node?.id) continue;
      const id = node.id.split("/").pop()!;
      const cap = node.capaciteit?.value != null ? Number(node.capaciteit.value) : null;
      const info: ProductInfo = {
        productType: node.productType ?? "",
        vendor: node.vendor ?? "",
        tags: node.tags ?? [],
        collections: node.collections?.nodes.map((c) => c.handle) ?? [],
        capacityOverride: cap != null && Number.isFinite(cap) ? cap : null,
        groupOverride: node.groep?.value ?? null,
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

export function clearCaches() {
  products.clear();
  rulesCache = null;
}

import assert from "node:assert/strict";
import { test } from "node:test";

import { LIVE, PORTAL, martRowCount, portalSession } from "./live-helpers.ts";

/**
 * The views every tenant gets, rendering from real warehouse data in the running stack.
 *
 * Each view is asserted to contain a figure that could only have come from the semantic API, not
 * merely to return 200. A page that renders its shell and five error panels is still a 200, and a
 * suite that accepted that would be reporting the shell, not the dashboard.
 *
 * PPOB IS NO LONGER IN THIS LIST, and the reason is the point of the change that removed it. The
 * four below are unconditional; PPOB is offered only to a tenant whose own `mart_ppob_transaction`
 * holds rows, so asserting it renders for whichever tenant this suite happens to log in as would
 * be asserting that the conditioning does not work. It has its own test at the foot of this file,
 * which reads the row count first and then asserts whichever behaviour that count requires -
 * never skipping, and never passing without an assertion.
 */

const describe = LIVE ? test : test.skip;

/** The tenant this suite logs in as. Also the tenant slug; see `portalSession`. */
const TENANT = process.env.PORTAL_E2E_TENANT ?? "bct";

const VIEWS = [
  { slug: "overview", heading: "Ringkasan Eksekutif", metric: "revenue_net" },
  { slug: "sales", heading: "Penjualan", metric: "sales_total" },
  { slug: "inventory", heading: "Persediaan", metric: "stock_net_quantity" },
  { slug: "finance", heading: "Keuangan", metric: "account_balance" },
];

for (const view of VIEWS) {
  describe("view " + view.slug + " renders from the semantic layer", async () => {
    const cookie = await portalSession(TENANT);
    const response = await fetch(PORTAL + "/t/" + TENANT + "/" + view.slug, { headers: { cookie } });
    assert.equal(response.status, 200);
    const html = await response.text();
    assert.ok(html.includes(view.heading), "heading missing from " + view.slug);
    assert.ok(
      html.includes(view.metric),
      view.slug + " does not name " + view.metric + ", so nothing on it came from that metric",
    );
    assert.equal(
      html.includes("Panel gagal dimuat"),
      false,
      view.slug + " rendered at least one failed panel",
    );
    assert.ok(
      html.includes("Diperbarui") && html.includes("SLA"),
      view.slug + " does not show pipeline freshness",
    );
  });
}

/**
 * The pair used to be PPOB (60 s) against finance (1 h), which was the widest spread in the
 * platform and therefore the best demonstration. PPOB is now a conditional view, so a tenant
 * without PPOB rows has no PPOB page to read an SLA from and the test would fail for a reason that
 * has nothing to do with freshness. Sales against finance is a narrower spread that every tenant
 * has, and it still proves the thing that matters: the SLA is per metric and comes from the
 * response, not from a constant in this application.
 */
describe("freshness comes from the pipeline, and the SLA differs per view", async () => {
  const cookie = await portalSession(TENANT);
  const sales = await (
    await fetch(PORTAL + "/t/" + TENANT + "/sales", { headers: { cookie } })
  ).text();
  const finance = await (
    await fetch(PORTAL + "/t/" + TENANT + "/finance", { headers: { cookie } })
  ).text();
  assert.ok(sales.includes("SLA 5 menit"), "sales must advertise the 300 second SLA of its metric");
  assert.ok(finance.includes("SLA 1 jam"), "finance must advertise its 60 minute SLA");
  assert.equal(
    finance.includes("SLA 5 menit"),
    false,
    "both views reported the same SLA, so the figure is not coming from the metric",
  );
  assert.ok(
    sales.includes("bukan dari jam perangkat Anda"),
    "the page must say the timestamp is pipeline metadata, not a device clock",
  );
});

/**
 * PPOB, whichever way this deployment's data falls.
 *
 * The row count is read first and BOTH branches assert. A test that skipped when the count was
 * zero would go green on a portal that had deleted the view outright, and a test that assumed a
 * count would fail as soon as somebody reseeded the warehouse - which is how this one came to be
 * written, when tenant `bct`'s rows turned out to be tombstoned and every PPOB assertion in the
 * suite had been passing against an empty mart.
 */
describe("the PPOB view matches this tenant's PPOB data, in whichever direction it falls", async () => {
  const rows = martRowCount(TENANT, "mart_ppob_transaction");
  const cookie = await portalSession(TENANT);
  const response = await fetch(PORTAL + "/t/" + TENANT + "/ppob", { headers: { cookie } });
  assert.equal(response.status, 200);
  const html = await response.text();

  if (rows > 0) {
    assert.ok(html.includes("Operasi PPOB"), "heading missing");
    assert.ok(
      html.includes("ppob_transaction_count"),
      "the view names no figure from ppob_transaction_count despite " + rows + " rows",
    );
    assert.equal(html.includes("Panel gagal dimuat"), false, "a panel failed to load");
    assert.ok(html.includes("SLA 60 detik"), "PPOB must advertise its 60 second SLA");
    return;
  }

  assert.ok(
    html.includes("tidak berlaku untuk data Anda"),
    "tenant " + TENANT + " holds 0 PPOB rows, so the view must say so rather than render zeroes",
  );
  assert.ok(html.includes("mart_ppob_transaction"), "the explanation must name the mart");
  assert.equal(
    html.includes("Rp 0"),
    false,
    "a zero rupiah PPOB commission is exactly what this must stop rendering",
  );
});

describe("the unavailable panels name the metric they would need", async () => {
  const cookie = await portalSession(TENANT);
  const finance = await (await fetch(PORTAL + "/t/" + TENANT + "/finance", { headers: { cookie } })).text();
  assert.ok(finance.includes("Tidak tersedia pada build ini"));
  assert.ok(finance.includes("ppn_output_tax"), "the tax panel must name what it would require");
  assert.equal(
    /PPN\s*[:=]\s*(Rp|[0-9])/.test(finance),
    false,
    "no tax figure may appear anywhere on the finance view",
  );
});

describe("filters persist across views", async () => {
  const cookie = await portalSession(TENANT);
  const set = await fetch(PORTAL + "/api/filters", {
    method: "POST",
    headers: { cookie, "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      next: "/t/" + TENANT + "/sales",
      preset: "custom",
      from: "2026-01-01",
      to: "2026-03-31",
    }),
    redirect: "manual",
  });
  assert.equal(set.status, 303);
  const filterCookie = set.headers
    .getSetCookie()
    .find((entry) => entry.startsWith("insight_portal_filters="));
  assert.notEqual(filterCookie, undefined, "the filter must be persisted in a cookie");
  const both = cookie + "; " + (filterCookie?.split(";", 1)[0] ?? "");

  // Set on Sales, read on Inventory and PPOB: a filter that only survives its own view is not
  // persistence.
  for (const slug of ["sales", "ppob", "overview"]) {
    const html = await (
      await fetch(PORTAL + "/t/" + TENANT + "/" + slug, { headers: { cookie: both } })
    ).text();
    assert.ok(
      html.includes("2026-01-01") && html.includes("2026-03-31"),
      "the filter did not survive navigation to " + slug,
    );
  }
});

describe("a narrowed date range actually changes the figures", async () => {
  const cookie = await portalSession(TENANT);
  const wide = await fetch(PORTAL + "/api/filters", {
    method: "POST",
    headers: { cookie, "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      next: "/t/" + TENANT + "/overview",
      preset: "custom",
      from: "2025-09-01",
      to: "2026-08-31",
    }),
    redirect: "manual",
  });
  const wideCookie =
    wide.headers.getSetCookie().find((entry) => entry.startsWith("insight_portal_filters="))
      ?.split(";", 1)[0] ?? "";
  const wideHtml = await (
    await fetch(PORTAL + "/t/" + TENANT + "/overview", { headers: { cookie: cookie + "; " + wideCookie } })
  ).text();

  const narrow = await fetch(PORTAL + "/api/filters", {
    method: "POST",
    headers: { cookie, "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      next: "/t/" + TENANT + "/overview",
      preset: "custom",
      from: "2026-08-01",
      to: "2026-08-31",
    }),
    redirect: "manual",
  });
  const narrowCookie =
    narrow.headers.getSetCookie().find((entry) => entry.startsWith("insight_portal_filters="))
      ?.split(";", 1)[0] ?? "";
  const narrowHtml = await (
    await fetch(PORTAL + "/t/" + TENANT + "/overview", { headers: { cookie: cookie + "; " + narrowCookie } })
  ).text();

  assert.notEqual(
    wideHtml,
    narrowHtml,
    "a twelve-month view and a one-month view rendered identically; the filter is not reaching the query",
  );
});

describe("drill-down reaches line level and rejects an undeclared dimension", async () => {
  const cookie = await portalSession(TENANT);
  const good = await fetch(
    PORTAL + "/t/" + TENANT + "/drill?metric=revenue_net&by=date_day,revenue_channel&order=-value&limit=100",
    { headers: { cookie } },
  );
  assert.equal(good.status, 200);
  const goodHtml = await good.text();
  assert.ok(goodHtml.includes("revenue_net"));
  assert.equal(goodHtml.includes("Dimensi tidak dideklarasikan"), false);

  const bad = await fetch(PORTAL + "/t/" + TENANT + "/drill?metric=revenue_net&by=not_a_dimension", {
    headers: { cookie },
  });
  assert.equal(bad.status, 200);
  const badHtml = await bad.text();
  assert.ok(
    badHtml.includes("Dimensi tidak dideklarasikan"),
    "an undeclared dimension must be refused against the catalogue before a query is sent",
  );

  const unknownMetric = await fetch(PORTAL + "/t/" + TENANT + "/drill?metric=definitely_not_a_metric", {
    headers: { cookie },
  });
  assert.ok((await unknownMetric.text()).includes("Metrik tidak dikenal"));
});

describe("export produces a CSV carrying its own provenance", async () => {
  const cookie = await portalSession(TENANT);
  const page = await (await fetch(PORTAL + "/t/" + TENANT + "/overview", { headers: { cookie } })).text();
  const href = /\/api\/export\?q=([A-Za-z0-9_-]+)&amp;format=csv&amp;name=([A-Za-z0-9-]+)/.exec(page);
  assert.notEqual(href, null, "no CSV export link found on the overview");
  const url = PORTAL + "/api/export?q=" + href?.[1] + "&format=csv&name=" + href?.[2];
  const response = await fetch(url, { headers: { cookie } });
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /text\/csv/);
  assert.match(response.headers.get("content-disposition") ?? "", /attachment; filename=/);
  const csv = await response.text();
  assert.ok(csv.includes("Model sumber"), "the export must carry its source model");
  assert.ok(csv.includes("Diperbarui (pipeline)"), "the export must carry the pipeline timestamp");
  assert.ok(csv.includes("Status kesegaran"), "the export must say whether it was stale");
});

describe("export produces a real XLSX", async () => {
  const cookie = await portalSession(TENANT);
  const page = await (await fetch(PORTAL + "/t/" + TENANT + "/overview", { headers: { cookie } })).text();
  const href = /\/api\/export\?q=([A-Za-z0-9_-]+)&amp;format=xlsx&amp;name=([A-Za-z0-9-]+)/.exec(page);
  assert.notEqual(href, null, "no XLSX export link found on the overview");
  const url = PORTAL + "/api/export?q=" + href?.[1] + "&format=xlsx&name=" + href?.[2];
  const response = await fetch(url, { headers: { cookie } });
  assert.equal(response.status, 200);
  const bytes = new Uint8Array(await response.arrayBuffer());
  assert.equal(bytes[0], 0x50, "an xlsx must start with the zip magic PK");
  assert.equal(bytes[1], 0x4b);
});

describe("an unauthenticated request never reaches a view", async () => {
  const response = await fetch(PORTAL + "/t/" + TENANT + "/overview", { redirect: "manual" });
  assert.equal(response.status, 307);
  assert.match(response.headers.get("location") ?? "", /\/login/);
});

describe("an unauthenticated API request gets 401, not a redirect", async () => {
  const response = await fetch(PORTAL + "/api/export?q=abc", { redirect: "manual" });
  assert.equal(response.status, 401);
  assert.deepEqual(await response.json(), { error: "unauthorized", detail: "Invalid token." });
});

describe("a forged token is rejected exactly like an absent one", async () => {
  const forged =
    "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0." +
    Buffer.from(JSON.stringify({ tenant_id: "bct", sub: "odoo:bct:2", all_ou: true })).toString(
      "base64url",
    ) +
    ".";
  const response = await fetch(PORTAL + "/t/" + TENANT + "/overview", {
    headers: { cookie: "insight_portal_session=" + forged },
    redirect: "manual",
  });
  assert.equal(response.status, 307, "an alg:none token must not authenticate");
  assert.match(response.headers.get("location") ?? "", /\/login/);
});

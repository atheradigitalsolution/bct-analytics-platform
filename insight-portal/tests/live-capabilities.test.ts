import assert from "node:assert/strict";
import { test } from "node:test";

import { LIVE, PORTAL, martRowCount, portalSession } from "./live-helpers.ts";

/**
 * Views follow the tenant's data, not the code.
 *
 * WHAT WENT WRONG. The view list was a constant, so every client was offered every view. A feed
 * mill opened ATHERA Insight to a navigation bar carrying "Operasi PPOB" and an executive summary
 * whose headline row led with PPOB commission and PPOB success rate. Nothing leaked - the figures
 * were that tenant's own, and they were zero - but a dashboard that names a line of business the
 * client is not in is asserting something false about them, and it was reported exactly that way.
 *
 * WHY EVERY ASSERTION HERE IS PAIRED WITH A ROW COUNT. "The PPOB tab is absent for this tenant"
 * proves nothing on its own: it is equally consistent with the tab having been deleted outright.
 * So each case reads the warehouse first and asserts the precondition it depends on - zero rows in
 * one mart, a non-zero count in another - and only then asserts what the page did. A suite that
 * checked the screen without checking the data would go green on a portal that had simply dropped
 * both views.
 *
 * The tenant is a parameter with a default rather than a literal, so the day `ndi` is renamed this
 * fails with a login error naming the database instead of quietly asserting nothing.
 */

const describe = LIVE ? test : test.skip;

/** A real Odoo tenant that has price-tier rows and no PPOB rows. */
const TENANT = process.env.PORTAL_E2E_PRICING_TENANT ?? "ndi";

function navSlugs(html: string, tenant: string): string[] {
  const slugs = new Set<string>();
  const pattern = new RegExp('href="/t/' + tenant + '/([a-z]+)"', "g");
  for (const match of html.matchAll(pattern)) {
    const slug = match[1];
    if (slug !== undefined && slug !== "drill") slugs.add(slug);
  }
  return [...slugs].sort();
}

describe("a view whose mart is empty for this tenant is not offered", async () => {
  const ppobRows = martRowCount(TENANT, "mart_ppob_transaction");
  assert.equal(
    ppobRows,
    0,
    "this test is written for a tenant with no PPOB rows; " +
      TENANT +
      " now has " +
      ppobRows +
      ", so the case it proves no longer exists here",
  );

  const cookie = await portalSession(TENANT);
  const html = await (
    await fetch(PORTAL + "/t/" + TENANT + "/overview", { headers: { cookie } })
  ).text();

  assert.equal(
    navSlugs(html, TENANT).includes("ppob"),
    false,
    "the navigation still offers PPOB to a tenant with no PPOB rows",
  );
  assert.equal(
    html.includes("Komisi PPOB"),
    false,
    "the executive summary still leads with a PPOB figure for a tenant with no PPOB rows",
  );
  assert.equal(html.includes("Keberhasilan PPOB"), false);
});

describe("reaching a non-applicable view by URL explains itself instead of showing zeroes", async () => {
  assert.equal(martRowCount(TENANT, "mart_ppob_transaction"), 0);
  const cookie = await portalSession(TENANT);
  const response = await fetch(PORTAL + "/t/" + TENANT + "/ppob", { headers: { cookie } });

  // NOT a 403 and NOT a 404. The session is valid and the tenant is right; there is simply nothing
  // of this kind in their data, which is a fact to state rather than an access decision.
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.ok(
    html.includes("tidak berlaku untuk data Anda"),
    "the page must say the view does not apply",
  );
  assert.ok(
    html.includes("mart_ppob_transaction"),
    "the explanation must name the mart, or nobody can check it",
  );
  assert.equal(
    html.includes("Rp 0"),
    false,
    "a zero rupiah PPOB figure is the thing this page exists to stop rendering",
  );
});

describe("a view whose mart has rows for this tenant is offered and renders", async () => {
  const tierRows = martRowCount(TENANT, "mart_sales_price_tier_daily");
  assert.ok(
    tierRows > 0,
    "this test needs a tenant WITH price-tier rows; " +
      TENANT +
      " has none, so a passing capability check would prove nothing",
  );

  const cookie = await portalSession(TENANT);
  const html = await (
    await fetch(PORTAL + "/t/" + TENANT + "/pricing", { headers: { cookie } })
  ).text();

  assert.ok(navSlugs(html, TENANT).includes("pricing"), "the navigation must offer the view");
  assert.equal(
    html.includes("tidak berlaku untuk data Anda"),
    false,
    "the view was offered and then refused to render, which is the worst of both",
  );
  assert.equal(html.includes("Panel gagal dimuat"), false, "a panel failed to load");
  for (const metric of [
    "sales_by_price_tier",
    "gross_margin_pct",
    "sales_below_default_tier_pct",
  ]) {
    assert.ok(html.includes(metric), "the page names no figure from " + metric);
  }
  assert.ok(
    html.includes("Diperbarui") && html.includes("SLA"),
    "the view does not show pipeline freshness",
  );
});

describe("the margin gap is not declared on a page that shows margin", async () => {
  assert.ok(martRowCount(TENANT, "mart_sales_price_tier_daily") > 0);
  const cookie = await portalSession(TENANT);
  const html = await (
    await fetch(PORTAL + "/t/" + TENANT + "/overview", { headers: { cookie } })
  ).text();

  assert.ok(html.includes("Margin kotor"), "the KPI must be there for this test to mean anything");

  // The `<code>` form is what `Unavailable` renders for the metric a gap would need, and it is the
  // only place on the page where a metric name means "this is not produced here". The name also
  // appears in the KPI's own hint, which is the opposite claim, so matching the bare string would
  // pass or fail for the wrong reason either way.
  assert.equal(
    /<code[^>]*>gross_margin_pct<\/code>/.test(html),
    false,
    "the overview declares gross_margin_pct unavailable while rendering it two rows above",
  );

  // The other gaps on this view are real and must survive: resolving one must not be implemented
  // by suppressing the section.
  assert.ok(
    html.includes("ar_ageing_bucket_amount") && html.includes("cash_position"),
    "resolving the margin gap removed the gaps that are still genuine",
  );
});

/**
 * The date filter must not be able to remove a view.
 *
 * This is the failure a naive capability check produces and it is worse than the bug it replaces:
 * a client whose PPOB traffic paused for the selected window would lose the tab, and with it the
 * only control that could have widened the window and shown them why it was empty. The probe
 * therefore asks over every date the column can hold, and this pins that decision.
 */
describe("an empty date window empties the figures without removing the view", async () => {
  assert.ok(martRowCount(TENANT, "mart_sales_price_tier_daily") > 0);
  const cookie = await portalSession(TENANT);
  // A window that predates the warehouse entirely.
  const filters = "insight_portal_filters=from%3D2020-01-01%26to%3D2020-01-31";
  const html = await (
    await fetch(PORTAL + "/t/" + TENANT + "/pricing", {
      headers: { cookie: cookie + "; " + filters },
    })
  ).text();

  assert.ok(navSlugs(html, TENANT).includes("pricing"), "the tab was removed by a date filter");
  assert.equal(
    html.includes("tidak berlaku untuk data Anda"),
    false,
    "an empty window was reported as the tenant not having this kind of data at all",
  );
  assert.ok(
    html.includes("&#x2014;") || html.includes("—"),
    "an empty window must render as an em dash, never as a zero",
  );
});

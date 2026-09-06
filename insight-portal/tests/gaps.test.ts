import assert from "node:assert/strict";
import { test } from "node:test";

import { gapsFor, METRICS_CONSUMED } from "../src/lib/gaps.ts";

/**
 * The unavailable panels, and the one rule about them that can go wrong silently.
 *
 * An "unavailable" panel is an assertion: it says this application does not produce the number and
 * names what would be needed. That makes a STALE entry worse than a missing one - a page that
 * shows gross margin in its headline row while also declaring gross margin unavailable is making
 * its strongest statement about the wrong thing. `gapsFor` therefore takes the same capability the
 * page renders from, and this test pins the two together.
 */

test("the margin gap disappears for a tenant that can actually answer it", () => {
  const withoutPricing = gapsFor("overview").map((gap) => gap.requires);
  const withPricing = gapsFor("overview", { pricing: true }).map((gap) => gap.requires);

  assert.ok(
    withoutPricing.includes("gross_margin_pct"),
    "a tenant with no price-tier rows must still be told why margin is missing",
  );
  assert.equal(
    withPricing.includes("gross_margin_pct"),
    false,
    "a tenant whose margin renders in the KPI row must not also be told margin is unavailable",
  );
});

test("resolving one gap does not quietly drop the others", () => {
  const withoutPricing = gapsFor("overview");
  const withPricing = gapsFor("overview", { pricing: true });
  assert.equal(withPricing.length, withoutPricing.length - 1);
  for (const gap of withPricing) {
    assert.ok(
      withoutPricing.some((other) => other.requires === gap.requires),
      gap.requires + " appeared only in the pricing variant, which no rule produces",
    );
  }
});

test("the default is to keep every gap, so a caller that forgets the flag over-reports", () => {
  // The failure direction matters. A caller that omits `pricing` shows one panel too many, which a
  // reader can see and question. The opposite default would hide a real gap with nothing on screen.
  assert.deepEqual(
    gapsFor("overview").map((gap) => gap.requires),
    gapsFor("overview", {}).map((gap) => gap.requires),
  );
});

test("the pricing view declares its own gaps rather than presenting a complete picture", () => {
  const requires = gapsFor("pricing").map((gap) => gap.requires);
  assert.ok(
    requires.includes("price_tier_coverage_pct"),
    "the uncounted share of lines is the most dangerous figure on that view to invent, so its " +
      "absence must be stated",
  );
  assert.ok(requires.includes("sales_qty_base"));
});

test("every metric the price-tier view queries is on the consumed list", () => {
  for (const metric of [
    "sales_by_price_tier",
    "gross_margin_by_price_tier",
    "gross_margin_pct",
    "sales_below_default_tier_pct",
  ]) {
    assert.ok(METRICS_CONSUMED.includes(metric), metric + " is queried but not declared consumed");
  }
});

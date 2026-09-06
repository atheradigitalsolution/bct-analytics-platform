import assert from "node:assert/strict";
import { test } from "node:test";

import { formatDimension, formatMeasure, formatSla } from "../src/lib/format.ts";

/**
 * Rendering rules that carry meaning, tested where the live data cannot exercise them.
 *
 * `is_profit_and_loss` NULL is the case in point: Backend confirmed this seed contains zero section
 * or note lines, so no live assertion can reach that branch. A NULL-free result today is not
 * evidence that NULL cannot occur, so the label is proven here instead of assumed.
 */

test("a NULL profit-and-loss flag is labelled, not shown as a missing value", () => {
  assert.equal(formatDimension("is_profit_and_loss", null), "Bukan keduanya (NULL)");
  assert.equal(formatDimension("is_profit_and_loss", true), "Ya");
  assert.equal(formatDimension("is_profit_and_loss", false), "Tidak");
});

test("an unassigned operating unit is a member, not a missing value", () => {
  assert.equal(formatDimension("operating_unit_id", -1), "Tanpa Operating Unit");
  assert.equal(formatDimension("operating_unit_id", 1), "1");
});

test("a product with no unit cost is labelled rather than blank", () => {
  assert.equal(formatDimension("has_unit_cost", false), "Tidak");
  assert.equal(formatDimension("has_unit_cost", true), "Ya");
});

test("a 60 second SLA reads as seconds, not as one minute", () => {
  assert.equal(formatSla(60), "60 detik");
  assert.equal(formatSla(300), "5 menit");
  assert.equal(formatSla(900), "15 menit");
  assert.equal(formatSla(3600), "1 jam");
});

test("a null measure is an em dash, never a zero", () => {
  assert.equal(formatMeasure(null, { unit: "IDR", type: "decimal" }), "—");
  assert.equal(formatMeasure(null, { unit: null, type: "percent" }), "—");
});

test("a percent metric is rendered as a percentage, not as a bare fraction", () => {
  assert.equal(formatMeasure(0.9836, { unit: null, type: "percent" }), "98,4%");
  assert.match(formatMeasure(0.12, { unit: null, type: "percent" }, { signed: true }), /^\+12/);
  assert.match(formatMeasure(-0.249, { unit: null, type: "percent" }, { signed: true }), /^-24,9/);
});

/**
 * Price-tier rendering.
 *
 * A missing tier is the case that matters. `sales_by_price_tier` keeps rows whose tier was never
 * recorded rather than discarding them, so the NULL group is part of the total on screen; rendering
 * it as an em dash would make a real and countable group look like a rendering fault. This
 * deployment's rows all carry a tier today, so no live assertion reaches the branch.
 */
test("a sale with no recorded price tier is labelled, not shown as a missing value", () => {
  assert.equal(formatDimension("hj_level", null), "Tanpa tingkat tercatat");
  assert.equal(formatDimension("hj_level_label", null), "Tanpa tingkat tercatat");
  assert.equal(formatDimension("hj_level", 3), "3");
  assert.equal(formatDimension("hj_level_label", "HJ3"), "HJ3");
});

test("slug dimension members are rendered as words, and unknown members still render", () => {
  assert.equal(formatDimension("customer_type", "poultry_shop"), "Poultry Shop");
  assert.equal(formatDimension("sales_region", "kediri_raya"), "Kediri Raya");
  assert.equal(formatDimension("sales_channel", "pos"), "Pos");
  // A member nobody has seen before is the common case for these dimensions: the rule must handle
  // it rather than fall back to the raw slug, which is what a lookup table would have done.
  assert.equal(formatDimension("customer_type", "koperasi_ternak_baru"), "Koperasi Ternak Baru");
  // The rule is scoped. A dimension that is not a slug keeps its value untouched.
  assert.equal(formatDimension("product_key", "prod_a_b"), "prod_a_b");
});

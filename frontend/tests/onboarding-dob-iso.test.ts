import assert from "node:assert/strict";
import test from "node:test";
import {
  ageFromIsoUtc,
  fromIsoDate,
  toIsoDate,
  useMonthDayYearFieldOrder,
} from "../lib/onboarding/dobIso";

test("toIsoDate / fromIsoDate round-trip", () => {
  assert.equal(toIsoDate(1990, 6, 15), "1990-06-15");
  assert.deepEqual(fromIsoDate("1990-06-15"), { y: 1990, m: 6, d: 15 });
  assert.equal(toIsoDate(2000, 2, 29), "2000-02-29");
  assert.equal(toIsoDate(1999, 2, 29), null);
});

test("ageFromIsoUtc: 18 boundary (UTC)", () => {
  const y = new Date().getUTCFullYear() - 18;
  const iso = `${y}-01-15`;
  const age = ageFromIsoUtc(iso);
  assert.ok(age != null && age >= 18);
  const young = `${new Date().getUTCFullYear() - 10}-01-15`;
  assert.ok((ageFromIsoUtc(young) ?? 0) < 18);
});

test("useMonthDayYearFieldOrder: en vs uk", () => {
  assert.equal(useMonthDayYearFieldOrder("en"), true);
  assert.equal(useMonthDayYearFieldOrder("uk"), false);
});

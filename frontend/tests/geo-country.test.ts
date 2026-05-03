import assert from "node:assert/strict";
import test from "node:test";
import { localeForCountry } from "../lib/i18n/geoCountry";

test("country CN -> zh-CN", () => {
  assert.equal(localeForCountry("CN"), "zh-CN");
});

test("country TW -> zh-TW", () => {
  assert.equal(localeForCountry("TW"), "zh-TW");
});

test("country HK/MO -> zh-TW", () => {
  assert.equal(localeForCountry("HK"), "zh-TW");
  assert.equal(localeForCountry("MO"), "zh-TW");
});

test("country SA -> ar", () => {
  assert.equal(localeForCountry("SA"), "ar");
});


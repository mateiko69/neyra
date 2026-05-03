import assert from "node:assert/strict";
import test from "node:test";
import { resolvePreferredLocale } from "../lib/i18n/detect";

test("stored locale always wins", () => {
  const r = resolvePreferredLocale({
    profileLocale: "ru",
    storedLocale: "uk",
    browserLanguages: ["en-US"],
    geoLocale: "zh-CN",
  });
  assert.equal(r.locale, "uk");
  assert.equal(r.source, "stored");
});

test("profile locale wins when no stored locale", () => {
  const r = resolvePreferredLocale({
    profileLocale: "uk",
    storedLocale: null,
    browserLanguages: ["en-US"],
    geoLocale: "ru",
  });
  assert.equal(r.locale, "uk");
  assert.equal(r.source, "profile");
});

test("browser uk -> uk", () => {
  const r = resolvePreferredLocale({ browserLanguages: ["uk-UA", "en-US"] });
  assert.equal(r.locale, "uk");
  assert.equal(r.source, "browser");
});

test("browser en -> en", () => {
  const r = resolvePreferredLocale({ browserLanguages: ["en-US"] });
  assert.equal(r.locale, "en");
  assert.equal(r.source, "browser");
});

test("geo CN -> zh-CN", () => {
  const r = resolvePreferredLocale({ browserLanguages: [], geoLocale: "zh-CN" });
  assert.equal(r.locale, "zh-CN");
  assert.equal(r.source, "geo");
});

test("geo TW -> zh-TW", () => {
  const r = resolvePreferredLocale({ browserLanguages: [], geoLocale: "zh-TW" });
  assert.equal(r.locale, "zh-TW");
  assert.equal(r.source, "geo");
});

test("geo SA -> ar", () => {
  const r = resolvePreferredLocale({ browserLanguages: [], geoLocale: "ar" });
  assert.equal(r.locale, "ar");
  assert.equal(r.source, "geo");
});


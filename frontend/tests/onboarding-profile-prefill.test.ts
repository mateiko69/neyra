import assert from "node:assert/strict";
import test from "node:test";
import { genderToForm, profileToOnboardingFormPartial } from "../lib/onboarding/profilePrefill";

test("genderToForm maps API values to onboarding man/woman", () => {
  assert.equal(genderToForm("male"), "man");
  assert.equal(genderToForm("woman"), "woman");
  assert.equal(genderToForm("F"), "woman");
  assert.equal(genderToForm(""), "");
});

test("profileToOnboardingFormPartial maps profile fields and photo_urls", () => {
  const partial = profileToOnboardingFormPartial({
    display_name: "Alex",
    city: "Berlin",
    gender: "female",
    date_of_birth: "1995-03-15",
    relationship_goal: "dating",
    vibe: "warm",
    interested_in: "men",
    min_preferred_age: 22,
    max_preferred_age: 40,
    native_language: "zh-tw",
    additional_languages: "en,FR",
    interests: "travel,music,gym",
    photo_urls: "https://a.example/a.jpg,https://b.example/b.jpg",
  });
  assert.equal(partial.name, "Alex");
  assert.equal(partial.city, "Berlin");
  assert.equal(partial.gender, "woman");
  assert.equal(partial.date_of_birth, "1995-03-15");
  assert.equal(partial.looking_for, "dating");
  assert.equal(partial.vibe, "warm");
  assert.equal(partial.interested_in, "men");
  assert.equal(partial.min_age, 22);
  assert.equal(partial.max_age, 40);
  assert.equal(partial.native_language, "zh-TW");
  assert.deepEqual(partial.additional_languages, ["en", "fr"]);
  assert.deepEqual(partial.tags, ["travel", "music", "gym"]);
  assert.deepEqual(partial.photos, ["https://a.example/a.jpg", "https://b.example/b.jpg"]);
  assert.equal(partial.primaryIndex, 0);
});

test("profileToOnboardingFormPartial returns {} for non-object", () => {
  assert.deepEqual(profileToOnboardingFormPartial(null), {});
  assert.deepEqual(profileToOnboardingFormPartial("x"), {});
});

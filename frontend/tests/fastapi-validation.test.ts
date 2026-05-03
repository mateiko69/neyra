/**
 * FastAPI 422 detail[] → formatApiError wire → localized UI (no raw Pydantic text).
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { formatApiError } from "../lib/apiErrorFormat";
import {
  fieldKeyFromLoc,
  mapItemToKind,
  wireFromFastApiDetailArray,
} from "../lib/i18n/fastApiValidation";
import { humanizeI18nKey } from "../lib/i18n/locales";
import { translateApiUserMessage, type TranslateFn } from "../lib/i18n/translateApiUserMessage";
import { normalizeLanguageCodes } from "../lib/languages";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const enPath = path.join(ROOT, "locales", "en.json");
const enMessages = JSON.parse(fs.readFileSync(enPath, "utf8")) as Record<string, string>;

const t: TranslateFn = (key, vars) => {
  let raw = enMessages[key];
  if (raw === undefined && key.startsWith("errors.validation.fields.")) {
    raw = humanizeI18nKey(key);
  }
  let s = raw ?? key;
  if (vars) {
    for (const [name, value] of Object.entries(vars)) {
      s = s.split(`{${name}}`).join(String(value));
    }
  }
  return s;
};

/** Phrases that appear in raw FastAPI/Pydantic `detail[].msg`, not in our i18n strings. */
const RAW_PYDANTIC = /Field required|pydantic|String should have at least|Value error,|value is not a valid email address|https:\/\/errors\.pydantic/i;

test("wireFromFastApiDetailArray: single missing field keeps compact wire", () => {
  const detail = [{ type: "missing", loc: ["body", "email"], msg: "Field required", input: {} }];
  assert.equal(wireFromFastApiDetailArray(detail), "validation\trequired\temail");
});

test("wireFromFastApiDetailArray: two missing fields → multi wire (kind/field pairs)", () => {
  const detail = [
    { type: "missing", loc: ["body", "email"], msg: "Field required", input: {} },
    { type: "missing", loc: ["body", "password"], msg: "Field required", input: {} },
  ];
  assert.equal(
    wireFromFastApiDetailArray(detail),
    "validation\tmulti\trequired\temail\trequired\tpassword",
  );
});

test("wireFromFastApiDetailArray: invalid email → email + field", () => {
  const detail = [
    {
      type: "value_error",
      loc: ["body", "email"],
      msg: "value is not a valid email address: An email address must have an @-sign.",
      input: "x",
    },
  ];
  assert.equal(wireFromFastApiDetailArray(detail), "validation\temail\temail");
});

test("wireFromFastApiDetailArray: short password → too_short", () => {
  const detail = [
    {
      type: "string_too_short",
      loc: ["body", "password"],
      msg: "String should have at least 8 characters",
      input: "short",
      ctx: { min_length: 8 },
    },
  ];
  assert.equal(wireFromFastApiDetailArray(detail), "validation\ttoo_short\tpassword");
});

test("mapItemToKind: enum → invalid_choice", () => {
  assert.equal(
    mapItemToKind({
      type: "enum",
      loc: ["body", "status"],
      msg: "Input should be 'a' or 'b'",
    }),
    "invalid_choice",
  );
});

test("mapItemToKind: date parsing → invalid_type", () => {
  assert.equal(
    mapItemToKind({
      type: "date_from_datetime_parsing",
      loc: ["body", "d"],
      msg: "Input should be a valid date or datetime, invalid character in year",
    }),
    "invalid_type",
  );
});

test("fieldKeyFromLoc skips top-level loc prefix only as final segment", () => {
  assert.equal(fieldKeyFromLoc(["body", "email"]), "email");
  assert.equal(fieldKeyFromLoc(["body"]), "");
});

test("formatApiError + translateApiUserMessage: no raw Pydantic for RegisterIn-style 422", () => {
  const bodies: string[] = [
    JSON.stringify({
      detail: [{ type: "missing", loc: ["body", "email"], msg: "Field required", input: {} }],
    }),
    JSON.stringify({
      detail: [
        {
          type: "value_error",
          loc: ["body", "email"],
          msg: "value is not a valid email address: An email address must have an @-sign.",
          input: "x",
        },
      ],
    }),
    JSON.stringify({
      detail: [
        {
          type: "string_too_short",
          loc: ["body", "password"],
          msg: "String should have at least 8 characters",
          input: "short",
          ctx: { min_length: 8 },
        },
      ],
    }),
  ];
  for (const text of bodies) {
    const wire = formatApiError(text, 422);
    assert.doesNotMatch(wire, RAW_PYDANTIC, `wire should not expose Pydantic: ${wire}`);
    const ui = translateApiUserMessage(wire, t);
    assert.doesNotMatch(ui, RAW_PYDANTIC, `UI should not expose Pydantic: ${ui}`);
  }
});

test("localized copy includes field label for email required", () => {
  const wire = formatApiError(
    JSON.stringify({
      detail: [{ type: "missing", loc: ["body", "email"], msg: "Field required", input: {} }],
    }),
    422,
  );
  const ui = translateApiUserMessage(wire, t);
  assert.match(ui, /Email/i);
  assert.match(ui, /required/i);
});

test("localized copy for invalid email and short password", () => {
  const badEmail = formatApiError(
    JSON.stringify({
      detail: [
        {
          type: "value_error",
          loc: ["body", "email"],
          msg: "value is not a valid email address: An email address must have an @-sign.",
          input: "x",
        },
      ],
    }),
    422,
  );
  assert.match(translateApiUserMessage(badEmail, t), /Email/i);
  assert.match(translateApiUserMessage(badEmail, t), /valid/i);

  const shortPw = formatApiError(
    JSON.stringify({
      detail: [
        {
          type: "string_too_short",
          loc: ["body", "password"],
          msg: "String should have at least 8 characters",
          input: "x",
        },
      ],
    }),
    422,
  );
  assert.match(translateApiUserMessage(shortPw, t), /Password/i);
  assert.match(translateApiUserMessage(shortPw, t), /short/i);
});

test("catalog field labels: first_name, city, phone use en copy", () => {
  for (const [field, word] of [
    ["first_name", "First name"],
    ["city", "City"],
    ["phone", "Phone"],
  ] as const) {
    const ui = translateApiUserMessage(`validation\trequired\t${field}`, t);
    assert.ok(ui.includes(word), ui);
  }
});

test("unknown API field: humanized label, no snake_case or i18n key path in UI", () => {
  const wire = "validation\trequired\tlegacy_api_field_xyz";
  const ui = translateApiUserMessage(wire, t);
  assert.doesNotMatch(ui, /legacy_api_field_xyz/);
  assert.doesNotMatch(ui, /errors\.validation/);
  assert.match(ui, /Legacy Api Field Xyz/);
  assert.match(ui, /required/i);
});

test("normalizeLanguageCodes: filters invalid non-string values", () => {
  assert.deepEqual(normalizeLanguageCodes(["en", {}, "  ", "uk", null, undefined, "ru"]), ["en", "uk", "ru"]);
});

test("multiple errors: prioritized order (required before too_short) and localized join", () => {
  const detail = [
    {
      type: "string_too_short",
      loc: ["body", "password"],
      msg: "String should have at least 8 characters",
      input: "x",
      ctx: { min_length: 8 },
    },
    { type: "missing", loc: ["body", "email"], msg: "Field required", input: {} },
  ];
  const wire = wireFromFastApiDetailArray(detail);
  assert.equal(wire, "validation\tmulti\trequired\temail\ttoo_short\tpassword");
  const ui = translateApiUserMessage(wire, t);
  assert.match(ui, /^Email is required\. Password is too short\.$/);
  assert.doesNotMatch(ui, RAW_PYDANTIC);
});

test("at most three validation errors in wire and UI", () => {
  const detail = [
    { type: "missing", loc: ["body", "a"], msg: "Field required", input: {} },
    { type: "missing", loc: ["body", "b"], msg: "Field required", input: {} },
    { type: "missing", loc: ["body", "c"], msg: "Field required", input: {} },
    { type: "missing", loc: ["body", "d"], msg: "Field required", input: {} },
  ];
  const wire = wireFromFastApiDetailArray(detail);
  assert.ok(wire?.startsWith("validation\tmulti\t"));
  const pairs = wire!.split("\t").length - 2;
  assert.equal(pairs % 2, 0);
  assert.equal(pairs / 2, 3);
  const ui = translateApiUserMessage(wire!, t);
  assert.equal((ui.match(/is required\./g) || []).length, 3);
  assert.doesNotMatch(ui, RAW_PYDANTIC);
});

test("formatApiError: RegisterIn empty body yields multi + localized, no Pydantic in UI", () => {
  const text = JSON.stringify({
    detail: [
      { type: "missing", loc: ["body", "email"], msg: "Field required", input: {} },
      { type: "missing", loc: ["body", "password"], msg: "Field required", input: {} },
      { type: "missing", loc: ["body", "display_name"], msg: "Field required", input: {} },
    ],
  });
  const wire = formatApiError(text, 422);
  assert.ok(wire.startsWith("validation\tmulti\t"));
  const ui = translateApiUserMessage(wire, t);
  assert.match(ui, /Email is required\./);
  assert.match(ui, /Password is required\./);
  assert.match(ui, /Display name is required\./);
  assert.doesNotMatch(ui, RAW_PYDANTIC);
});

test("leaked fields.* key path from t() is replaced with humanized fallback", () => {
  const leakyT: TranslateFn = (key, vars) => {
    if (key === "errors.validation.fieldFallbackName" && vars?.name != null) {
      return String(vars.name);
    }
    if (key.startsWith("errors.validation.fields.")) return key;
    const raw = enMessages[key];
    let s = raw ?? key;
    if (vars) {
      for (const [name, value] of Object.entries(vars)) {
        s = s.split(`{${name}}`).join(String(value));
      }
    }
    return s;
  };
  const ui = translateApiUserMessage("validation\trequired\tweird_custom_thing", leakyT);
  assert.doesNotMatch(ui, /errors\.validation\.fields/);
  assert.doesNotMatch(ui, /weird_custom_thing/);
  assert.match(ui, /Weird Custom Thing/);
});

import assert from "node:assert/strict";
import test from "node:test";

import { normalizeSendMessageResponse } from "../lib/chat/normalize";

test("normalizeSendMessageResponse consumes demo scheduling fields and demo reply", () => {
  const raw = {
    message: {
      id: 101,
      sender_id: 7,
      receiver_id: 11,
      content: "Hello demo",
      created_at: "2026-04-29T10:00:00.000Z",
      is_read: true,
    },
    demo_partner: true,
    demo_reply_scheduled: true,
    expected_reply_delay_seconds: 2,
    demo_reply: {
      id: 102,
      sender_id: 11,
      receiver_id: 7,
      content: "Hi! I am a demo profile. How is your day going?",
      created_at: "2026-04-29T10:00:02.000Z",
      is_read: false,
    },
  };

  const normalized = normalizeSendMessageResponse(raw);
  assert.ok(normalized && normalized.kind === "sent");
  if (!normalized || normalized.kind !== "sent") return;

  assert.equal(normalized.demoPartner, true);
  assert.equal(normalized.demoReplyScheduled, true);
  assert.equal(normalized.expectedReplyDelaySeconds, 2);
  assert.equal(normalized.extraMessages?.length, 1);
  assert.equal(normalized.extraMessages?.[0]?.senderId, 11);
  assert.match(String(normalized.extraMessages?.[0]?.content ?? ""), /demo profile/i);
});

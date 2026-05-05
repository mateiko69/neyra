import type { TranslationVars } from "./index";
import { humanizeI18nKey } from "./locales";
import { i18nKey, rawI18nText, type I18nText } from "./message";

export type TranslateFn = (key: string, vars?: TranslationVars) => string;

function validationFieldLabel(fieldKey: string, t: TranslateFn): string {
  const fieldsKey = `errors.validation.fields.${fieldKey}`;
  const humanized = humanizeI18nKey(fieldsKey);
  let label = t(fieldsKey);
  const trimmed = label.trim();
  if (
    trimmed === fieldsKey ||
    trimmed === fieldKey ||
    /^errors\.validation\.fields\.[a-z0-9_]+$/i.test(trimmed)
  ) {
    label = t("errors.validation.fieldFallbackName", { name: humanized });
  }
  return label;
}

const VALIDATION_KIND_TO_MSG_KEY: Record<string, string> = {
  required: "errors.validation.required",
  email: "errors.validation.email",
  too_short: "errors.validation.tooShort",
  too_long: "errors.validation.tooLong",
  invalid_type: "errors.validation.invalidType",
  invalid_choice: "errors.validation.invalidChoice",
  generic: "errors.validation.generic",
};

function validationSingleSentence(kind: string, fieldKey: string, t: TranslateFn): string {
  const k = (kind || "generic").trim() || "generic";
  const fieldLabel = fieldKey ? validationFieldLabel(fieldKey, t) : t("errors.validation.fieldLabelFallback");
  const msgKey = VALIDATION_KIND_TO_MSG_KEY[k] ?? "errors.validation.generic";
  return t(msgKey, { field: fieldLabel });
}

/** Backend `detail.code` values (API v1). */
const ERROR_CODES: Record<string, string> = {
  "auth.email_taken": "errors.api.auth.emailTaken",
  "auth.invalid_credentials": "errors.api.auth.invalidCredentials",
  "auth.social_only": "errors.api.auth.socialOnly",
  "profile.not_found": "errors.api.profileNotFound",
  "profile.no_fields_to_update": "errors.api.profile.noFieldsToUpdate",
  "profile.use_me_endpoint": "errors.api.profile.useMeEndpoint",
  "profile.save_failed": "errors.api.profile.saveFailed",
  "profile.verify.clip_required": "errors.api.profile.verify.clipRequired",
  "profile.verify.frames_read_failed": "errors.api.profile.verify.framesReadFailed",
  "profile.verify.motion_required": "errors.api.profile.verify.motionRequired",
  "profile.verify.needs_primary_photo": "errors.api.profile.verify.needsPrimaryPhoto",
  "profile.verify.rate_limited": "errors.api.profile.verify.rateLimited",
  "profile.verify.missing_frames": "errors.api.profile.verify.missingFrames",
  "profile.verify.missing_filename": "errors.api.profile.verify.missingFilename",
  "profile.verify.invalid_frame": "errors.api.profile.verify.invalidFrame",
  "profile.verify.frames_process_failed": "errors.api.profile.verify.framesProcessFailed",
  "profile.verify.frames_unreadable": "errors.api.profile.verify.framesUnreadable",
  "profile.verify.liveness_failed": "errors.api.profile.verify.livenessFailed",
  "profile.verify.needs_profile_photo": "errors.api.profile.verify.needsProfilePhoto",
  "profile.verify.persist_failed": "errors.api.profile.verify.persistFailed",
  "profile.verify.selfie_url_required": "errors.api.profile.verify.selfieUrlRequired",
  "profile.verify.selfie_url_too_long": "errors.api.profile.verify.selfieUrlTooLong",
  "profile.verify.selfie_unreadable": "errors.api.profile.verify.selfieUnreadable",
  "profile.verify.live_camera_required": "errors.api.profile.verify.liveCameraRequired",
  "profile.verify.invalid_pose": "errors.api.profile.verify.invalidPose",
  "upload.empty": "errors.api.upload.empty",
  "upload.image_too_large": "errors.api.upload.imageTooLarge",
  "upload.audio_too_large": "errors.api.upload.audioTooLarge",
  "upload.image_type_not_allowed": "errors.api.upload.imageTypeNotAllowed",
  "upload.audio_type_not_allowed": "errors.api.upload.audioTypeNotAllowed",
  "upload.no_files": "errors.api.upload.noFiles",
  "upload.too_many_files": "errors.api.upload.tooManyFiles",
  "upload.item_failed": "errors.api.upload.itemFailed",
  "upload.storage_unavailable": "errors.api.upload.storageUnavailable",
  "safety.invalid_target": "errors.api.safety.invalidTarget",
  "safety.user_not_found": "errors.api.safety.userNotFound",
  "safety.demo_report_forbidden": "errors.api.safety.demoReportForbidden",
  "safety.report_reason_required": "errors.api.safety.reportReasonRequired",
  "safety.report_reason_too_long": "errors.api.safety.reportReasonTooLong",
  "chat.demo_disabled": "errors.api.demoModeDisabled",
  "chat.user_blocked": "errors.api.userBlocked",
  "chat.match_required": "errors.api.matchRequired",
  "chat.invalid_match": "errors.api.chatInvalidMatch",
  "chat.match_not_found": "errors.api.chatMatchNotFound",
  "chat.match_forbidden": "errors.api.chatMatchForbidden",
  "chat.rate_limit_personalize": "errors.api.slowDownPersonalize",
  "chat.rate_limit_new_chat": "errors.api.waitBeforeNewChat",
  "chat.message_blocked": "errors.api.chat.messageBlocked",
  "chat.moderation_blocked": "errors.api.chat.moderationBlocked",
  "chat.reply_not_found": "errors.api.replyTargetNotFound",
  "chat.reply_invalid_target": "errors.api.invalidReplyTarget",
  "chat.send_failed": "errors.api.sendMessageFailed",
  "chat.reaction_invalid": "errors.api.invalidReaction",
  "chat.message_not_found": "errors.api.messageNotFound",
  "subscription.invalid_plan": "errors.api.subscription.invalidPlan",
  "chat.premium_required": "errors.api.premiumRequired",
  "ai.suggestions_disabled": "errors.api.ai.suggestionsDisabled",
  "ai.rate_limited": "errors.api.ai.rateLimited",
  "referral.invalid": "errors.api.referral.invalid",
  "referral.self": "errors.api.referral.self",
  "referral.already_claimed": "errors.api.referral.already_claimed",
};

/** Exact FastAPI `detail` strings (string body) or thrown Error.message values we surface in UI. */
const EXACT: Record<string, string> = {
  "User is blocked": "errors.api.userBlocked",
  "Demo mode is disabled": "errors.api.demoModeDisabled",
  "Please slow down and personalize your message.": "errors.api.slowDownPersonalize",
  "Please wait a moment before starting another chat.": "errors.api.waitBeforeNewChat",
  "Failed to send message": "errors.api.sendMessageFailed",
  "Invalid reaction": "errors.api.invalidReaction",
  "Message not found": "errors.api.messageNotFound",
  "Reply target not found": "errors.api.replyTargetNotFound",
  "Invalid reply target": "errors.api.invalidReplyTarget",
  "You need to match before chatting": "errors.api.matchRequired",
  "Premium required": "errors.api.premiumRequired",
  "Confirmation required": "errors.api.confirmationRequired",
  "Password required": "errors.api.passwordRequired",
  "Invalid password": "errors.api.invalidPassword",
  "User not found": "errors.api.userNotFound",
  "Restore window expired": "errors.api.restoreExpired",
  "Profile not found": "errors.api.profileNotFound",
  "Invalid event name": "errors.api.invalidEventName",
  "Unauthorized": "errors.api.unauthorized",
  "Rate limited": "errors.api.rateLimited",
  "feature is required": "errors.api.featureRequired",
};

export function translateApiUserMessage(raw: string, t: TranslateFn): string {
  const s = (raw || "").trim();
  if (!s) return t("errors.api.generic");
  if (s === "THROTTLE_SKIP" || s === "Request aborted") return "";

  const tabbed = s.split("\t");
  const code = tabbed[0] || "";
  const tabArg = tabbed[1];
  if (code === "upload.item_failed" && tabArg) {
    return t("errors.api.upload.itemFailed", { part: tabArg });
  }
  if (code === "upload.too_many_files" && tabArg) {
    return t("errors.api.upload.tooManyFiles", { max: tabArg });
  }

  if (code === "validation") {
    const kindFirst = (tabbed[1] || "generic").trim();
    if (kindFirst === "multi") {
      const parts: string[] = [];
      for (let i = 2; i < tabbed.length && parts.length < 3; i += 2) {
        const k = (tabbed[i] ?? "generic").trim() || "generic";
        const f = (tabbed[i + 1] ?? "").trim();
        parts.push(validationSingleSentence(k, f, t));
      }
      return parts.join(" ");
    }
    const fieldKey = (tabbed[2] ?? "").trim();
    return validationSingleSentence(kindFirst, fieldKey, t);
  }

  if (ERROR_CODES[code]) return t(ERROR_CODES[code]);

  if (EXACT[s]) return t(EXACT[s]);

  if (/^Rate limited$/i.test(s)) return t("errors.api.rateLimited");
  const rl = s.match(/^Rate limited:\s*(.+)$/is);
  if (rl) return t("errors.api.rateLimitedDetail", { detail: rl[1].trim() });

  if (s.startsWith("API unreachable (")) return t("errors.api.unreachable");

  const rf = s.match(/^Request failed \((\d+)\)\s*$/);
  if (rf) return t("errors.api.requestFailedStatus", { status: rf[1] });

  if (s.startsWith("Message blocked:")) {
    const detail = s.replace(/^Message blocked:\s*/i, "").trim();
    return t("errors.api.messageBlocked", { detail: detail || t("errors.api.policy") });
  }
  if (s.startsWith("Blocked by moderation:")) {
    const detail = s.replace(/^Blocked by moderation:\s*/i, "").trim();
    return t("errors.api.moderationBlocked", { detail: detail || t("errors.api.policy") });
  }

  return s;
}

/** Maps thrown API/network errors to user-visible copy; falls back to `fallbackKey` when empty after translation. */
export function apiFailureToI18nText(
  errorValue: unknown,
  t: TranslateFn,
  fallbackKey: string,
  formatApi?: (msg: string, code: number) => string,
): NonNullable<I18nText> {
  const rawMsg =
    errorValue instanceof Error
      ? errorValue.message
      : formatApi
        ? formatApi(String(errorValue), 0)
        : String(errorValue ?? "");
  const trimmed = rawMsg.trim();
  if (!trimmed) return i18nKey(fallbackKey);
  const ui = translateApiUserMessage(trimmed, t).trim();
  return ui ? rawI18nText(ui) : i18nKey(fallbackKey);
}

"use client";

import type { CSSProperties } from "react";
import { useEffect, useRef, useState } from "react";
import { dispatchAuthExpired } from "../../lib/auth/navigation";
import {
  ApiUnauthorizedError,
  apiFetch,
  apiUpload,
  ensureAuthBootstrapped,
  formatApiError,
  getToken,
  invalidateApiGetCache,
} from "../../lib/api";
import { invalidateMyProfileAvatarCache } from "../../lib/meProfileCache";
import { i18nKey, rawI18nText, resolveI18nText, type I18nText } from "../../lib/i18n/message";
import { apiFailureToI18nText } from "../../lib/i18n/translateApiUserMessage";
import { useT } from "./i18n/I18nProvider";
import { SafeImg } from "./SafeImg";
import { Button } from "./ui";

const MAX_PHOTOS = 6;
const MAX_BYTES = 8 * 1024 * 1024;
/** Broad accept for the native picker; server still validates type and size. */
const ACCEPT_IMAGES = "image/*";

/** Stable id for label / mobile picker reliability. */
export const PROFILE_PHOTO_FILE_INPUT_ID = "neyra-profile-photo-input";

/** `auth_redirect` = session invalid; full navigation to /login is in progress. */
type PhotoUploadResult = { url?: string } | null | "auth_redirect";

function isTransientUploadNetworkError(e: unknown): boolean {
  if (e instanceof ApiUnauthorizedError) return false;
  if (e instanceof TypeError) return true;
  if (e instanceof Error) {
    return /\b503\b|\b502\b|\b504\b|\b522\b|network|fetch|unreachable|failed to fetch|rate limited/i.test(
      String(e.message),
    );
  }
  return false;
}

async function withTransientUploadRetry<T>(run: () => Promise<T>): Promise<T> {
  try {
    return await run();
  } catch (e) {
    if (!isTransientUploadNetworkError(e)) throw e;
    await new Promise((r) => setTimeout(r, 750));
    return await run();
  }
}

async function uploadPhotoWithAuthRetry(file: File): Promise<PhotoUploadResult> {
  const run = () => {
    const formData = new FormData();
    formData.append("file", file);
    return apiUpload("/uploads/photo", formData) as Promise<{ url?: string } | null>;
  };
  try {
    return await withTransientUploadRetry(() => run());
  } catch (e) {
    if (e instanceof ApiUnauthorizedError) {
      await ensureAuthBootstrapped();
      if (typeof window !== "undefined" && !getToken()) {
        dispatchAuthExpired();
        return "auth_redirect";
      }
      try {
        return await withTransientUploadRetry(() => run());
      } catch (e2) {
        if (e2 instanceof ApiUnauthorizedError && typeof window !== "undefined") {
          dispatchAuthExpired();
          return "auth_redirect";
        }
        throw e2;
      }
    }
    throw e;
  }
}

async function uploadProfileGalleryPhotoWithAuthRetry(file: File): Promise<unknown | "auth_redirect"> {
  const run = () => {
    const formData = new FormData();
    formData.append("file", file);
    return apiUpload("/profile/photos", formData, { metaReason: "profile-gallery-upload" }) as Promise<unknown>;
  };
  try {
    return await withTransientUploadRetry(() => run());
  } catch (e) {
    if (e instanceof ApiUnauthorizedError) {
      await ensureAuthBootstrapped();
      if (typeof window !== "undefined" && !getToken()) {
        dispatchAuthExpired();
        return "auth_redirect";
      }
      try {
        return await withTransientUploadRetry(() => run());
      } catch (e2) {
        if (e2 instanceof ApiUnauthorizedError && typeof window !== "undefined") {
          dispatchAuthExpired();
          return "auth_redirect";
        }
        throw e2;
      }
    }
    throw e;
  }
}

async function persistPrimaryPhotoUrl(url: string) {
  const patch = async () => {
    await apiFetch("/profiles/me", {
      method: "PATCH",
      body: JSON.stringify({ primary_photo_url: url }),
      skipThrottle: true,
      skipCache: true,
      metaReason: "photo-upload-persist-primary",
    });
  };
  try {
    await patch();
  } catch (e) {
    if (e instanceof ApiUnauthorizedError) {
      await ensureAuthBootstrapped();
      if (typeof window !== "undefined" && !getToken()) {
        dispatchAuthExpired();
        return;
      }
      try {
        await apiFetch("/auth/me", {
          method: "GET",
          skipAuthRedirect: true,
          skipThrottle: true,
          skipCache: true,
          metaReason: "photo-upload-auth-recheck",
        });
        await patch();
      } catch (e2) {
        if (e2 instanceof ApiUnauthorizedError && typeof window !== "undefined") {
          dispatchAuthExpired();
          return;
        }
        /* best-effort; upload already persisted server-side */
      }
    }
  } finally {
    invalidateApiGetCache("/profiles/me");
    invalidateMyProfileAvatarCache();
  }
}

type PendingSlot = {
  id: string;
  blobUrl: string;
  fileName: string;
  uploading: boolean;
  error?: NonNullable<I18nText>;
};

type ProfileGalleryPhotoRow = { id?: unknown; url?: unknown; is_primary?: unknown };

export function normalizeProfileGalleryPhotos(data: unknown): { urls: string[]; photoIds: (number | null)[]; primaryIndex: number } {
  const raw = data as { photos?: unknown };
  let photos: ProfileGalleryPhotoRow[] = [];
  if (Array.isArray(data)) photos = data as ProfileGalleryPhotoRow[];
  else if (Array.isArray(raw.photos)) photos = raw.photos as ProfileGalleryPhotoRow[];
  const urls: string[] = [];
  const photoIds: (number | null)[] = [];
  let primaryIndex = 0;
  for (let i = 0; i < photos.length; i++) {
    const p = photos[i];
    const u = String((p?.url as string) ?? "").trim();
    if (!u) continue;
    urls.push(u);
    const idRaw = p?.id;
    photoIds.push(typeof idRaw === "number" && Number.isFinite(idRaw) ? idRaw : null);
    if (p?.is_primary === true) primaryIndex = urls.length - 1;
  }
  if (urls.length === 0) return { urls, photoIds, primaryIndex: 0 };
  primaryIndex = Math.max(0, Math.min(primaryIndex, urls.length - 1));
  return { urls, photoIds, primaryIndex };
}

function normalizedRowsFromList(rows: ProfileGalleryPhotoRow[]): { urls: string[]; photoIds: (number | null)[]; primaryIndex: number } {
  return normalizeProfileGalleryPhotos(rows);
}

type Props = {
  urls: string[];
  primaryIndex: number;
  onChange: (urls: string[], primaryIndex: number) => void;
  onError: (message: NonNullable<I18nText>) => void;
  disabled?: boolean;
  /** Use `/profile/photos` REST + multipart upload when storage is configured (see `photo_upload_available`). */
  useProfileGalleryApi?: boolean;
  /** Same length as `urls` when gallery API is active; `null` until loaded from GET /profile/photos. */
  photoIdsByIndex?: (number | null)[];
  onGallerySynced?: (urls: string[], photoIds: (number | null)[], primaryIndex: number) => void;
};

/** Off-screen (not display:none) so `inputRef.current?.click()` still opens the picker reliably. */
const offScreenFileInput: CSSProperties = {
  position: "fixed",
  left: "-10000px",
  top: 0,
  width: 1,
  height: 1,
  opacity: 0,
  overflow: "hidden",
  margin: 0,
  padding: 0,
  border: 0,
};

export function PhotoUploader({
  urls,
  primaryIndex,
  onChange,
  onError,
  disabled,
  useProfileGalleryApi = false,
  photoIdsByIndex,
  onGallerySynced,
}: Props) {
  const { t } = useT("PhotoUploader");
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [pending, setPending] = useState<PendingSlot[]>([]);
  const [busy, setBusy] = useState(false);
  const [successHint, setSuccessHint] = useState<I18nText>(null);
  const blobRegistry = useRef(new Set<string>());

  const validateImageFile = (file: File): NonNullable<I18nText> | null => {
    if (file.size > MAX_BYTES) {
      return i18nKey("photos.validation.tooLarge", { name: file.name });
    }
    const mimeOk = !!(file.type && file.type.startsWith("image/"));
    const extOk = /\.(jpe?g|png|gif|webp)$/i.test(file.name);
    if (!mimeOk && !extOk) {
      return i18nKey("photos.validation.unsupported", { name: file.name });
    }
    return null;
  };

  const registerBlob = (url: string) => {
    blobRegistry.current.add(url);
  };

  const revokeBlob = (url: string) => {
    if (blobRegistry.current.has(url)) {
      blobRegistry.current.delete(url);
      URL.revokeObjectURL(url);
    }
  };

  useEffect(() => {
    const registry = blobRegistry.current;
    return () => {
      registry.forEach((url) => URL.revokeObjectURL(url));
      registry.clear();
    };
  }, []);

  const applyGalleryState = (payload: unknown) => {
    const normalized = normalizeProfileGalleryPhotos(payload);
    onChange(normalized.urls, normalized.primaryIndex);
    onGallerySynced?.(normalized.urls, normalized.photoIds, normalized.primaryIndex);
    invalidateApiGetCache("/profiles/me");
    invalidateMyProfileAvatarCache();
  };

  const refetchGallery = async (): Promise<void> => {
    const rows = (await apiFetch("/profile/photos", {
      method: "GET",
      skipThrottle: true,
      skipCache: true,
      metaReason: "profile-gallery-refetch",
    })) as ProfileGalleryPhotoRow[];
    const norm = normalizedRowsFromList(Array.isArray(rows) ? rows : []);
    onChange(norm.urls, norm.primaryIndex);
    onGallerySynced?.(norm.urls, norm.photoIds, norm.primaryIndex);
    invalidateApiGetCache("/profiles/me");
    invalidateMyProfileAvatarCache();
  };

  const slotsUsed = urls.length + pending.length;
  const remainingSlots = MAX_PHOTOS - slotsUsed;

  async function onFilesSelected(files: FileList | null) {
    if (!files?.length || disabled || busy) return;
    if (remainingSlots <= 0) {
      onError(i18nKey("photos.limit", { count: MAX_PHOTOS }));
      return;
    }

    const rawList = Array.from(files);
    console.log(
      "[PhotoUploader] files selected",
      rawList.map((file) => ({ name: file.name, type: file.type, size: file.size })),
    );

    const pairs: { file: File; slot: PendingSlot }[] = [];
    for (const file of rawList) {
      if (pairs.length >= remainingSlots) break;
      const validationError = validateImageFile(file);
      if (validationError) {
        onError(validationError);
        continue;
      }
      const blobUrl = URL.createObjectURL(file);
      registerBlob(blobUrl);
      pairs.push({
        file,
        slot: {
          id: crypto.randomUUID(),
          blobUrl,
          fileName: file.name,
          uploading: true,
        },
      });
    }

    if (!pairs.length) {
      if (inputRef.current) inputRef.current.value = "";
      return;
    }

    setPending((current) => [...current, ...pairs.map((pair) => pair.slot)]);
    setBusy(true);

    let nextUrls = [...urls];
    const nextPrimaryIndex = urls.length === 0 ? 0 : Math.min(primaryIndex, Math.max(0, urls.length - 1));

    try {
      for (const { file, slot } of pairs) {
        try {
          let data: PhotoUploadResult | unknown;
          if (useProfileGalleryApi) {
            try {
              data = await uploadProfileGalleryPhotoWithAuthRetry(file);
            } catch (galleryErr: unknown) {
              if (galleryErr instanceof ApiUnauthorizedError && typeof window !== "undefined") {
                dispatchAuthExpired();
                return;
              }
              console.warn("[PhotoUploader] gallery upload failed; falling back to /uploads/photo", galleryErr);
              const legacyFb = await uploadPhotoWithAuthRetry(file);
              if (legacyFb === "auth_redirect") {
                setBusy(false);
                if (inputRef.current) inputRef.current.value = "";
                return;
              }
              const lf = legacyFb && typeof legacyFb === "object" ? (legacyFb as { url?: string }) : null;
              const fbUrl = lf?.url?.trim() ?? "";
              if (!fbUrl) {
                throw galleryErr instanceof Error ? galleryErr : new Error(String(galleryErr));
              }
              try {
                await refetchGallery();
              } catch {
                /* stale ids until next gallery load; legacy already persisted CSV */
              }
              setPending((current) => current.filter((item) => item.id !== slot.id));
              revokeBlob(slot.blobUrl);
              setSuccessHint(i18nKey("photos.added", { name: file.name }));
              window.setTimeout(() => setSuccessHint(null), 2800);
              void persistPrimaryPhotoUrl(fbUrl);
              continue;
            }
            if (data === "auth_redirect") {
              setBusy(false);
              if (inputRef.current) inputRef.current.value = "";
              return;
            }
            console.log("[PhotoUploader] gallery upload response", data);
            const normalized = normalizeProfileGalleryPhotos(data);
            if (normalized.urls.length === 0) {
              const message = i18nKey("photos.noUrl");
              setPending((current) =>
                current.map((item) => (item.id === slot.id ? { ...item, uploading: false, error: message } : item)),
              );
              onError(message);
              continue;
            }
            applyGalleryState(data);
            setPending((current) => current.filter((item) => item.id !== slot.id));
            revokeBlob(slot.blobUrl);
            setSuccessHint(i18nKey("photos.added", { name: file.name }));
            window.setTimeout(() => setSuccessHint(null), 2800);
            continue;
          }

          data = await uploadPhotoWithAuthRetry(file);
          if (data === "auth_redirect") {
            setBusy(false);
            if (inputRef.current) inputRef.current.value = "";
            return;
          }
          console.log("[PhotoUploader] upload response", data);
          const legacyPayload = data && typeof data === "object" ? (data as { url?: string }) : null;
          const url = legacyPayload?.url?.trim() ?? "";
          if (!url) {
            const message = i18nKey("photos.noUrl");
            setPending((current) =>
              current.map((item) => (item.id === slot.id ? { ...item, uploading: false, error: message } : item)),
            );
            onError(message);
            continue;
          }

          nextUrls = [...nextUrls, url];
          onChange(nextUrls, Math.min(nextPrimaryIndex, Math.max(0, nextUrls.length - 1)));
          setPending((current) => current.filter((item) => item.id !== slot.id));
          revokeBlob(slot.blobUrl);
          setSuccessHint(i18nKey("photos.added", { name: file.name }));
          window.setTimeout(() => setSuccessHint(null), 2800);
          void persistPrimaryPhotoUrl(url);
        } catch (errorValue: unknown) {
          if (errorValue instanceof ApiUnauthorizedError && typeof window !== "undefined") {
            dispatchAuthExpired();
            return;
          }
          const message = apiFailureToI18nText(errorValue, t, "photos.uploadFailed", formatApiError);
          setPending((current) =>
            current.map((item) => (item.id === slot.id ? { ...item, uploading: false, error: message } : item)),
          );
          onError(message);
        }
      }
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  function removePending(id: string) {
    setPending((current) => {
      const slot = current.find((item) => item.id === id);
      if (slot) revokeBlob(slot.blobUrl);
      return current.filter((item) => item.id !== id);
    });
  }

  async function removeAtGallery(index: number) {
    const pid = photoIdsByIndex?.[index];
    if (busy) return;
    setBusy(true);
    try {
      if (pid != null) {
        await apiFetch(`/profile/photos/${pid}`, {
          method: "DELETE",
          skipThrottle: true,
          skipCache: true,
          metaReason: "profile-gallery-delete",
        });
      }
      await refetchGallery();
    } catch (errorValue: unknown) {
      if (errorValue instanceof ApiUnauthorizedError && typeof window !== "undefined") {
        dispatchAuthExpired();
        return;
      }
      try {
        await refetchGallery();
      } catch {
        /* ignore */
      }
      onError(apiFailureToI18nText(errorValue, t, "photos.uploadFailed", formatApiError));
    } finally {
      setBusy(false);
    }
  }

  function removeAt(index: number) {
    if (typeof window !== "undefined" && !window.confirm(t("photos.confirmRemove"))) return;

    if (useProfileGalleryApi) {
      void removeAtGallery(index);
      return;
    }

    const next = urls.filter((_, currentIndex) => currentIndex !== index);
    let nextPrimaryIndex = primaryIndex;
    if (index === nextPrimaryIndex) nextPrimaryIndex = 0;
    else if (index < nextPrimaryIndex) nextPrimaryIndex = Math.max(0, nextPrimaryIndex - 1);
    if (next.length === 0) nextPrimaryIndex = 0;
    else nextPrimaryIndex = Math.min(nextPrimaryIndex, next.length - 1);
    onChange(next, nextPrimaryIndex);
  }

  async function applyPrimaryGallery(index: number) {
    const pid = photoIdsByIndex?.[index];
    if (pid == null || busy) {
      await refetchGallery();
      return;
    }
    setBusy(true);
    try {
      const data = await apiFetch(`/profile/photos/${pid}/primary`, {
        method: "POST",
        skipThrottle: true,
        skipCache: true,
        metaReason: "profile-gallery-primary",
      });
      applyGalleryState(data);
    } catch (errorValue: unknown) {
      if (errorValue instanceof ApiUnauthorizedError && typeof window !== "undefined") {
        dispatchAuthExpired();
        return;
      }
      onError(apiFailureToI18nText(errorValue, t, "photos.uploadFailed", formatApiError));
    } finally {
      setBusy(false);
    }
  }

  function setPrimary(index: number) {
    if (useProfileGalleryApi) {
      void applyPrimaryGallery(index);
      return;
    }
    onChange(urls, index);
  }

  function movePrimaryToFront() {
    if (urls.length === 0 || primaryIndex <= 0) return;
    if (useProfileGalleryApi) {
      void applyPrimaryGallery(primaryIndex);
      return;
    }
    const next = [...urls];
    const [main] = next.splice(primaryIndex, 1);
    next.unshift(main);
    onChange(next, 0);
  }

  const inputDisabled = disabled || busy || slotsUsed >= MAX_PHOTOS;
  const interactionsLocked = Boolean(disabled);

  function openFilePicker() {
    if (inputDisabled) return;
    const element = inputRef.current;
    if (!element) return;
    window.requestAnimationFrame(() => {
      element.click();
    });
  }

  return (
    <div className="grid" style={{ gap: 12 }}>
      {urls.length === 0 && pending.length === 0 && !interactionsLocked ? (
        <div className="photo-upload-empty" aria-hidden={false}>
          <div className="photo-upload-empty-title">{t("photos.empty.title")}</div>
          <p className="photo-upload-empty-desc">{t("photos.empty.description")}</p>
        </div>
      ) : null}

      {!interactionsLocked ? (
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <div style={{ display: "inline-block", position: "relative", touchAction: "manipulation" }}>
            <label
              htmlFor={PROFILE_PHOTO_FILE_INPUT_ID}
              style={{
                position: "absolute",
                width: 1,
                height: 1,
                padding: 0,
                margin: -1,
                overflow: "hidden",
                clip: "rect(0 0 0 0)",
                clipPath: "inset(50%)",
                border: 0,
                whiteSpace: "nowrap",
              }}
            >
              {t("photos.chooseAria")}
            </label>
            {/* Off-screen, not display:none — programmatic .click() + label[for] for mobile picker reliability. */}
            <input
              id={PROFILE_PHOTO_FILE_INPUT_ID}
              ref={inputRef}
              type="file"
              accept={ACCEPT_IMAGES}
              multiple
              tabIndex={-1}
              aria-label={t("photos.chooseAria")}
              onChange={(event) => void onFilesSelected(event.target.files)}
              style={offScreenFileInput}
            />
            <Button type="button" variant="secondary" disabled={inputDisabled} onClick={openFilePicker}>
              {busy ? t("photos.uploading") : t("photos.add")}
            </Button>
          </div>
          <span className="caption">{t("photos.caption", { used: slotsUsed, count: MAX_PHOTOS })}</span>
        </div>
      ) : null}

      {successHint ? (
        <div className="caption" style={{ color: "var(--success)", fontWeight: 600 }}>
          {resolveI18nText(successHint, t)}
        </div>
      ) : null}

      {!interactionsLocked && urls.length > 0 && primaryIndex !== 0 ? (
        <Button type="button" variant="ghost" onClick={movePrimaryToFront} disabled={busy}>
          {t("photos.makePrimaryFirst")}
        </Button>
      ) : null}

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        {urls.map((url, index) => (
          <div
            key={`${url}-${index}`}
            style={{
              position: "relative",
              width: 108,
              borderRadius: 16,
              overflow: "hidden",
              border: index === primaryIndex ? "2px solid rgba(124,92,255,0.85)" : "1px solid rgba(255,255,255,0.12)",
            }}
          >
            <SafeImg
              src={url}
              alt=""
              loading={index === primaryIndex ? "eager" : "lazy"}
              style={{ width: "100%", height: 120, objectFit: "cover", display: "block" }}
              previewUnavailableText={t("photos.previewUnavailable")}
            />
            {!interactionsLocked ? (
              <div style={{ display: "flex", gap: 4, padding: 6, flexWrap: "wrap" }}>
                <button
                  type="button"
                  className="chip"
                  style={{ cursor: "pointer", fontSize: 11 }}
                  disabled={busy}
                  onClick={() => void setPrimary(index)}
                >
                  {index === primaryIndex ? t("photos.primary") : t("photos.setPrimary")}
                </button>
                <button
                  type="button"
                  className="chip"
                  style={{ cursor: "pointer", fontSize: 11 }}
                  disabled={busy}
                  onClick={() => removeAt(index)}
                >
                  {t("photos.remove")}
                </button>
              </div>
            ) : null}
          </div>
        ))}

        {pending.map((slot) => (
          <div
            key={slot.id}
            style={{
              position: "relative",
              width: 108,
              borderRadius: 16,
              overflow: "hidden",
              border: slot.error ? "2px solid rgba(255,91,122,0.75)" : "1px dashed rgba(255,255,255,0.22)",
            }}
          >
            <SafeImg
              src={slot.blobUrl}
              alt=""
              loading="eager"
              style={{ width: "100%", height: 120, objectFit: "cover", display: "block" }}
            />
            {slot.uploading && !slot.error ? (
              <div
                style={{
                  position: "absolute",
                  inset: 0,
                  background: "rgba(0,0,0,0.45)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 11,
                  fontWeight: 700,
                  color: "#fff",
                  textAlign: "center",
                  padding: 8,
                }}
              >
                {t("photos.uploading")}
              </div>
            ) : null}
            <div style={{ padding: 6, display: "grid", gap: 4 }}>
              <div className="caption" style={{ fontSize: 10, overflow: "hidden", textOverflow: "ellipsis" }}>
                {slot.fileName}
              </div>
              {slot.error ? (
                <div className="caption" style={{ color: "var(--danger)", fontSize: 10 }}>
                  {resolveI18nText(slot.error, t)}
                </div>
              ) : null}
              {!interactionsLocked ? (
                <button
                  type="button"
                  className="chip"
                  style={{ cursor: "pointer", fontSize: 11 }}
                  disabled={slot.uploading && !slot.error}
                  onClick={() => removePending(slot.id)}
                >
                  {t("photos.remove")}
                </button>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

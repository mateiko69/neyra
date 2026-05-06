"use client";

import { resolveMediaUrl } from "../../../lib/media";
import {
  bundledDemoMainFallbackRing,
  demoCatalogFallbackMain,
  resolveDemoProfilePhoto,
} from "../../../lib/resolvePhoto";
import { SafeImg } from "../SafeImg";

type ChatAvatarProps = {
  name: string;
  src?: string | null;
  className?: string;
  alt?: string;
};

function initialForName(name: string): string {
  const clean = (name || "").trim();
  return clean ? clean.charAt(0).toUpperCase() : "?";
}

export function ChatAvatar({ name, src, className = "", alt = "" }: ChatAvatarProps) {
  const raw = src?.trim() || "";
  const likelyDemo = raw.includes("/demo-profiles/") || /(?:^|[_/])demo[_-]?\d+/i.test(raw);
  const primary = raw ? resolveMediaUrl(raw) : "";
  const demoFallback =
    raw.length > 0
      ? resolveDemoProfilePhoto({ photo_url: raw, avatar_url: raw, image_url: raw, is_demo_profile: likelyDemo }) ||
        demoCatalogFallbackMain(null)
      : demoCatalogFallbackMain(null);

  const label = alt || initialForName(name);

  return (
    <SafeImg
      className={`${className} chat-avatar chat-avatar--safe`.trim()}
      src={primary || null}
      fallbackSrc={demoFallback}
      extraFallbackSources={bundledDemoMainFallbackRing(null)}
      alt={label}
      loading="lazy"
    />
  );
}

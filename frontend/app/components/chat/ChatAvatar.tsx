"use client";

import { resolveMediaUrl } from "../../../lib/media";
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
  const resolved = raw ? resolveMediaUrl(raw) : "";
  return (
    <SafeImg
      className={resolved ? className : `${className} chat-avatar chat-avatar--fallback`.trim()}
      src={resolved || null}
      alt={alt || initialForName(name)}
      loading="lazy"
    />
  );
}

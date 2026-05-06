"use client";

import { resolveMediaUrl } from "../../../lib/media";
import { resolveDemoProfilePhoto } from "../../../lib/resolvePhoto";
import { SafeImg } from "../SafeImg";
import { useState } from "react";

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
  const resolved = raw ? resolveDemoProfilePhoto({ photo_url: raw, avatar_url: raw, image_url: raw, is_demo_profile: likelyDemo }) || resolveMediaUrl(raw) : "";
  const [imgFailed, setImgFailed] = useState(false);
  const showNativeImg = Boolean(resolved) && !imgFailed;
  return (
    showNativeImg ? (
      <img
        className={className}
        src={resolved}
        alt={alt || initialForName(name)}
        loading="lazy"
        onError={() => setImgFailed(true)}
      />
    ) : (
      <SafeImg
        className={`${className} chat-avatar chat-avatar--fallback`.trim()}
        src={null}
        alt={alt || initialForName(name)}
        loading="lazy"
      />
    )
  );
}

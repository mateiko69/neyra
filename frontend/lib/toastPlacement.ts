export type ToastPlacement = "auto" | "top-right" | "top-center" | "bottom-left" | "bottom-center";

export function resolveToastPlacement(pathname: string, placement: ToastPlacement = "auto"): Exclude<ToastPlacement, "auto"> {
  if (placement !== "auto") return placement;
  const p = String(pathname || "/");
  if (p.startsWith("/onboarding")) return "top-center";
  if (
    p === "/" ||
    p.startsWith("/login") ||
    p.startsWith("/signup") ||
    p.startsWith("/verify-email") ||
    p.startsWith("/account/restore") ||
    p.startsWith("/intro") ||
    p.startsWith("/discover") ||
    p.startsWith("/likes")
  ) {
    return "top-right";
  }
  return "bottom-left";
}

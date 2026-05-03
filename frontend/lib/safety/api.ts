import { apiFetch } from "../api";

export type ReportCategory =
  | "spam"
  | "harassment"
  | "hate"
  | "nudity"
  | "scam"
  | "impersonation"
  | "minor"
  | "other";

export async function blockUser(userId: number): Promise<void> {
  await apiFetch(`/users/${userId}/block`, { method: "POST", skipThrottle: true });
}

export async function unblockUser(userId: number): Promise<void> {
  await apiFetch(`/users/${userId}/block`, { method: "DELETE", skipThrottle: true });
}

export async function ignoreUser(userId: number): Promise<void> {
  await apiFetch(`/users/${userId}/ignore`, { method: "POST", skipThrottle: true });
}

export async function unignoreUser(userId: number): Promise<void> {
  await apiFetch(`/users/${userId}/ignore`, { method: "DELETE", skipThrottle: true });
}

export async function reportUser(userId: number, category: ReportCategory, details?: string): Promise<void> {
  const reason = details?.trim() ? `${category}: ${details.trim()}` : category;
  await apiFetch(`/users/${userId}/report`, {
    method: "POST",
    body: JSON.stringify({ reason }),
    skipThrottle: true,
  });
}

import { API_URL } from "./config/env";

function friendlyError() {
  return "Щось пішло не так. Спробуй ще раз.";
}

export async function apiFetch(path, { token, method = "GET", body } = {}) {
  if (!API_URL) throw new Error("Missing API URL");
  const url = `${API_URL}${path.startsWith("/") ? path : `/${path}`}`;

  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(url, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }

  if (!res.ok) {
    if (typeof __DEV__ !== "undefined" && __DEV__) {
      // eslint-disable-next-line no-console
      console.log("[NEYRA] API error", res.status, url, data);
    }
    throw new Error(friendlyError());
  }
  return data;
}


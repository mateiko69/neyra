import Constants from "expo-constants";

function fromExtra(key) {
  return Constants?.expoConfig?.extra?.[key] ?? Constants?.manifest?.extra?.[key];
}

export const API_URL = (fromExtra("EXPO_PUBLIC_API_URL") || process.env.EXPO_PUBLIC_API_URL || "").trim();
export const WS_URL = (fromExtra("EXPO_PUBLIC_WS_URL") || process.env.EXPO_PUBLIC_WS_URL || "").trim();

export function validateEnv() {
  const problems = [];
  if (!API_URL) problems.push("Missing EXPO_PUBLIC_API_URL");
  if (API_URL.includes("localhost") || API_URL.includes("127.0.0.1")) problems.push("API URL uses localhost (won't work on physical device)");
  if (WS_URL && (WS_URL.includes("localhost") || WS_URL.includes("127.0.0.1"))) problems.push("WS URL uses localhost (won't work on physical device)");
  return problems;
}

export function debugEnvLog() {
  if (typeof __DEV__ !== "undefined" && __DEV__) {
    // Lightweight debug output.
    // eslint-disable-next-line no-console
    console.log("[NEYRA] API_URL =", API_URL);
    // eslint-disable-next-line no-console
    console.log("[NEYRA] WS_URL  =", WS_URL);
  }
}


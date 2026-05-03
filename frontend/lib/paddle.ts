/**
 * Paddle.js v2 (CDN): single-flight script load + init; overlay checkout.
 */

const PADDLE_SCRIPT_SRC = "https://cdn.paddle.com/paddle/v2/paddle.js";

/** Monthly Premium — override via `NEXT_PUBLIC_NEYRA_PREMIUM_PRICE_ID` if needed. */
export const NEYRA_PREMIUM_PRICE_ID =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_NEYRA_PREMIUM_PRICE_ID?.trim()) ||
  "pri_01kqnycbd75d45aap2ehj4xj2x";

/** Monthly Premium+ — set `NEXT_PUBLIC_NEYRA_PREMIUM_PLUS_PRICE_ID` in production. */
export const NEYRA_PREMIUM_PLUS_PRICE_ID =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_NEYRA_PREMIUM_PLUS_PRICE_ID?.trim()) || "";

export interface PaddleCheckoutOpenOptions {
  items?: Array<{ priceId: string; quantity: number }>;
  customData?: Record<string, string | number | boolean>;
  settings?: {
    displayMode?: "overlay" | "inline" | null;
    theme?: string | null;
    locale?: string | null;
    variant?: string | null;
  };
  transactionId?: string;
  customer?: Record<string, unknown>;
}

export interface PaddleInitializeOptions {
  token: string;
  checkout?: unknown;
  pwCustomer?: { id?: string } | null;
  eventCallback?: (event: unknown) => void;
}

export interface PaddleNamespace {
  Environment?: {
    set?: (environment: "sandbox" | "production") => void;
  };
  Initialize?: (options: PaddleInitializeOptions) => void;
  Checkout?: {
    open?: (options: PaddleCheckoutOpenOptions) => void;
  };
}

declare global {
  interface Window {
    Paddle?: PaddleNamespace;
  }
}

let scriptPromise: Promise<void> | null = null;
let initInflight: Promise<boolean> | null = null;
let paddleInitialized = false;

function loadPaddleScript(): Promise<void> {
  if (typeof window === "undefined") {
    return Promise.resolve();
  }
  if (window.Paddle?.Initialize) {
    return Promise.resolve();
  }
  if (scriptPromise) {
    return scriptPromise;
  }
  scriptPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(`script[src="${PADDLE_SCRIPT_SRC}"]`);
    if (existing) {
      if (window.Paddle?.Initialize) {
        resolve();
        return;
      }
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener("error", () => reject(new Error("Paddle script failed")), { once: true });
      return;
    }
    const el = document.createElement("script");
    el.src = PADDLE_SCRIPT_SRC;
    el.async = true;
    el.onload = () => resolve();
    el.onerror = () => reject(new Error("Paddle script failed"));
    document.head.appendChild(el);
  });
  return scriptPromise;
}

/**
 * Loads CDN script once (if needed) and calls Paddle.Environment + Paddle.Initialize once per page.
 * Returns false if token missing or Paddle unavailable.
 */
export async function initPaddle(): Promise<boolean> {
  if (typeof window === "undefined") {
    return false;
  }
  if (paddleInitialized) {
    return true;
  }
  const token = (process.env.NEXT_PUBLIC_PADDLE_CLIENT_TOKEN ?? "").trim();
  if (!token) {
    return false;
  }
  if (initInflight) {
    return initInflight;
  }
  initInflight = (async (): Promise<boolean> => {
    try {
      await loadPaddleScript();
      const paddle = window.Paddle;
      if (!paddle?.Initialize) {
        return false;
      }
      paddle.Environment?.set?.("sandbox");
      paddle.Initialize({ token });
      paddleInitialized = true;
      return true;
    } catch {
      return false;
    } finally {
      initInflight = null;
    }
  })();
  return initInflight;
}

/**
 * Opens Paddle overlay checkout for a price. Safe no-op if init fails or Checkout is missing.
 */
export async function openCheckout(
  priceId: string,
  quantity: number = 1,
  extra?: { customData?: Record<string, string | number | boolean> },
): Promise<void> {
  if (typeof window === "undefined") {
    return;
  }
  const pid = String(priceId || "").trim();
  if (!pid) {
    return;
  }
  const ready = await initPaddle();
  if (!ready) {
    return;
  }
  const open = window.Paddle?.Checkout?.open;
  if (typeof open !== "function") {
    return;
  }
  try {
    const payload: PaddleCheckoutOpenOptions = {
      items: [{ priceId: pid, quantity }],
      settings: {
        displayMode: "overlay",
        theme: "light",
      },
    };
    const cd = extra?.customData;
    if (cd && typeof cd === "object" && Object.keys(cd).length > 0) {
      payload.customData = cd;
    }
    open(payload);
  } catch {
    /* Paddle threw — avoid breaking the app */
  }
}

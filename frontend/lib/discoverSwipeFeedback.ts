/**
 * Lightweight swipe feedback: haptics (mobile) and optional soft click sound.
 * Sound is off unless localStorage key `neyra:discover_swipe_sound` === "1".
 */

const SWIPE_SOUND_LS = "neyra:discover_swipe_sound";

let audioCtx: AudioContext | null = null;

function getAudioContext(): AudioContext | null {
  if (typeof window === "undefined") return null;
  try {
    const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return null;
    if (!audioCtx) audioCtx = new Ctx();
    return audioCtx;
  } catch {
    return null;
  }
}

export function isDiscoverSwipeSoundEnabled(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(SWIPE_SOUND_LS) === "1";
  } catch {
    return false;
  }
}

function playTone(freq: number, durationMs: number, gain = 0.04) {
  if (!isDiscoverSwipeSoundEnabled()) return;
  const ctx = getAudioContext();
  if (!ctx) return;
  void ctx.resume().catch(() => {});
  const osc = ctx.createOscillator();
  const g = ctx.createGain();
  osc.type = "sine";
  osc.frequency.value = freq;
  g.gain.value = 0;
  osc.connect(g);
  g.connect(ctx.destination);
  const t0 = ctx.currentTime;
  const dur = Math.max(0.02, durationMs / 1000);
  g.gain.linearRampToValueAtTime(gain, t0 + 0.01);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  osc.start(t0);
  osc.stop(t0 + dur + 0.02);
}

export function discoverSwipeHaptic(kind: "like" | "pass") {
  try {
    if (typeof navigator === "undefined" || typeof (navigator as unknown as { vibrate?: (p: number | number[]) => boolean }).vibrate !== "function") {
      return;
    }
    const v = (navigator as unknown as { vibrate: (p: number | number[]) => boolean }).vibrate;
    if (kind === "like") v([10, 28, 14]);
    else v(8);
  } catch {
    /* ignore */
  }
}

export function discoverSwipeSound(kind: "like" | "pass") {
  try {
    if (kind === "like") playTone(520, 0.09, 0.035);
    else playTone(220, 0.06, 0.028);
  } catch {
    /* ignore */
  }
}

export function discoverSwipeFeedback(kind: "like" | "pass") {
  discoverSwipeHaptic(kind);
  discoverSwipeSound(kind);
}

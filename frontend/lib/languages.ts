export function normalizeLanguageCodes(input: unknown): string[] {
  const out: string[] = [];

  const push = (v: unknown) => {
    if (typeof v !== "string") return;
    const code = v.trim().toLowerCase();
    if (!code) return;
    // Keep conservative: locale codes only (prevents {}, [object Object], etc.)
    if (!/^[a-z]{2}(-[a-z]{2})?$/.test(code)) return;
    out.push(code);
  };

  if (Array.isArray(input)) {
    for (const v of input) push(v);
  } else if (typeof input === "string") {
    for (const part of input.split(",")) push(part);
  } else if (input && typeof input === "object" && "native" in (input as any) && "additional" in (input as any)) {
    // Optional structured format: { native, additional }
    push((input as any).native);
    const add = (input as any).additional;
    if (Array.isArray(add)) for (const v of add) push(v);
    else if (typeof add === "string") for (const part of add.split(",")) push(part);
  }

  return [...new Set(out)];
}


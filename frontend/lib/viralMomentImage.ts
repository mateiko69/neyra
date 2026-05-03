export type ViralMomentImageInput = {
  /** Last message from match (may be empty for first outbound). */
  partnerMessage: string;
  /** AI suggestion text. */
  aiReply: string;
  /** What the user actually sent (may differ if edited). */
  resultText: string;
  maskedName?: string;
  /** Short labels (caller passes localized strings). */
  labels?: {
    them: string;
    ai: string;
    you: string;
  };
};

const W = 720;
const PADDING = 40;
const FOOTER_H = 72;

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, width: number, height: number, r: number) {
  const rr = Math.max(0, Math.min(r, Math.min(width / 2, height / 2)));
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.arcTo(x + width, y, x + width, y + height, rr);
  ctx.arcTo(x + width, y + height, x, y + height, rr);
  ctx.arcTo(x, y + height, x, y, rr);
  ctx.arcTo(x, y, x + width, y, rr);
  ctx.closePath();
}

function wrapWords(text: string, maxCharsPerLine: number, maxLines: number): string[] {
  const words = String(text || "")
    .trim()
    .slice(0, 420)
    .split(/\s+/)
    .filter(Boolean);
  const lines: string[] = [];
  let cur = "";
  for (const wd of words) {
    const next = cur ? `${cur} ${wd}` : wd;
    if (next.length > maxCharsPerLine && cur) {
      lines.push(cur);
      cur = wd;
      if (lines.length >= maxLines) break;
      continue;
    }
    cur = next;
  }
  if (lines.length < maxLines && cur) lines.push(cur);
  return lines.slice(0, maxLines);
}

function measureSectionHeight(lines: number): number {
  const titleLine = 28;
  const bodyLine = 30;
  const pad = 56;
  return pad + titleLine + Math.max(1, lines) * bodyLine + 18;
}

export async function generateViralMomentImage(opts: ViralMomentImageInput): Promise<{ blob: Blob; dataUrl: string }> {
  const labels = opts.labels ?? { them: "Their message", ai: "AI suggestion", you: "You sent" };
  const partnerLines = wrapWords(opts.partnerMessage || "—", 34, 5);
  const aiLines = wrapWords(opts.aiReply || "—", 34, 6);
  const resultLines = wrapWords(opts.resultText || "—", 34, 6);

  const hTop = 140;
  const h1 = measureSectionHeight(partnerLines.length);
  const h2 = measureSectionHeight(aiLines.length);
  const h3 = measureSectionHeight(resultLines.length);
  const H = hTop + h1 + h2 + h3 + FOOTER_H + 28;

  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("no_canvas");

  const g = ctx.createLinearGradient(0, 0, W, H);
  g.addColorStop(0, "#0b0b12");
  g.addColorStop(0.55, "#12122a");
  g.addColorStop(1, "#0b0b12");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);

  ctx.globalAlpha = 0.16;
  ctx.fillStyle = "#7c5cff";
  ctx.beginPath();
  ctx.ellipse(W * 0.55, H * 0.18, W * 0.62, H * 0.14, 0.15, 0, Math.PI * 2);
  ctx.fill();
  ctx.globalAlpha = 1;

  const name = (opts.maskedName || "Your match").slice(0, 28);
  ctx.fillStyle = "rgba(255,255,255,0.92)";
  ctx.font = "700 26px system-ui, -apple-system, Segoe UI, Roboto, Arial";
  ctx.fillText(`Chat with ${name}`, PADDING, 72);
  ctx.fillStyle = "rgba(255,255,255,0.48)";
  ctx.font = "600 15px system-ui, -apple-system, Segoe UI, Roboto, Arial";
  ctx.fillText("Shared moment", PADDING, 100);

  let y = hTop;

  function drawBlock(title: string, lineRows: string[], accent: "violet" | "amber" | "mint") {
    const bubbleX = PADDING;
    const bubbleW = W - PADDING * 2;
    const lineH = 30;
    const titleH = 28;
    const innerPad = 18;
    const bubbleH = innerPad * 2 + titleH + lineRows.length * lineH + 8;

    const stroke =
      accent === "amber"
        ? "rgba(255, 190, 100, 0.28)"
        : accent === "mint"
          ? "rgba(102, 227, 161, 0.22)"
          : "rgba(124, 92, 255, 0.28)";
    const fill =
      accent === "amber"
        ? "rgba(255, 190, 100, 0.07)"
        : accent === "mint"
          ? "rgba(102, 227, 161, 0.06)"
          : "rgba(124, 92, 255, 0.09)";

    ctx.fillStyle = fill;
    ctx.strokeStyle = stroke;
    ctx.lineWidth = 2;
    roundRect(ctx, bubbleX, y, bubbleW, bubbleH, 20);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = "rgba(255,255,255,0.5)";
    ctx.font = "700 13px system-ui, -apple-system, Segoe UI, Roboto, Arial";
    ctx.fillText(title.toUpperCase(), bubbleX + innerPad, y + innerPad + 12);

    ctx.fillStyle = "rgba(255,255,255,0.94)";
    ctx.font = "650 20px system-ui, -apple-system, Segoe UI, Roboto, Arial";
    let ty = y + innerPad + titleH + 10;
    for (const ln of lineRows) {
      ctx.fillText(ln, bubbleX + innerPad, ty);
      ty += lineH;
    }

    y += bubbleH + 14;
  }

  drawBlock(labels.them, partnerLines, "violet");
  drawBlock(labels.ai, aiLines, "amber");
  drawBlock(labels.you, resultLines, "mint");

  ctx.globalAlpha = 0.88;
  ctx.fillStyle = "rgba(255,255,255,0.42)";
  ctx.font = "800 17px system-ui, -apple-system, Segoe UI, Roboto, Arial";
  ctx.fillText("NEYRA AI", PADDING, H - 36);
  ctx.globalAlpha = 0.55;
  ctx.font = "600 13px system-ui, -apple-system, Segoe UI, Roboto, Arial";
  ctx.fillText("neyra.app", W - PADDING - ctx.measureText("neyra.app").width, H - 34);
  ctx.globalAlpha = 1;

  const blob: Blob = await new Promise((resolve, reject) => {
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("toBlob_failed"))), "image/png", 0.92);
  });
  const dataUrl = canvas.toDataURL("image/png");
  return { blob, dataUrl };
}

const SIZE = 32;
const CENTER = SIZE / 2;
const DOT_RADIUS = 7;
const PULSE_MAX_RADIUS = 15;

// Draws the favicon: a dot, plus (when `pulse` is set, 0..1 through the
// cycle) a ring growing out of it and fading. Returns a data URL.
export function drawDot(canvas: HTMLCanvasElement, color: string, pulse: number | null): string {
  canvas.width = SIZE;
  canvas.height = SIZE;
  const ctx = canvas.getContext("2d");
  if (!ctx) return "";
  ctx.clearRect(0, 0, SIZE, SIZE);
  ctx.fillStyle = color;

  if (pulse !== null) {
    ctx.globalAlpha = (1 - pulse) * 0.6;
    ctx.beginPath();
    ctx.arc(CENTER, CENTER, DOT_RADIUS + (PULSE_MAX_RADIUS - DOT_RADIUS) * pulse, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.globalAlpha = 1;
  ctx.beginPath();
  ctx.arc(CENTER, CENTER, DOT_RADIUS, 0, Math.PI * 2);
  ctx.fill();
  return canvas.toDataURL("image/png");
}

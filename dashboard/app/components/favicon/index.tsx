import { useEffect } from "react";

import { drawDot } from "./draw-dot";

const GREEN = "#22c55e";
const YELLOW = "#eab308";
const PULSE_PERIOD_MS = 1500;
const FRAME_MS = 100;

function iconLink(): HTMLLinkElement {
  let link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
  if (!link) {
    link = document.createElement("link");
    link.rel = "icon";
    document.head.appendChild(link);
  }
  link.type = "image/png";
  return link;
}

// Tab favicon: pulsing green dot while some paper can open positions,
// steady yellow dot otherwise. Renders nothing itself.
export function Favicon({ active }: { active: boolean }) {
  useEffect(() => {
    const canvas = document.createElement("canvas");
    const link = iconLink();
    if (!active) {
      link.href = drawDot(canvas, YELLOW, null);
      return;
    }
    const draw = () => {
      link.href = drawDot(canvas, GREEN, (Date.now() % PULSE_PERIOD_MS) / PULSE_PERIOD_MS);
    };
    draw();
    const interval = setInterval(draw, FRAME_MS);
    return () => clearInterval(interval);
  }, [active]);

  return null;
}

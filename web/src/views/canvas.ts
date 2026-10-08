// Shared drawing helpers: the two palettes, text styles and a canvas that stays sharp at any size.

/** Colors for one drawing surface. Energy, the road and the limit keep their meaning on both. */
export interface Tone {
  ink: string; // figures and marks that must read first
  label: string; // names and axis text
  rule: string; // outlines and gridlines
  vehicle: string; // a vehicle in the depot
  road: string; // a vehicle on the road
  roadFill: string;
  energy: string; // power flowing
  energyLine: string;
  energyFill: string;
  limit: string; // the site limit, and rides lost
  lostFill: string;
  shade: string; // the hours when energy costs most
}

/** The depot floor and the heartbeat: a site seen at night, where energy is the only thing that glows. */
export const STAGE: Tone = {
  ink: "#ffffff",
  label: "#a2abb9",
  rule: "#2a3a52",
  vehicle: "#e5e9f0",
  road: "#3d95ff",
  roadFill: "rgba(61, 149, 255, 0.25)",
  energy: "#00e89d",
  energyLine: "#00e89d",
  energyFill: "#00e89d",
  limit: "#ff5c5c",
  lostFill: "rgba(255, 92, 92, 0.5)",
  shade: "rgba(255, 255, 255, 0.07)",
};

/** The charts under the stage, on the white page. */
export const PAGE: Tone = {
  ink: "#050f1e",
  label: "#5d6e83",
  rule: "#e5e9f0",
  vehicle: "#050f1e",
  road: "#006fee",
  roadFill: "#dcebff",
  energy: "#00e89d",
  energyLine: "#007068", // the darker teal: mint and Waymo's #00929d marker teal both fail contrast as text on white
  energyFill: "#d2f9ec",
  limit: "#ea0000",
  lostFill: "rgba(234, 0, 0, 0.45)",
  shade: "rgba(5, 15, 30, 0.06)",
};

export const LABEL = '400 13px "Outfit", system-ui, sans-serif';
export const FIGURE = '500 15px "Outfit", system-ui, sans-serif';
export const DISPLAY = '500 40px "Outfit", system-ui, sans-serif';

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export interface Surface {
  ctx: CanvasRenderingContext2D;
  w: number;
  h: number;
}

/**
 * Size a canvas's backing store to its place on the page and return a surface in layout units.
 * The layout is `aspect` times as tall as it is wide and never narrower than `minWidth` units, so that
 * on a phone the drawing shrinks a little instead of crowding.
 */
export function surface(canvas: HTMLCanvasElement, aspect: number, minWidth: number): Surface {
  const shown = canvas.clientWidth || 800;
  const w = Math.max(shown, minWidth);
  const h = Math.round(w * aspect);
  const ratio = (window.devicePixelRatio || 1) * (shown / w);
  const width = Math.round(w * ratio);
  const height = Math.round(h * ratio);
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  const ctx = canvas.getContext("2d")!;
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, w, h);
  return { ctx, w, h };
}

/** Whether a canvas is shown at phone width, where drawings switch to a taller, simpler layout. */
export function narrow(canvas: HTMLCanvasElement): boolean {
  return (canvas.clientWidth || 800) < 560;
}

export function text(ctx: CanvasRenderingContext2D, value: string, x: number, y: number, font: string, color: string, align: CanvasTextAlign = "left"): void {
  ctx.font = font;
  ctx.fillStyle = color;
  ctx.textAlign = align;
  ctx.fillText(value, x, y);
}

/** "Tue 14:05" for a minute counted from Monday midnight. */
export function clock(minute: number): string {
  const day = DAYS[Math.floor(minute / 1440) % 7];
  const hour = Math.floor((minute % 1440) / 60);
  const min = Math.floor(minute % 60);
  return `${day} ${String(hour).padStart(2, "0")}:${String(min).padStart(2, "0")}`;
}

export function whole(value: number): string {
  return Math.round(value).toLocaleString("en-US");
}

export function percent(share: number): string {
  return Number.isFinite(share) ? `${(share * 100).toFixed(1)}%` : "n/a";
}

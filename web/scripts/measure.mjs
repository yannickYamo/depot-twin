// The measurable design laws, measured on the built site: every interactive target at least 24 by 24
// pixels, no two hit areas overlapping, no horizontal overflow, nothing unreachable above the fold, the
// settings straight under the depot at phone width, and no console errors, console warnings or uncaught
// page errors, in every place the page has (the short version, the three tabs, the further settings and each
// part under the hood, opened) at desktop and phone width. The shape is checked on the way: seven beats, one
// control and under 660 words on the short version; three tabs on the twin. Contrast is not measured here: it is asserted on
// the colour tokens by tests/laws.test.ts. Run against `vite preview`, never the dev server. Needs
// playwright: `npx playwright install chromium` once.
//   node scripts/measure.mjs http://localhost:4001/
import { chromium } from "playwright";

const url = process.argv[2] ?? "http://localhost:4001/";
const browser = await chromium.launch();
const page = await browser.newPage();
const errors = [];
page.on("console", (m) => ["error", "warning"].includes(m.type()) && errors.push(`${m.type()}: ${m.text()}`));
page.on("pageerror", (e) => errors.push(`page error: ${e}`));
let failed = false;
for (const [width, height] of [[1440, 1000], [390, 844]]) {
  await page.setViewportSize({ width, height });
  await page.goto(url);
  await page.waitForTimeout(1500);
  // Every place the page has: the short version, the three tabs, and each part under the hood opened alone.
  const hood = (part) => async () => { await page.click("#mode-hood"); await page.click(`#hood-${part} > summary`); };
  const places = [
    ["short", () => page.click("#view-short")],
    ["depot", async () => { await page.click("#view-full"); await page.click("#mode-play"); }],
    ["more settings", () => page.click("#more-settings > summary")],
    ["decisions", () => page.click("#mode-outcome")],
    ["hood", () => page.click("#mode-hood")],
    ["forecasts", hood("model")],
    ["account", hood("money")],
    ["recorded", hood("replay")],
  ];
  for (const [mode, open] of places) {
    await open();
    await page.waitForTimeout(1800);
    const shape = await page.evaluate(() => ({
      tabs: document.querySelectorAll('.modes [role="tab"]').length,
      parts: [...document.querySelectorAll(".hood-part")].filter((part) => part.open).length,
      beats: document.querySelectorAll("#brief:not([hidden]) .beat").length,
      groups: document.querySelectorAll("#brief:not([hidden]) [role=radiogroup]").length,
      words: (document.querySelector("#brief:not([hidden])")?.innerText ?? "").split(/\s+/).filter(Boolean).length,
    }));
    const wrong = mode === "short" ? shape.beats !== 7 || shape.groups !== 1 || shape.words >= 660
      : shape.tabs !== 3 || shape.parts !== (["forecasts", "account", "recorded"].includes(mode) ? 1 : 0);
    const found = await page.evaluate(() => {
      window.scrollTo(0, 0);
      const els = [...document.querySelectorAll("button, input, select, a, [role=radio], [role=tab]")].filter((e) => e.offsetParent !== null && !e.closest("[hidden]") && e.checkVisibility());
      const rects = els.map((e) => ({ id: e.id || e.textContent.trim().slice(0, 24), r: e.getBoundingClientRect() }));
      const small = rects.filter((x) => x.r.width < 24 || x.r.height < 24).map((x) => `${x.id} ${Math.round(x.r.width)}x${Math.round(x.r.height)}`);
      const overlaps = [];
      for (let i = 0; i < rects.length; i++) for (let j = i + 1; j < rects.length; j++) {
        const a = rects[i].r, b = rects[j].r;
        if (a.width && b.width && a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1) overlaps.push(`${rects[i].id} | ${rects[j].id}`);
      }
      const unreachable = [...document.querySelectorAll("h1, h2, h3, p, dt, dd, button")].filter((e) => e.offsetParent !== null && e.getBoundingClientRect().top < 0).length;
      // In one column the settings come before the vehicle list and the charts, so a slider and the floor share a screen.
      const top = (selector) => document.querySelector(selector).getBoundingClientRect().top;
      const visible = (selector) => document.querySelector(selector)?.offsetParent != null && !document.querySelector(selector).closest("[hidden]");
      const buried = innerWidth <= 1020 && visible("#controls") && !(top("#controls") > top("#floor") && top("#controls") < top("#chain-open"));
      return { targets: els.length, small, overlaps, overflow: document.documentElement.scrollWidth > innerWidth, unreachable, buried };
    });
    const bad = found.small.length || found.overlaps.length || found.overflow || found.unreachable || found.buried || wrong;
    failed ||= Boolean(bad);
    console.log(`${width}px ${mode.padEnd(13)} targets ${String(found.targets).padStart(3)}  ${bad ? "FAIL" : "ok  "}`, bad ? JSON.stringify({ ...found, shape }) : mode === "short" ? `${shape.words} words` : "");
    // A part under the hood is closed again, so the next is measured alone.
    if (shape.parts) await page.click(".hood-part[open] > summary");
  }
}
if (errors.length) { failed = true; console.log("console errors and warnings:", errors.slice(0, 5)); }
await browser.close();
process.exit(failed ? 1 : 0);

// The measurable design laws, measured on the built site: every interactive target at least 24 by 24
// pixels, no two hit areas overlapping, no horizontal overflow, nothing unreachable above the fold, and
// no console errors, in every mode at desktop and phone width. Run against `vite preview`, never the
// dev server. Needs playwright: `npx playwright install chromium` once.
//   node scripts/measure.mjs http://localhost:4001/
import { chromium } from "playwright";

const url = process.argv[2] ?? "http://localhost:4001/";
const browser = await chromium.launch();
const page = await browser.newPage();
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
let failed = false;
for (const [width, height] of [[1440, 1000], [390, 844]]) {
  await page.setViewportSize({ width, height });
  await page.goto(url);
  await page.waitForTimeout(1500);
  for (const mode of ["play", "replay", "model", "money", "story"]) {
    await page.click(`#mode-${mode}`);
    await page.waitForTimeout(1800);
    const found = await page.evaluate(() => {
      window.scrollTo(0, 0);
      const els = [...document.querySelectorAll("button, input, select, a, [role=radio], [role=tab]")].filter((e) => e.offsetParent !== null && !e.closest("[hidden]"));
      const rects = els.map((e) => ({ id: e.id || e.textContent.trim().slice(0, 24), r: e.getBoundingClientRect() }));
      const small = rects.filter((x) => x.r.width < 24 || x.r.height < 24).map((x) => `${x.id} ${Math.round(x.r.width)}x${Math.round(x.r.height)}`);
      const overlaps = [];
      for (let i = 0; i < rects.length; i++) for (let j = i + 1; j < rects.length; j++) {
        const a = rects[i].r, b = rects[j].r;
        if (a.width && b.width && a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1) overlaps.push(`${rects[i].id} | ${rects[j].id}`);
      }
      const unreachable = [...document.querySelectorAll("h1, h2, h3, p, dt, dd, button")].filter((e) => e.offsetParent !== null && e.getBoundingClientRect().top < 0).length;
      return { targets: els.length, small, overlaps, overflow: document.documentElement.scrollWidth > innerWidth, unreachable };
    });
    const bad = found.small.length || found.overlaps.length || found.overflow || found.unreachable;
    failed ||= Boolean(bad);
    console.log(`${width}px ${mode.padEnd(6)} targets ${String(found.targets).padStart(3)}  ${bad ? "FAIL" : "ok  "}`, bad ? JSON.stringify(found) : "");
  }
}
if (errors.length) { failed = true; console.log("console errors:", errors.slice(0, 5)); }
await browser.close();
process.exit(failed ? 1 : 0);

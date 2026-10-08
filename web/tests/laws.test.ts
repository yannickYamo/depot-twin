// The measurable design laws from the owner's front-end rules, asserted on the page's own tokens.
// Contrast is measured against every ground a text colour actually sits on, not against white alone.

import { describe, expect, it } from "vitest";
import { PAGE, STAGE } from "../src/views/canvas";

function luminance(hex: string): number {
  const channel = (k: number) => {
    const v = parseInt(hex.slice(1 + 2 * k, 3 + 2 * k), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(0) + 0.7152 * channel(1) + 0.0722 * channel(2);
}

export function contrast(a: string, b: string): number {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

const PAGE_GROUND = "#ffffff";
const WASH = "#f4f6f9";
const STAGE_GROUND = "#050f1e";

// Every colour that carries text, and every ground it is read on.
const TEXT_ON_GROUND: [string, string, string][] = [
  ["ink on the page", PAGE.ink, PAGE_GROUND],
  ["ink on the wash", PAGE.ink, WASH],
  ["slate labels on the page", PAGE.label, PAGE_GROUND],
  ["slate labels on the wash", PAGE.label, WASH],
  ["blue text on the page", PAGE.road, PAGE_GROUND],
  ["teal text on the page", PAGE.energyLine, PAGE_GROUND],
  ["red text on the page", PAGE.limit, PAGE_GROUND],
  ["white figures on the stage", STAGE.ink, STAGE_GROUND],
  ["stage labels on the stage", STAGE.label, STAGE_GROUND],
  ["red limit text on the stage", STAGE.limit, STAGE_GROUND],
  ["ink text on the mint play button", "#050f1e", "#00e89d"],
  ["page text on an ink pill", PAGE_GROUND, "#050f1e"],
];

describe("the measurable design laws", () => {
  for (const [name, text, ground] of TEXT_ON_GROUND) {
    it(`${name} reads at 4.5:1 or better`, () => {
      expect(contrast(text, ground)).toBeGreaterThanOrEqual(4.5);
    });
  }

  it("one accent marks energy and nothing else wears it as text", () => {
    // Mint is energy. It is never a text colour on the page, where it would fail contrast.
    expect(contrast(PAGE.energy, PAGE_GROUND)).toBeLessThan(4.5);
    expect(TEXT_ON_GROUND.some(([, text]) => text === PAGE.energy)).toBe(false);
  });
});

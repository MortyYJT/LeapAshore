import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { LINE_COLOURS } from "./overview.ts";

// The application line colours in app/globals.css, in both themes. A line is a stroke and a station
// on the workspace and in the sidebar, and its code is printed on the colour (the sidebar's 「我的申请」,
// the overview, the line maps), so each colour must read against both surfaces (WCAG 1.4.11, 3:1) and
// the code on it must read as text (WCAG 1.4.3, 4.5:1).

const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");

function block(selector: string): string {
  const start = css.indexOf(`${selector} {`);
  assert.ok(start >= 0, `globals.css has a ${selector} block`);
  return css.slice(start, css.indexOf("\n}", start));
}

function tokens(text: string): Map<string, string> {
  const out = new Map<string, string>();
  // Comments name Codex variables (`--white: ...`); drop them so only declarations are read.
  for (const [, name, value] of text.replace(/\/\*[\s\S]*?\*\//g, "").matchAll(/(--[a-z0-9-]+):\s*([^;]+);/g)) out.set(name, value.trim());
  return out;
}

const light = tokens(block(":root"));
// The dark block only overrides; anything it leaves out keeps the light value.
const dark = new Map([...light, ...tokens(block('html[data-appearance="dark"]'))]);

function rgb(value: string, name: string): [number, number, number] {
  const hex = /^#([0-9a-f]{6})$/i.exec(value);
  assert.ok(hex, `${name} is an opaque #rrggbb colour (got ${value})`);
  return [0, 2, 4].map((i) => Number.parseInt(hex[1].slice(i, i + 2), 16)) as [number, number, number];
}

function luminance([r, g, b]: [number, number, number]) {
  const linear = (v: number) => (v / 255 <= 0.04045 ? v / 255 / 12.92 : ((v / 255 + 0.055) / 1.055) ** 2.4);
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
}

function contrast(a: [number, number, number], b: [number, number, number]) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

for (const [theme, values] of [["light", light], ["dark", dark]] as const) {
  const value = (name: string) => {
    const v = values.get(name);
    assert.ok(v, `${theme}: ${name} is defined`);
    return rgb(v, `${theme} ${name}`);
  };

  test(`${theme}: every line colour reads at 3:1 against the workspace and the sidebar`, () => {
    for (const surface of ["--bg", "--rail"]) {
      for (const line of LINE_COLOURS) {
        const ratio = contrast(value(`--l-${line}`), value(surface));
        assert.ok(ratio >= 3, `${theme} --l-${line} on ${surface}: ${ratio.toFixed(2)}:1`);
      }
    }
  });

  test(`${theme}: the code printed on every line colour reads at 4.5:1`, () => {
    for (const line of LINE_COLOURS) {
      const ratio = contrast(value(`--on-l-${line}`), value(`--l-${line}`));
      assert.ok(ratio >= 4.5, `${theme} --on-l-${line} on --l-${line}: ${ratio.toFixed(2)}:1`);
    }
  });

  test(`${theme}: the eight line colours are eight different colours`, () => {
    const seen = new Set(LINE_COLOURS.map((line) => values.get(`--l-${line}`)));
    assert.equal(seen.size, LINE_COLOURS.length);
  });
}

test("every line colour has a class that sets it", () => {
  for (const line of LINE_COLOURS) {
    assert.ok(css.includes(`.line-${line} { --lc: var(--l-${line}); --on-lc: var(--on-l-${line}); }`), line);
  }
});

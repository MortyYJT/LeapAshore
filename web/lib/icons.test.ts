import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { inflateSync } from "node:zlib";

// The icon files scripts/make-icons.cjs writes from app/icon.svg. These tests read the committed
// bitmaps, so they fail when icon.svg or the script changes and the script was not rerun.

// The light theme's rail and ink (app/globals.css), and the dark theme's ink.
const RAIL = [0xf6, 0xf6, 0xf6] as const;
const RAIL_INK = [0x1a, 0x1c, 0x1f] as const;
const DARK_INK = [0xdf, 0xdf, 0xdf] as const;
const WHITE = [255, 255, 255] as const;
const NEAR_BLACK = [0x0b, 0x0c, 0x0e] as const;
// The greys of Chrome's light tab strip and dark selected tab, the nearest in tone to a mid ink.
const LIGHT_STRIP = [0xde, 0xe1, 0xe6] as const;
const DARK_TAB = [0x35, 0x36, 0x3a] as const;

type Rgb = readonly [number, number, number];
type Bitmap = { width: number; height: number; at: (x: number, y: number) => [number, number, number, number] };

/**
 * Decode an 8-bit RGB or RGBA PNG without interlacing, which is what the generator's screenshots are:
 * Chromium writes RGB when no pixel is transparent.
 */
function decode(png: Buffer): Bitmap {
  assert.equal(png.toString("latin1", 1, 4), "PNG");
  const width = png.readUInt32BE(16);
  const height = png.readUInt32BE(20);
  assert.deepEqual([png[24], png[28]], [8, 0], "8 bits per channel, not interlaced");
  assert.ok(png[25] === 2 || png[25] === 6, "RGB or RGBA");
  const channels = png[25] === 6 ? 4 : 3;
  const data: Buffer[] = [];
  for (let at = 8; at < png.length; ) {
    const length = png.readUInt32BE(at);
    if (png.toString("latin1", at + 4, at + 8) === "IDAT") data.push(png.subarray(at + 8, at + 8 + length));
    at += 12 + length;
  }
  const raw = inflateSync(Buffer.concat(data));
  const stride = width * channels;
  const out = Buffer.alloc(stride * height);
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)];
    for (let i = 0; i < stride; i++) {
      const value = raw[y * (stride + 1) + 1 + i];
      const left = i >= channels ? out[y * stride + i - channels] : 0;
      const up = y > 0 ? out[(y - 1) * stride + i] : 0;
      const corner = i >= channels && y > 0 ? out[(y - 1) * stride + i - channels] : 0;
      let predicted = 0;
      if (filter === 1) predicted = left;
      else if (filter === 2) predicted = up;
      else if (filter === 3) predicted = (left + up) >> 1;
      else if (filter === 4) {
        const p = left + up - corner;
        const [a, b, c] = [Math.abs(p - left), Math.abs(p - up), Math.abs(p - corner)];
        predicted = a <= b && a <= c ? left : b <= c ? up : corner;
      }
      out[y * stride + i] = (value + predicted) & 255;
    }
  }
  return {
    width,
    height,
    at: (x, y) => {
      const i = (y * width + x) * channels;
      return [out[i], out[i + 1], out[i + 2], channels === 4 ? out[i + 3] : 255];
    },
  };
}

function pixels(bitmap: Bitmap) {
  const all: { x: number; y: number; rgba: [number, number, number, number] }[] = [];
  for (let y = 0; y < bitmap.height; y++) for (let x = 0; x < bitmap.width; x++) all.push({ x, y, rgba: bitmap.at(x, y) });
  return all;
}

const corners = (bitmap: Bitmap) =>
  [[0, 0], [bitmap.width - 1, 0], [0, bitmap.height - 1], [bitmap.width - 1, bitmap.height - 1]].map(([x, y]) => bitmap.at(x, y));

function luminance([r, g, b]: Rgb) {
  const linear = (v: number) => (v / 255 <= 0.04045 ? v / 255 / 12.92 : ((v / 255 + 0.055) / 1.055) ** 2.4);
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
}

function contrast(a: Rgb, b: Rgb) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const near = (a: readonly number[], b: readonly number[], tolerance = 3) => a.slice(0, 3).every((v, i) => Math.abs(v - b[i]) <= tolerance);

const asset = (path: string) => readFileSync(new URL(path, import.meta.url));

/** The images inside an ICO file whose entries are PNGs. */
function icoEntries(ico: Buffer) {
  assert.deepEqual([ico.readUInt16LE(0), ico.readUInt16LE(2)], [0, 1], "an icon file");
  return Array.from({ length: ico.readUInt16LE(4) }, (_, i) => {
    const entry = 6 + 16 * i;
    const [length, offset] = [ico.readUInt32LE(entry + 8), ico.readUInt32LE(entry + 12)];
    return { size: ico[entry], bitmap: decode(ico.subarray(offset, offset + length)) };
  });
}

/** A bitmap with no plate: clear corners, mostly clear, and one ink that reads on light and dark surfaces. */
function assertTransparentMark(bitmap: Bitmap, name: string) {
  for (const corner of corners(bitmap)) assert.equal(corner[3], 0, `${name}: a corner is transparent`);
  const all = pixels(bitmap);
  const solid = all.filter((p) => p.rgba[3] === 255);
  const clear = all.filter((p) => p.rgba[3] === 0);
  assert.ok(clear.length > all.length / 2, `${name}: more than half the picture is transparent`);
  assert.ok(solid.length > 0, `${name}: the mark has fully opaque pixels`);
  const ink = solid[0].rgba.slice(0, 3) as unknown as Rgb;
  for (const p of solid) assert.ok(near(p.rgba, ink), `${name}: one ink`);
  // WCAG 1.4.11 asks 3:1 of a graphic against what is next to it.
  for (const [surface, colour] of Object.entries({ white: WHITE, "near-black": NEAR_BLACK, "a light tab strip": LIGHT_STRIP, "a dark tab": DARK_TAB })) {
    assert.ok(contrast(ink, colour) >= 3, `${name}: reads on ${surface} (${contrast(ink, colour).toFixed(2)})`);
  }
  return { solid: solid.length, total: all.length };
}

test("icon.svg has no plate and switches its ink with the colour scheme", () => {
  const svg = asset("../app/icon.svg").toString("utf8");
  assert.doesNotMatch(svg, /<rect/);
  assert.match(svg, /stroke:\s*#1a1c1f/);
  assert.match(svg, /@media\s*\(prefers-color-scheme:\s*dark\)\s*\{[^}]*stroke:\s*#dfdfdf/);
  assert.ok(contrast(RAIL_INK, WHITE) >= 4.5 && contrast(DARK_INK, NEAR_BLACK) >= 4.5);
  assert.ok(contrast(RAIL_INK, RAIL) >= 4.5, "the plated icons' mark reads on its ground");
});

test("favicon.ico holds 16, 32 and 48 px images with a transparent ground", () => {
  const entries = icoEntries(asset("../app/favicon.ico"));
  assert.deepEqual(entries.map((entry) => entry.size), [16, 32, 48]);
  for (const { size, bitmap } of entries) {
    assert.deepEqual([bitmap.width, bitmap.height], [size, size]);
    const { solid } = assertTransparentMark(bitmap, `favicon ${size}`);
    // A stroke thinner than a pixel leaves no fully opaque pixel at all. At 16 px the three strokes
    // (leap, ground line, station) should each keep a solid core.
    if (size === 16) assert.ok(solid >= 16, `favicon 16: ${solid} solid pixels`);
  }
});

test("the manifest's any-purpose icons are transparent", () => {
  for (const size of [192, 512]) {
    const bitmap = decode(asset(`../public/icons/icon-${size}.png`));
    assert.deepEqual([bitmap.width, bitmap.height], [size, size]);
    assertTransparentMark(bitmap, `icon-${size}`);
  }
});

test("maskable icons keep a full-bleed ground and the mark inside the safe circle", () => {
  for (const size of [192, 512]) {
    const bitmap = decode(asset(`../public/icons/maskable-${size}.png`));
    const all = pixels(bitmap);
    assert.ok(all.every((p) => p.rgba[3] === 255), `maskable-${size}: fully opaque`);
    for (const corner of corners(bitmap)) assert.ok(near(corner, RAIL), `maskable-${size}: the ground reaches the corner`);
    // A launcher may cut everything outside the circle of 80% diameter.
    const centre = (size - 1) / 2;
    const outside = all.filter((p) => Math.hypot(p.x - centre, p.y - centre) > size * 0.4);
    assert.ok(outside.every((p) => near(p.rgba, RAIL)), `maskable-${size}: nothing but ground outside the safe circle`);
    assert.ok(all.some((p) => near(p.rgba, RAIL_INK)), `maskable-${size}: the mark is drawn`);
  }
});

test("the Apple touch icon is opaque, because iOS paints transparent pixels black", () => {
  const bitmap = decode(asset("../app/apple-icon.png"));
  assert.deepEqual([bitmap.width, bitmap.height], [180, 180]);
  const all = pixels(bitmap);
  assert.ok(all.every((p) => p.rgba[3] === 255));
  for (const corner of corners(bitmap)) assert.ok(near(corner, RAIL));
  assert.ok(all.some((p) => near(p.rgba, RAIL_INK)));
});

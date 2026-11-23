// Derive the bitmap icons from web/app/icon.svg, the one hand-drawn source.
//
// icon.svg has no ground. A browser that takes an SVG tab icon gets that file as it is, and its ink
// follows the colour scheme. A bitmap cannot do that, so the files below come in two kinds.
//
// Transparent, in one ink that reads on white and on near-black (MID: 4.0:1 on white, 4.9:1 on
// near-black, and 3.0:1 on the greys of a light and a dark tab strip, which lie between them):
//   web/app/favicon.ico (16, 32 and 48 px), for browsers that do not take an SVG;
//   web/public/icons/icon-192.png and icon-512.png, the manifest's `purpose: any` icons.
// A dark ink disappears on a dark taskbar and a light one on a white page. A light outline around a
// dark ink (or the reverse) reads at 192 px and turns to a smudge at 16 px. A saturated blue reads
// well and is ruled out because the product keeps saturated colours for program lines.
//
// Opaque, ink on the rail colour (the light sidebar grey), the mark at its drawn size so it keeps a margin:
//   web/app/apple-icon.png (180 px): iOS does not support transparency in a home-screen icon and
//     fills it with black, and it cuts the corners itself, so the ground is a full square;
//   web/public/icons/maskable-192.png and maskable-512.png: a launcher cuts a maskable icon to its
//     own shape and only the circle of 80% diameter in the middle is sure to survive, so the ground
//     runs to the edges and the mark is drawn at 0.8 scale (its farthest stroke ends 36% of the
//     width from the centre).
//
// Rerun after editing icon.svg: node scripts/make-icons.cjs
// web/lib/icons.test.ts reads the files this writes.

const fs = require("fs");
const path = require("path");

const { chromium } = require("./playwright.cjs");

const APP = path.resolve(__dirname, "..", "web", "app");
const INSTALL = path.resolve(__dirname, "..", "web", "public", "icons");

async function render(browser, svg, size) {
  const page = await browser.newPage({ viewport: { width: size, height: size }, deviceScaleFactor: 1 });
  const uri = `data:image/svg+xml;base64,${Buffer.from(svg).toString("base64")}`;
  await page.setContent(`<body style="margin:0"><img src="${uri}" width="${size}" height="${size}" style="display:block"></body>`);
  const png = await page.screenshot({ omitBackground: true });
  await page.close();
  return png;
}

/** An ICO file whose entries are PNG images, which every current browser reads. */
function ico(images) {
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(images.length, 4);
  const entries = [];
  let offset = 6 + 16 * images.length;
  for (const { size, png } of images) {
    const entry = Buffer.alloc(16);
    entry.writeUInt8(size >= 256 ? 0 : size, 0);
    entry.writeUInt8(size >= 256 ? 0 : size, 1);
    entry.writeUInt16LE(1, 4); // colour planes
    entry.writeUInt16LE(32, 6); // bits per pixel
    entry.writeUInt32LE(png.length, 8);
    entry.writeUInt32LE(offset, 12);
    entries.push(entry);
    offset += png.length;
  }
  return Buffer.concat([header, ...entries, ...images.map((i) => i.png)]);
}

// The light theme's rail and ink (app/globals.css, --rail and --ink).
const RAIL = "#f6f6f6";
const RAIL_INK = "#1a1c1f";
const MID = "#6c80a1";
// Where the mark sat on the 32-unit plate before the tab icon lost its ground.
const ON_PLATE = "translate(2 1.6)";

/** The mark's shapes and stroke attributes, taken from icon.svg so the geometry has one source. */
function readMark(svg) {
  const group = svg.match(/<g transform="([^"]*)"([^>]*)>([\s\S]*?)<\/g>/);
  if (!group) throw new Error("icon.svg: the mark's <g transform> was not found");
  return { fit: group[1], attributes: group[2], shapes: group[3] };
}

function compose({ attributes, shapes }, { transform, ink, ground }) {
  const plate = ground ? `<rect width="32" height="32" fill="${ground}"/>` : "";
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">${plate}` +
    `<g transform="${transform}" stroke="${ink}"${attributes}>${shapes}</g></svg>`
  );
}

(async () => {
  const mark = readMark(fs.readFileSync(path.join(APP, "icon.svg"), "utf8"));
  const clear = compose(mark, { transform: mark.fit, ink: MID });
  const plated = compose(mark, { transform: ON_PLATE, ink: RAIL_INK, ground: RAIL });
  const maskable = compose(mark, {
    transform: `translate(16 16) scale(0.8) translate(-16 -16) ${ON_PLATE}`,
    ink: RAIL_INK,
    ground: RAIL,
  });
  const browser = await chromium.launch();
  try {
    const images = [];
    for (const size of [16, 32, 48]) images.push({ size, png: await render(browser, clear, size) });
    fs.writeFileSync(path.join(APP, "favicon.ico"), ico(images));
    fs.writeFileSync(path.join(APP, "apple-icon.png"), await render(browser, plated, 180));
    fs.mkdirSync(INSTALL, { recursive: true });
    for (const size of [192, 512]) {
      fs.writeFileSync(path.join(INSTALL, `icon-${size}.png`), await render(browser, clear, size));
      fs.writeFileSync(path.join(INSTALL, `maskable-${size}.png`), await render(browser, maskable, size));
    }
  } finally {
    await browser.close();
  }
  console.log("wrote web/app/favicon.ico, web/app/apple-icon.png and web/public/icons/*.png");
})();

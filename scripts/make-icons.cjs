// Derive the bitmap icons from web/app/icon.svg, the one hand-drawn source.
//
// Next.js serves files with these names from web/app/ as the site's icons: icon.svg for browsers that take
// an SVG, favicon.ico (16, 32 and 48 px) for those that do not, and apple-icon.png (180 px) for an iOS home
// screen. The Apple icon is drawn without the rounded corners, because iOS cuts its own and a transparent
// corner would show black.
//
// The web app manifest (web/app/manifest.ts) lists four more, written to web/public/icons/: 192 and 512 px
// with the rounded corners, and the same two sizes as maskable icons. A maskable icon is cut to whatever
// shape the launcher uses, and only the circle of 80% diameter in the middle is sure to survive, so there
// the ground runs to the edges and the mark is drawn at 0.8 scale: its farthest stroke ends 36% of the
// width from the centre.
//
// Rerun after editing icon.svg: node scripts/make-icons.cjs

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

(async () => {
  const svg = fs.readFileSync(path.join(APP, "icon.svg"), "utf8");
  const browser = await chromium.launch();
  try {
    const sizes = [16, 32, 48];
    const images = [];
    for (const size of sizes) images.push({ size, png: await render(browser, svg, size) });
    fs.writeFileSync(path.join(APP, "favicon.ico"), ico(images));
    const square = svg.replace(/<rect([^>]*?) rx="[^"]*"/, "<rect$1");
    fs.writeFileSync(path.join(APP, "apple-icon.png"), await render(browser, square, 180));
    const maskable = square.replace(/<g transform="/, '<g transform="translate(16 16) scale(0.8) translate(-16 -16) ');
    if (maskable === square) throw new Error("icon.svg: the mark's <g transform> was not found");
    fs.mkdirSync(INSTALL, { recursive: true });
    for (const size of [192, 512]) {
      fs.writeFileSync(path.join(INSTALL, `icon-${size}.png`), await render(browser, svg, size));
      fs.writeFileSync(path.join(INSTALL, `maskable-${size}.png`), await render(browser, maskable, size));
    }
  } finally {
    await browser.close();
  }
  console.log("wrote web/app/favicon.ico, web/app/apple-icon.png and web/public/icons/*.png");
})();

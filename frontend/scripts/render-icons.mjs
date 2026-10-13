// Renders the PNG app icons and the link-preview image from public/favicon.svg.
// Run after changing the logo colours: CHROMIUM_PATH=/path/to/chrome node scripts/render-icons.mjs
import { chromium } from 'playwright-core';
import { readFileSync } from 'node:fs';
const out = new URL('../public/', import.meta.url).pathname;
const svg = readFileSync(out + 'favicon.svg', 'utf8');
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const page = await browser.newPage();
for (const [name, size, pad] of [['apple-touch-icon.png', 180, 0], ['icon-192.png', 192, 0], ['icon-512.png', 512, 0], ['og-image.png', 0, 0]]) {
  if (name === 'og-image.png') {
    await page.setViewportSize({ width: 1200, height: 630 });
    await page.setContent(`<html><body style="margin:0;width:1200px;height:630px;display:grid;place-items:center;background:radial-gradient(70% 60% at 50% 20%,#fff,rgba(255,255,255,0) 70%),linear-gradient(160deg,#f5f6fd,#e8eaf8);font-family:Georgia,serif"><div style="display:flex;align-items:center;gap:44px"><div style="width:200px;height:200px">${svg.replace('<svg ', '<svg width="200" height="200" ')}</div><div><div style="font-size:120px;font-weight:600;letter-spacing:.08em;color:#3b2f9a">KEEL</div><div style="font:500 22px system-ui,sans-serif;letter-spacing:.32em;color:#5d63a8;margin-top:8px">INTELLIGENCE. IN CONTROL.</div></div></div></body></html>`);
    await page.screenshot({ path: out + name });
    continue;
  }
  await page.setViewportSize({ width: size, height: size });
  // iOS rounds the corners itself, so the touch icon is a full square tile.
  const body = name === 'apple-touch-icon.png' ? svg.replace(/rx="15"/g, 'rx="0"') : svg;
  await page.setContent(`<html><body style="margin:0;background:transparent">${body.replace('<svg ', `<svg width="${size}" height="${size}" `)}</body></html>`);
  await page.screenshot({ path: out + name, omitBackground: true, clip: { x: 0, y: 0, width: size, height: size } });
}
await browser.close();
console.log('ok');

import { chromium } from './node_modules/playwright/index.mjs';
const browser = await chromium.launch();
const page = await browser.newPage();
await page.setViewportSize({ width: 1280, height: 900 });
// First get the fund list to find a live fund BLE
const resp = await page.goto('http://localhost:8000/api/funds', { waitUntil: 'networkidle' });
const body = await page.content();
// extract first live fund id
const match = body.match(/"fund_id":"([^"]+)".*?"synthetic_static":false/);
console.log('BODY_SNIPPET:' + body.substring(0, 500));
await browser.close();

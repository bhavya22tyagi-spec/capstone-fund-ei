import { chromium } from './node_modules/playwright/index.mjs';
const browser = await chromium.launch();
const page = await browser.newPage();
await page.setViewportSize({ width: 1280, height: 900 });
await page.goto('http://localhost:5173/bles/b0001001-b000-0000-0000-000000000001', { waitUntil: 'networkidle', timeout: 15000 });
await page.screenshot({ path: 'C:/Users/drago/AppData/Local/Temp/ble_drilldown.png' });
await browser.close();

import { chromium } from './node_modules/playwright/index.mjs';
const browser = await chromium.launch();
const page = await browser.newPage();
await page.setViewportSize({ width: 1280, height: 800 });
await page.goto('http://localhost:5173', { waitUntil: 'networkidle', timeout: 15000 });
await page.screenshot({ path: 'C:/Users/drago/AppData/Local/Temp/screenshot_5173.png' });
console.log('TITLE:' + await page.title());
await browser.close();

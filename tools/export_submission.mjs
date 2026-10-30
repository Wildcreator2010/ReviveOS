import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const source = path.join(root, 'docs/ReviveOS-作品介绍.html');
const output = path.join(root, 'docs/ReviveOS-作品介绍.pdf');
const scratch = path.join(root, '.scratch');
const preview = path.join(scratch, 'submission-preview');
const browser = process.env.EDGE_BIN ?? [process.env['PROGRAMFILES(X86)'], process.env.PROGRAMFILES, process.env.LOCALAPPDATA]
  .filter(Boolean).map(dir => path.join(dir, 'Microsoft/Edge/Application/msedge.exe')).find(existsSync);
assert(browser, 'Edge is required; set EDGE_BIN to an existing executable.');
assert(existsSync(source), 'Submission HTML is missing.');
await mkdir(scratch, { recursive: true });
await mkdir(preview, { recursive: true });
const profile = await mkdtemp(path.join(scratch, 'submission-edge-'));
const child = spawn(browser, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  `--user-data-dir=${profile}`, '--remote-debugging-port=0', 'about:blank'], { stdio: ['ignore', 'ignore', 'pipe'] });
let socket;
let nextId = 0;
const pending = new Map();
function call(method, params = {}, sessionId) {
  const id = ++nextId;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`Timed out: ${method}`)); }, 30000);
    pending.set(id, { resolve, reject, timer });
    socket.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
  });
}
try {
  const endpoint = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Browser startup timed out.')), 30000);
    let buffer = '';
    child.once('error', error => { clearTimeout(timer); reject(error); });
    child.once('exit', code => { clearTimeout(timer); reject(new Error(`Browser exited: ${code}`)); });
    child.stderr.on('data', chunk => {
      buffer += chunk.toString();
      const match = buffer.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (match) { clearTimeout(timer); resolve(match[1]); }
    });
  });
  socket = new WebSocket(endpoint);
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true });
    socket.addEventListener('error', reject, { once: true });
  });
  socket.addEventListener('message', event => {
    const response = JSON.parse(String(event.data));
    const item = pending.get(response.id);
    if (!item) return;
    clearTimeout(item.timer);
    pending.delete(response.id);
    if (response.error) item.reject(new Error(JSON.stringify(response.error)));
    else item.resolve(response.result);
  });
  const { targetId } = await call('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await call('Target.attachToTarget', { targetId, flatten: true });
  const page = (method, params = {}) => call(method, params, sessionId);
  await page('Page.enable');
  await page('Emulation.setDeviceMetricsOverride', { width: 1000, height: 1300, deviceScaleFactor: 1, mobile: false });
  await page('Page.navigate', { url: pathToFileURL(source).href });
  const evaluated = await page('Runtime.evaluate', { awaitPromise: true, returnByValue: true, expression: `
    (async () => {
      if (document.readyState !== 'complete') await new Promise(resolve => window.addEventListener('load', resolve, {once:true}));
      await document.fonts.ready;
      await Promise.all([...document.images].map(image => image.decode()));
      return [...document.querySelectorAll('.page')].map((element, index) => {
        const rect = element.getBoundingClientRect();
        const footer = element.querySelector('.foot').getBoundingClientRect();
        const children = [...element.children].filter(item => !item.classList.contains('foot'));
        const bottom = Math.max(...children.map(item => item.getBoundingClientRect().bottom));
        const overflow = [...element.querySelectorAll('*')].some(item => {
          const bounds = item.getBoundingClientRect();
          return bounds.right > rect.right + 1 || bounds.left < rect.left - 1;
        });
        return { page: index + 1, gap: footer.top - bottom, overflow,
          clip: { x: rect.x + scrollX, y: rect.y + scrollY, width: rect.width, height: rect.height, scale: 1 } };
      });
    })()` });
  assert(!evaluated.exceptionDetails, JSON.stringify(evaluated.exceptionDetails));
  const pages = evaluated.result.value;
  assert.equal(pages.length, 7, 'Expected seven document pages.');
  for (const item of pages) {
    const screenshot = await page('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, clip: item.clip });
    await writeFile(path.join(preview, `page-${item.page}.png`), Buffer.from(screenshot.data, 'base64'));
  }
  await writeFile(path.join(preview, 'layout.json'), JSON.stringify(pages, null, 2));
  assert(pages.every(item => item.gap >= 8 && !item.overflow), `Page content overflow: ${JSON.stringify(pages)}`);
  const pdf = await page('Page.printToPDF', { printBackground: true, preferCSSPageSize: true, displayHeaderFooter: false });
  const bytes = Buffer.from(pdf.data, 'base64');
  assert(bytes.subarray(0, 5).toString() === '%PDF-');
  assert.equal([...bytes.toString('latin1').matchAll(/\/Type\s*\/Page\b/g)].length, 7, 'PDF page count mismatch.');
  await writeFile(output, bytes);
  assert.equal((await readFile(output)).length, bytes.length);
  console.log(JSON.stringify({ pdf: output, bytes: bytes.length, pages: pages.length, minimumFooterGap: Math.min(...pages.map(item => item.gap)), preview }, null, 2));
} finally {
  if (socket?.readyState === WebSocket.OPEN) {
    await call('Browser.close').catch(() => {});
    socket.close();
  }
  for (const item of pending.values()) clearTimeout(item.timer);
  if (child.exitCode === null) await new Promise(resolve => {
    const timer = setTimeout(resolve, 5000);
    child.once('exit', () => { clearTimeout(timer); resolve(); });
  });
  if (child.exitCode !== null) await rm(profile, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 }).catch(() => {});
}

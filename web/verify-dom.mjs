// Headless DOM verification of App.jsx using jsdom + esbuild, used in
// environments where the Playwright Chromium system libraries cannot be
// installed.  Renders the real component, submits the four request
// shapes against the running API, and asserts the table/SVG share the
// single global witness, legacy shapes are untouched, and 422 clears
// stale results.
//
// Requires the API on 127.0.0.1:8000 (uvicorn app.main:app from ../api).
import { JSDOM } from 'jsdom';
import * as esbuild from 'esbuild';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { writeFileSync, mkdtempSync, rmSync } from 'node:fs';
import { join, dirname } from 'node:path';

const webRoot = dirname(fileURLToPath(import.meta.url));

const apiUp = await new Promise((resolve) => {
  import('node:http').then(({ request }) => {
    const req = request(
      { hostname: '127.0.0.1', port: 8000, path: '/health' },
      (res) => {
        res.resume();
        resolve(res.statusCode === 200);
      },
    );
    req.on('error', () => resolve(false));
    req.end();
  });
});
if (!apiUp) {
  console.error(
    'verify-dom.mjs needs the API at http://127.0.0.1:8000 — start it with:\n' +
      '  (cd ../api && python3 -m uvicorn app.main:app --port 8000)',
  );
  process.exit(2);
}

const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', {
  url: 'http://127.0.0.1:5173/',
  pretendToBeVisual: true,
});
globalThis.window = dom.window;
globalThis.document = dom.window.document;
globalThis.navigator = dom.window.navigator;
globalThis.HTMLElement = dom.window.HTMLElement;
globalThis.SVGElement = dom.window.SVGElement;
globalThis.Element = dom.window.Element;
globalThis.Node = dom.window.Node;
globalThis.Event = dom.window.Event;
globalThis.MouseEvent = dom.window.MouseEvent;
globalThis.requestAnimationFrame = (cb) => setTimeout(cb, 0);
globalThis.cancelAnimationFrame = (id) => clearTimeout(id);
globalThis.fetch = (url, init) =>
  import('node:http').then(({ request }) => {
    const body = init?.body;
    return new Promise((resolve, reject) => {
      const req = request(
        {
          hostname: '127.0.0.1',
          port: 8000,
          path: url,
          method: init?.method ?? 'GET',
          headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
        },
        (res) => {
          let data = '';
          res.on('data', (chunk) => (data += chunk));
          res.on('end', () =>
            resolve({
              status: res.statusCode,
              ok: res.statusCode >= 200 && res.statusCode < 300,
              json: async () => JSON.parse(data),
              text: async () => data,
            }),
          );
        },
      );
      req.on('error', reject);
      if (body) req.write(body);
      req.end();
    });
  });

const dir = mkdtempSync(join(webRoot, 'node_modules', '.app-bundle-'));
const entry = join(dir, 'entry.jsx');
const outfile = join(dir, 'app.js');
writeFileSync(
  entry,
  [
    `export { default as App } from ${JSON.stringify(join(webRoot, 'src', 'App.jsx'))};`,
    "export { createRoot } from 'react-dom/client';",
    "export { default as React } from 'react';",
  ].join('\n'),
);
const buildResult = await esbuild.build({
  entryPoints: [entry],
  bundle: true,
  format: 'esm',
  jsx: 'automatic',
  loader: { '.js': 'jsx' },
  outfile,
  define: { 'process.env.NODE_ENV': '"production"' },
});
const { App, createRoot, React } = await import(pathToFileURL(outfile).href);
process.on('exit', () => rmSync(dir, { recursive: true, force: true }));

const container = document.getElementById('root');
const root = createRoot(container);
// React 18's createRoot.render has no completion callback (the second
// parameter is an internal flag); flush through the scheduler instead.
root.render(React.createElement(App));
await new Promise((r) => setTimeout(r, 30));

const text = (sel) => document.querySelector(sel)?.textContent ?? '';
const count = (sel) => document.querySelectorAll(sel).length;

function fillJson(payload) {
  const ta = document.querySelector('#json-input');
  const setter = Object.getOwnPropertyDescriptor(
    dom.window.HTMLTextAreaElement.prototype,
    'value',
  ).set;
  setter.call(ta, JSON.stringify(payload));
  ta.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
}

async function submit() {
  document.querySelector('button[type=submit]').click();
  for (let i = 0; i < 50; i++) {
    await new Promise((r) => setTimeout(r, 30));
    if (count('.error') || count('[data-testid=result-panel]')) break;
  }
}

function selectMode(nameFragment) {
  const radios = [...document.querySelectorAll('input[name=mode]')];
  const label = [...document.querySelectorAll('.mode-switch label')].find((l) =>
    l.textContent.includes(nameFragment),
  );
  label.querySelector('input').click();
}

let failures = 0;
function check(name, cond) {
  console.log(`${cond ? 'PASS' : 'FAIL'}  ${name}`);
  if (!cond) failures++;
}

// 1. Legacy tolerance: minimal shape, no segment table.
selectMode('阈值模式');
fillJson({
  tolerance: 5,
  points: [0, 5, 0, 5, 0, 5, 0].map((v, i) => ({ time: i, value: v })),
});
await submit();
check('legacy threshold renders result', count('[data-testid=result-panel]') === 1);
check('legacy threshold has no segment table', count('[data-testid=segment-table]') === 0);
check('legacy threshold summary', text('.summary').includes('tolerance = 5'));

// 2. Legacy budget: 5-col table, integer witness shape.
selectMode('段数预算模式');
fillJson({
  budget: 2,
  points: [
    { time: 0, value: 0 }, { time: 1, value: 0 }, { time: 2, value: 1 },
    { time: 3, value: 0 }, { time: 4, value: 1 }, { time: 5, value: 0 },
    { time: 6, value: 0 },
  ],
});
await submit();
check('legacy budget max error 3/4', text('[data-testid=max-error]') === '3/4');
check('legacy budget table has 5 columns', count('[data-testid=segment-table] thead th') === 5);
check('legacy budget one worst row', count('tr.worst-row') === 1);
check('legacy budget no direction column / banner',
  count('[data-testid=global-witness]') === 0);
check('legacy budget red markers', count('svg g.marker-worst') === 1);
const worstRowText = document.querySelector('tr.worst-row').textContent;
check('worst row shows index 3', worstRowText.includes('3'));

// 3. Directed budget: shared witness index 4 below, 6 columns.
fillJson({
  budget: 2,
  directed_error: { above: 2, below: 5 },
  points: [
    { time: 0, value: 0 }, { time: 1, value: 0 }, { time: 2, value: 1 },
    { time: 3, value: 0 }, { time: 4, value: -1 }, { time: 5, value: 0 },
    { time: 6, value: 0 },
  ],
});
await submit();
check('directed budget multiplier 3/10', text('[data-testid=max-error]') === '3/10');
check('directed budget 6 columns', count('[data-testid=segment-table] thead th') === 6);
const banner = text('[data-testid=global-witness]');
check('banner names index 4', banner.includes('下标 4'));
check('banner says below', banner.includes('插值线下方'));
check('directed budget single worst row', count('tr.worst-row') === 1);
const dWorstRow = document.querySelector('tr.worst-row').textContent;
check('worst row index 4', dWorstRow.includes('4') && dWorstRow.includes('插值线下方'));
// the red SVG marker's label contains the same index
const redLabel = document.querySelector('svg g.marker-worst .error-index').textContent;
check('red marker labels witness 4', redLabel.startsWith('4'));
check('below glyph attached', redLabel.includes('▼'));
check('exactly one red marker', count('svg g.marker-worst') === 1);
check('one orange marker', count('svg g.marker-segment') === 1);

// 4. Directed threshold: adjudicates, direction column present.
selectMode('阈值模式');
fillJson({
  directed_error: { above: 5, below: 5 },
  points: [0, 5, 0, 5, 0].map((v, i) => ({ time: i, value: v })),
});
await submit();
check('directed threshold renders', count('[data-testid=result-panel]') === 1);
check('directed threshold multiplier 1', text('[data-testid=max-error]') === '1');
check('directed threshold table 6 cols', count('[data-testid=segment-table] thead th') === 6);
check('directed threshold banner shows above glyph text',
  text('[data-testid=global-witness]').includes('插值线上方'));

// 5. tolerance + directed_error together -> 422, panel cleared.
fillJson({
  tolerance: 5,
  directed_error: { above: 5, below: 5 },
  points: [0, 5, 0].map((v, i) => ({ time: i, value: v })),
});
await submit();
check('both modes -> 422 error shown', text('.error').includes('422'));
check('422 clears stale panel', count('[data-testid=result-panel]') === 0);

// 6. non-positive bound -> 422
fillJson({
  directed_error: { above: 0, below: 5 },
  points: [0, 5, 0].map((v, i) => ({ time: i, value: v })),
});
await submit();
check('zero bound -> 422', text('.error').includes('422'));

// 7. editing after a good directed result clears the conclusion.
selectMode('阈值模式');
fillJson({
  directed_error: { above: 5, below: 5 },
  points: [0, 5, 0, 5, 0].map((v, i) => ({ time: i, value: v })),
});
await submit();
check('panel back before edit', count('[data-testid=result-panel]') === 1);
{
  const ta = document.querySelector('#json-input');
  const setter = Object.getOwnPropertyDescriptor(
    dom.window.HTMLTextAreaElement.prototype,
    'value',
  ).set;
  setter.call(ta, ta.value + ' ');
  ta.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
}
check('editing clears panel', count('[data-testid=result-panel]') === 0);

console.log(failures ? `\n${failures} FAILURE(S)` : '\nALL DOM CHECKS PASSED');
process.exit(failures ? 1 : 0);

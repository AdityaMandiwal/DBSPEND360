// Phase 2 browser pass (plan §2.1/§2.2/§2.3).
// Drives the running dev UI headlessly to verify:
//   2.1 no React "unique key" warning on the Job Clusters table
//   2.2 no duplicate-key warning when expanding pipelines
//   2.3 LLM analysis renders as sanitized markdown (no raw HTML / no XSS)
// Saves screenshots under claude_scripts/shots/.

import { chromium } from 'playwright';
import { mkdirSync } from 'fs';

const BASE = 'http://localhost:5173';
const SHOTS = new URL('./shots/', import.meta.url).pathname;
mkdirSync(SHOTS, { recursive: true });

const consoleMsgs = [];
const keyWarnings = [];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function record(msg) {
  const t = msg.type();
  const text = msg.text();
  consoleMsgs.push(`[${t}] ${text}`);
  if (/unique "?key"?|two children with the same key|same key/i.test(text)) {
    keyWarnings.push(text);
  }
}

const run = async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on('console', record);
  page.on('pageerror', (e) => consoleMsgs.push(`[pageerror] ${e.message}`));

  // --- XSS interception (plan §2.3): rewrite every analyze response so the
  // "analysis" field carries a hostile payload. If AnalysisMarkdown is safe,
  // window.__xss must stay undefined and the markdown still renders.
  const XSS = [
    '## Cost Heading',
    '',
    'This is **bold** and a bullet:',
    '',
    '- item one',
    '',
    'Raw HTML attempt: <img src=x onerror="window.__xss=1"> and',
    '<script>window.__xss=1</script> should NOT execute.',
  ].join('\n');

  // Fulfill analyze requests directly (the real LLM call is slow / costs money,
  // and we only need to prove the renderer sanitizes the text).
  await page.route('**/analyze**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        analysis: XSS,
        timestamp: new Date().toISOString(),
        cluster_id: 'test',
        pipeline_id: 'test',
        pool_id: 'test',
        job_id: 'test',
      }),
    });
  });

  const log = (s) => console.log(s);

  const closeDialogs = async () => {
    for (let i = 0; i < 4; i++) {
      if (!(await page.locator('[role="dialog"]').count())) return;
      const closeBtn = page.locator('[role="dialog"] button[aria-label*="close" i], [role="dialog"] button:has-text("Close")');
      if (await closeBtn.count()) await closeBtn.first().click().catch(() => {});
      else await page.keyboard.press('Escape').catch(() => {});
      await sleep(600);
    }
  };

  log('navigating to app...');
  await page.goto(BASE, { waitUntil: 'networkidle', timeout: 60000 });
  await sleep(2500);
  await page.screenshot({ path: SHOTS + '01-job-clusters.png', fullPage: false });

  // ---- 2.1 Job Clusters: expand a row + change sort, watch for key warnings.
  log('Job Clusters: expanding first job row...');
  const jobExpanders = page.locator('table tbody tr button').filter({ has: page.locator('svg') });
  if (await jobExpanders.count()) {
    await jobExpanders.first().click().catch(() => {});
    await sleep(1500);
  }
  // click a sortable header to re-sort the current page
  const sortHeader = page.getByRole('button', { name: /total|cost/i }).first();
  if (await sortHeader.count()) {
    await sortHeader.click().catch(() => {});
    await sleep(1200);
  }
  await page.screenshot({ path: SHOTS + '02-job-expanded-sorted.png' });
  await closeDialogs();

  // ---- Pipeline Compute tab (2.2 + 2.3 main check) ----
  log('switching to Pipeline Compute...');
  await page.getByRole('tab', { name: 'Pipeline Compute' }).click();
  // wait for the pipeline table to actually populate before counting expanders
  await page
    .getByRole('button', { name: /expand pipeline/i })
    .first()
    .waitFor({ timeout: 30000 })
    .catch(() => log('  (no expand-pipeline button appeared in 30s)'));
  await sleep(1500);
  await page.screenshot({ path: SHOTS + '04-pipelines.png' });

  // Open the pipeline details modal FIRST (before expanding) so layout is stable.
  log('Pipelines: opening pipeline details modal (XSS-injected analysis)...');
  const pName = page.locator('table tbody button.text-left').first();
  log(`  pipeline-name buttons: ${await page.locator('table tbody button.text-left').count()}`);
  await pName.scrollIntoViewIfNeeded().catch(() => {});
  await pName.click().catch((e) => log('  name click failed: ' + e.message));
  await page
    .locator('[role="dialog"]')
    .first()
    .waitFor({ timeout: 15000 })
    .catch(() => log('  (dialog did not appear)'));
  // analysis is gated behind details resolving; give the markdown time to render
  await page
    .locator('[role="dialog"] [class*="prose"]')
    .first()
    .waitFor({ timeout: 20000 })
    .catch(() => log('  (analysis prose did not render)'));
  await sleep(1500);
  log(`  dialogs open: ${await page.locator('[role="dialog"]').count()}`);
  const dlgText = await page
    .locator('[role="dialog"]')
    .first()
    .innerText()
    .catch(() => '');
  log('  dialog text (first 200): ' + dlgText.replace(/\n/g, ' ').slice(0, 200));
  await page.screenshot({ path: SHOTS + '06-pipeline-modal-xss.png', fullPage: false });

  // Run XSS/markdown assertions while the dialog is open.
  const assert = {
    xssFired: await page.evaluate(() => window.__xss === 1),
    hasStrong: await page.locator('[role="dialog"] strong').count(),
    hasHeading: await page.locator('[role="dialog"] h1, [role="dialog"] h2').count(),
    rawImgOnerror: await page.locator('img[onerror]').count(),
    literalShown: /window\.__xss=1|onerror=|<script>/i.test(dlgText),
  };
  log(`  [modal-open assert] ${JSON.stringify(assert)}`);

  await closeDialogs();

  // ---- now exercise 2.2: expand many pipeline rows, watch for dup-key warnings
  log('Pipelines: expanding all visible pipeline rows...');
  const pExp = page.getByRole('button', { name: /expand pipeline/i });
  const n = await pExp.count();
  log(`  found ${n} pipeline expanders`);
  for (let i = 0; i < Math.min(n, 8); i++) {
    await pExp.nth(i).click().catch(() => {});
    await sleep(300);
  }
  await sleep(1500);
  await page.screenshot({ path: SHOTS + '05-pipelines-expanded.png', fullPage: true });

  const { xssFired, hasStrong, hasHeading, rawImgOnerror, literalShown: literalScriptShown } = assert;

  await browser.close();

  // ---- report ----
  console.log('\n================ PHASE 2 BROWSER PASS REPORT ================');
  console.log('Console messages captured:', consoleMsgs.length);
  console.log('React key warnings       :', keyWarnings.length);
  keyWarnings.forEach((w) => console.log('   !! ', w.slice(0, 200)));
  console.log('--- 2.3 XSS / markdown ---');
  console.log('window.__xss fired (BAD if true):', xssFired);
  console.log('<img onerror> in DOM (BAD if >0):', rawImgOnerror);
  console.log('<strong> rendered (good if >0)  :', hasStrong);
  console.log('<h1/h2> rendered (good if >0)   :', hasHeading);
  console.log('raw HTML shown as literal text  :', literalScriptShown);
  console.log('--- error-type console lines (first 15) ---');
  consoleMsgs
    .filter((m) => /\[error\]|\[warning\]|\[pageerror\]/.test(m))
    .slice(0, 15)
    .forEach((m) => console.log('   ', m.slice(0, 200)));
  const pass =
    keyWarnings.length === 0 && xssFired === false && rawImgOnerror === 0 && hasStrong > 0;
  console.log('\nOVERALL:', pass ? 'PASS ✅' : 'NEEDS REVIEW ❌');
  console.log('Screenshots in:', SHOTS);
  process.exit(0);
};

run().catch((e) => {
  console.error('SCRIPT ERROR:', e);
  process.exit(1);
});

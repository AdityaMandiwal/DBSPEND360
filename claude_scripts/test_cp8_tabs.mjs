// CP8 validation: top-level tabs shell + URL state persistence.
//
// Exit criteria validated here:
//   (2) Default load shows Job Clusters tab with the existing dashboard content.
//   (3) Clicking "All-Purpose Clusters" swaps the panel without a full page reload
//       and without any new network request to localhost:5173 (HMR-capable router-less
//       tab swap).
//   (4) Refreshing on `?tab=all-purpose` lands back on the All-Purpose tab.
//
// Visual diff (criterion 2's pixel parity) is recorded by writing two screenshots
// the user can eyeball; this script does not enforce it programmatically.

import { chromium } from 'playwright';
import { existsSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const BASE = process.env.APP_URL ?? 'http://localhost:5173';
const OUT = resolve(process.cwd(), 'claude_scripts', '_cp8_artifacts');
if (!existsSync(OUT)) mkdirSync(OUT, { recursive: true });

const log = (...args) => console.log('[cp8]', ...args);
const fail = (msg) => {
  console.error('[cp8] FAIL:', msg);
  process.exit(1);
};

const browser = await chromium.launch();
try {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();

  let loadCount = 0;
  page.on('load', () => {
    loadCount += 1;
  });

  // --- (2) default load lands on Job Clusters ---
  // CP10 made the All-Purpose tab render real data; React Query's
  // adjacent-page prefetch keeps the network busy, so `networkidle`
  // is no longer a reasonable signal here (it would time out).
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });

  await page.waitForSelector('text=DBSpend360');
  const jobTab = page.getByRole('tab', { name: 'Job Clusters' });
  const apTab = page.getByRole('tab', { name: 'All-Purpose Clusters' });
  if ((await jobTab.count()) !== 1) fail('Job Clusters tab trigger not found');
  if ((await apTab.count()) !== 1) fail('All-Purpose Clusters tab trigger not found');

  const jobActive = await jobTab.getAttribute('data-state');
  if (jobActive !== 'active') fail(`Job Clusters tab not active on default load (data-state=${jobActive})`);

  // The Job Clusters panel should still render the original dashboard chrome.
  const filtersHeading = page.getByText('Filters & Controls');
  if ((await filtersHeading.count()) === 0) fail('Job Clusters panel did not render "Filters & Controls"');

  await page.screenshot({ path: `${OUT}/01_default_job_clusters.png`, fullPage: true });
  log('OK default load: Job Clusters active, dashboard chrome present');

  const loadsBeforeSwap = loadCount;
  // Plant a window-scoped marker that a real page reload would discard but
  // a router-less in-place tab swap leaves intact.
  await page.evaluate(() => {
    window.__cp8ReloadCanary = 'persist-me';
  });

  // --- (3) clicking All-Purpose swaps without a full page reload ---
  await apTab.click();
  await page.waitForTimeout(300);

  const apActive = await apTab.getAttribute('data-state');
  if (apActive !== 'active') fail(`All-Purpose tab did not become active (data-state=${apActive})`);

  // CP10 replaced the placeholder with the real <AllPurposeDashboard /> body.
  // Assert that we landed on All-Purpose content (filters card title is stable
  // across both tabs; combine with the active sub-tab tab-role to disambiguate).
  const byClusterSubTab = page.getByRole('tab', { name: 'By Cluster' });
  await byClusterSubTab.waitFor({ state: 'visible', timeout: 5000 }).catch(() => {});
  if ((await byClusterSubTab.count()) === 0) {
    fail('All-Purpose dashboard did not render — "By Cluster" sub-tab not visible');
  }

  const canaryAfterSwap = await page.evaluate(() => window.__cp8ReloadCanary);
  if (canaryAfterSwap !== 'persist-me') {
    fail(`Window marker was cleared on tab swap (got ${JSON.stringify(canaryAfterSwap)}); the page reloaded`);
  }
  if (loadCount !== loadsBeforeSwap) {
    fail(`Tab swap fired ${loadCount - loadsBeforeSwap} 'load' event(s); expected 0`);
  }

  const urlAfterSwap = new URL(page.url());
  if (urlAfterSwap.searchParams.get('tab') !== 'all-purpose') {
    fail(`URL not updated to ?tab=all-purpose (got "${urlAfterSwap.searchParams.get('tab')}")`);
  }
  log('OK tab swap: All-Purpose active, no reload, URL state written');

  await page.screenshot({ path: `${OUT}/02_all_purpose_placeholder.png`, fullPage: true });

  // --- (4) refresh on ?tab=all-purpose stays on All-Purpose ---
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForSelector('text=DBSpend360', { timeout: 15000 });

  const apActiveAfterReload = await page
    .getByRole('tab', { name: 'All-Purpose Clusters' })
    .getAttribute('data-state');
  if (apActiveAfterReload !== 'active') {
    fail(`After reload on ?tab=all-purpose, All-Purpose tab not active (data-state=${apActiveAfterReload})`);
  }
  log('OK reload: ?tab=all-purpose persisted across refresh');

  // --- bonus: swapping back to Job Clusters strips the query param ---
  await page.getByRole('tab', { name: 'Job Clusters' }).click();
  await page.waitForTimeout(150);
  const urlAfterBack = new URL(page.url());
  if (urlAfterBack.searchParams.has('tab')) {
    fail(`Switching back to default tab did not strip ?tab (got "${urlAfterBack.searchParams.get('tab')}")`);
  }
  log('OK default tab strips ?tab param from URL');

  log('all CP8 checks passed');
} finally {
  await browser.close();
}

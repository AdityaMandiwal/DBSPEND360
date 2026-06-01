// CP10 validation: All-Purpose tab end-to-end UI.
//
// Walks the acceptance criteria from plan §8 / CP10 against a running
// dev frontend (default `http://localhost:5173`, backed by the local
// FastAPI on `:8000`):
//
//   (1) Open app → click "All-Purpose Clusters" → summary cards render
//       with non-zero values.
//   (2) "By Cluster" sub-tab — expand first row → daily breakdown rows
//       appear; data_security_mode badges render ("Dedicated" / "Shared"
//       / "Legacy" / "Unknown").
//   (3) "By User" sub-tab — expand first row → per-cluster rows appear.
//   (4) Click a cluster name → cluster details modal opens with the LLM
//       analysis card visible.
//   (5) Sub-tab URL state persists across refresh.
//   (6) No JS console errors on the page.
//
// The script does NOT enforce a particular workspace's data shape —
// instead it gates the assertions on whether the backend returned any
// rows for the default 30-day window, and only fails if rows exist but
// the UI didn't render them.

import { chromium } from 'playwright';
import { existsSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const BASE = process.env.APP_URL ?? 'http://localhost:5173';
const OUT = resolve(process.cwd(), 'claude_scripts', '_cp10_artifacts');
if (!existsSync(OUT)) mkdirSync(OUT, { recursive: true });

const log = (...args) => console.log('[cp10]', ...args);
const fail = (msg) => {
  console.error('[cp10] FAIL:', msg);
  process.exit(1);
};
const warn = (...args) => console.warn('[cp10] WARN:', ...args);

const browser = await chromium.launch();
try {
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  const page = await ctx.newPage();

  const consoleErrors = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      // Some 3rd-party network errors slip in via fetch (e.g. dev-only
      // requests); only count React/component-level errors as fatal.
      const text = msg.text();
      if (/(react|Warning:|TypeError|ReferenceError)/i.test(text)) {
        consoleErrors.push(text);
      }
    }
  });
  page.on('pageerror', (err) => consoleErrors.push(String(err)));

  // --- (1) summary cards ---
  // Use `domcontentloaded` rather than `networkidle`: React Query's
  // adjacent-page prefetch keeps the network ~constantly busy, so
  // `networkidle` would time out even on a healthy page.
  await page.goto(`${BASE}?tab=all-purpose`, { waitUntil: 'domcontentloaded' });
  // Vite's first-request bundle can be slow on cold start; the dashboard
  // also mounts a handful of React Query subscribers that all fire at once,
  // so give the page a generous 30s to surface its title.
  await page.waitForSelector('text=DBSpend360', { timeout: 30000 });

  const apTab = page.getByRole('tab', { name: 'All-Purpose Clusters' });
  if ((await apTab.getAttribute('data-state')) !== 'active') {
    fail('All-Purpose tab not active after navigating to ?tab=all-purpose');
  }

  // Wait for summary cards to populate (KPI strip). "Total Spend" is the
  // title that renders before the value; we wait for it (which proves the
  // dashboard mounted), then wait for the data to resolve by polling
  // either a $ value or the empty state.
  await page
    .getByText('Total Spend', { exact: true })
    .first()
    .waitFor({ state: 'visible', timeout: 30000 })
    .catch(() => fail('"Total Spend" card title never appeared'));

  // Poll up to 30s for the values to populate. The /summary endpoint can
  // take ~5–10s on a real workspace.
  const dataResolved = await page
    .waitForFunction(
      () => {
        const text = document.body.innerText;
        return (
          /\$\d/.test(text) ||
          text.includes('No all-purpose data available')
        );
      },
      undefined,
      { timeout: 30000 },
    )
    .then(() => true)
    .catch(() => false);
  if (!dataResolved) {
    fail('Summary cards never resolved (no value, no empty state) — likely API not reachable');
  }

  const hasEmptyState =
    (await page.getByText('No all-purpose data available').count()) > 0;
  if (hasEmptyState) {
    warn(
      'Backend returned no all-purpose data for the default 30-day window — ' +
        'skipping data-dependent checks (3, 4). The tab UI itself rendered fine.',
    );
  } else {
    const totalSpendCard = page.getByText('Total Spend', { exact: true });
    if ((await totalSpendCard.count()) === 0) fail('"Total Spend" card missing');

    const activeClustersCard = page.getByText('Active Clusters', { exact: true });
    if ((await activeClustersCard.count()) === 0) fail('"Active Clusters" card missing');

    const activeUsersCard = page.getByText('Active Users', { exact: true });
    if ((await activeUsersCard.count()) === 0) fail('"Active Users" card missing');

    log('OK summary cards rendered (Total Spend / Active Clusters / Active Users)');
  }

  await page.screenshot({ path: `${OUT}/01_all_purpose_summary.png`, fullPage: true });

  // --- (2) By Cluster sub-tab ---
  const byClusterTab = page.getByRole('tab', { name: 'By Cluster' });
  if ((await byClusterTab.count()) === 0) fail('"By Cluster" sub-tab missing');
  await byClusterTab.click();
  await page.waitForTimeout(500);

  // Wait for either the By Cluster table content or empty state. The
  // /grouped-by-cluster endpoint can take ~10s on a real workspace.
  await Promise.race([
    page.waitForSelector('button[aria-label="Expand row"]', { timeout: 30000 }),
    page.waitForSelector(
      'text=No all-purpose clusters found for the selected filters.',
      { timeout: 30000 },
    ),
  ]).catch(() => fail('By Cluster table never resolved (no rows, no empty state)'));

  const noClusters =
    (await page
      .getByText('No all-purpose clusters found for the selected filters.')
      .count()) > 0;

  if (!noClusters && !hasEmptyState) {

    // Verify at least one attribution badge is rendered. The badge text is
    // one of "Dedicated" / "Shared" / "Legacy" / "Unknown".
    const badgeText = await page
      .locator('text=/^(Dedicated|Shared|Legacy|Unknown)$/')
      .first()
      .textContent()
      .catch(() => null);
    if (!badgeText) {
      fail('No data_security_mode badge rendered on the By Cluster table');
    }
    log(`OK By Cluster: attribution badge rendered (e.g. "${badgeText}")`);

    // Expand first row and verify daily breakdown appears.
    const firstExpander = page.locator('button[aria-label="Expand row"]').first();
    await firstExpander.click();
    await page.waitForTimeout(500);

    const dailyHeading = page.getByText(/Daily breakdown \(/);
    if ((await dailyHeading.count()) === 0) {
      fail('Daily breakdown panel did not appear after expanding first cluster');
    }
    log('OK By Cluster: expanding first row showed daily breakdown');

    await page.screenshot({
      path: `${OUT}/02_by_cluster_expanded.png`,
      fullPage: true,
    });

    // --- (4) Click first cluster name → details modal opens ---
    // Cluster name cell is the first `<button>` with title starting "View details for".
    const detailsTrigger = page.locator('button[title^="View details for"]').first();
    await detailsTrigger.click();

    // Modal renders "Cluster Configuration & Analysis" as the dialog title.
    const modalTitle = page.getByText('Cluster Configuration & Analysis');
    await modalTitle.waitFor({ state: 'visible', timeout: 10000 }).catch(() => {
      fail('Cluster details modal did not open');
    });

    // The Cluster Configuration section + AI Cluster Analysis card both
    // render only after the details API call resolves (skeleton until
    // then). Wait for either the analysis card title or the details
    // skeleton to settle.
    await page
      .getByText('AI Cluster Analysis')
      .first()
      .waitFor({ state: 'visible', timeout: 20000 })
      .catch(() => fail('"AI Cluster Analysis" card never rendered in modal'));
    log('OK cluster details modal opens with AI analysis card');

    await page.screenshot({
      path: `${OUT}/03_cluster_details_modal.png`,
      fullPage: true,
    });

    // Close the modal (Escape key works on Radix Dialog). Wait for the
    // dialog title to detach so the next click doesn't race with the
    // close animation.
    await page.keyboard.press('Escape');
    await page
      .getByText('Cluster Configuration & Analysis')
      .waitFor({ state: 'detached', timeout: 5000 })
      .catch(() => {});
  } else {
    warn('No clusters found in the default window — skipping expand + modal checks');
  }

  // --- (3) By User sub-tab ---
  const byUserTab = page.getByRole('tab', { name: 'By User' });
  if ((await byUserTab.count()) === 0) fail('"By User" sub-tab missing');
  await byUserTab.click();
  await page.waitForTimeout(500);

  // Wait for either the By User table content (a row's expand button) or
  // the explicit empty state to appear. The /grouped-by-user endpoint can
  // take ~10s on a real workspace, so the timeout is generous.
  await Promise.race([
    page.waitForSelector('button[aria-label="Expand row"]', { timeout: 30000 }),
    page.waitForSelector('text=No users found for the selected filters.', {
      timeout: 30000,
    }),
  ]).catch(() => fail('By User table never resolved (no rows, no empty state)'));

  const noUsers =
    (await page.getByText('No users found for the selected filters.').count()) > 0;

  if (!noUsers && !hasEmptyState) {

    const firstUserExpander = page
      .locator('button[aria-label="Expand row"]')
      .first();
    await firstUserExpander.click();

    // The expansion is instant (the per-cluster array is already in the
    // page's React state); but the click can race with React rendering,
    // so wait briefly for either the populated heading or the empty
    // fallback. Both prove the panel mounted.
    await Promise.race([
      page
        .getByText(/Clusters owned \(/)
        .first()
        .waitFor({ state: 'visible', timeout: 5000 }),
      page
        .getByText('No cluster breakdown returned for this user.')
        .first()
        .waitFor({ state: 'visible', timeout: 5000 }),
    ]).catch(async () => {
      // Snapshot before failing so we can see the actual state.
      await page.screenshot({
        path: `${OUT}/04b_by_user_expand_fail.png`,
        fullPage: true,
      });
      fail(
        '"Clusters owned" panel did not appear after expanding first user. ' +
          'See _cp10_artifacts/04b_by_user_expand_fail.png',
      );
    });
    log('OK By User: expanding first row showed per-cluster breakdown');

    await page.screenshot({
      path: `${OUT}/04_by_user_expanded.png`,
      fullPage: true,
    });
  } else {
    warn('No users found in the default window — skipping by-user expand check');
  }

  // --- (5) sub-tab URL state persists ---
  const urlBeforeReload = new URL(page.url());
  if (urlBeforeReload.searchParams.get('subtab') !== 'by-user') {
    fail(
      `After clicking "By User" sub-tab, expected ?subtab=by-user, got ` +
        `${urlBeforeReload.searchParams.get('subtab')}`,
    );
  }
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForSelector('text=DBSpend360', { timeout: 15000 });
  const subTabActive = await page
    .getByRole('tab', { name: 'By User' })
    .getAttribute('data-state');
  if (subTabActive !== 'active') {
    fail(`Reloaded on ?subtab=by-user but By User tab not active (state=${subTabActive})`);
  }
  log('OK ?subtab=by-user persists across refresh');

  // --- (6) console errors ---
  if (consoleErrors.length > 0) {
    console.error('[cp10] console errors encountered:');
    consoleErrors.forEach((e) => console.error('  -', e));
    fail(`${consoleErrors.length} console error(s) on page`);
  }
  log('OK no console errors on page');

  log('all CP10 checks passed');
} finally {
  await browser.close();
}

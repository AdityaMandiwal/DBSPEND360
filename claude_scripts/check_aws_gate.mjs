#!/usr/bin/env node
/**
 * CP9 — AWS-gate CI regression guard (plan §4.0(c), D16).
 *
 * Mechanically enforces the two invariants that keep the AWS honesty gate from
 * silently regressing (the MAJOR-1 root cause: an Nth render path that decides
 * segmentation by data shape, or hard-wires the config-derived cloud label):
 *
 *   Rule A — no data-shape segmentation gate.
 *     A `*compute_cost (!=|==|!==|===) null` expression may NOT drive a render
 *     branch. The segmented-vs-2-slice decision must flow through the positive
 *     allowlist (`isSegmentedPlatform`). Allowed forms:
 *       - `const X = ...compute_cost != null` ONLY when paired with
 *         `X && isSegmentedPlatform` (or `isSegmentedPlatform && X`) — the
 *         blessed `hasSegmented`/`showSegmented` pattern from §4.0(b).
 *       - a `...compute_cost != null` null-safe cell formatter that lives inside
 *         an `{isSegmentedPlatform && ( ... )}` guarded JSX region.
 *     Everything else (a bare data-shape render gate) fails the build.
 *
 *   Rule B — no config-derived cloud label in the AWS branch.
 *     `compute_service` / `compute_display_name` must not appear in the
 *     consequent (AWS-true) branch of an `isAws ? ... : ...` ternary. The AWS
 *     branch must use the single `AWS_CLOUD_LABEL` const. Non-AWS branches may
 *     still reference the config labels.
 *
 * Scope: the six gated components only (plan §4.0(c)).
 *
 * Usage:
 *   node claude_scripts/check_aws_gate.mjs            # check the real files
 *   node claude_scripts/check_aws_gate.mjs --self-test # prove red/green logic
 *
 * Exit code 0 = clean, 1 = violations (or self-test mismatch).
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(__dirname, '..');

const GATED_FILES = [
  'client/src/components/GroupedJobTable.tsx',
  'client/src/components/SummaryCards.tsx',
  'client/src/components/JobBreakdownModal.tsx',
  'client/src/components/AllPurposeSummaryCards.tsx',
  'client/src/components/AllPurposeClustersTable.tsx',
  'client/src/components/AllPurposeUsersTable.tsx',
];

const RE_COMPUTE_NULL = /compute_cost\s*(?:!==|===|!=|==)\s*null/g;
const RE_SEG_REGION = /isSegmentedPlatform\s*&&\s*\(/g;
const RE_AWS_LABEL = /isAws\s*\?\s*[^:]*?compute_(?:service|display_name)/g;

/**
 * Return a same-length copy of `src` with comments and string/template *literal
 * text* replaced by spaces (newlines preserved). Template `${...}` expression
 * code is kept verbatim so labels embedded in templates are still analysed.
 * After this pass, paren/brace counting and token searches ignore strings and
 * comments, so we never false-positive on a `compute_service` in a comment or a
 * `(` inside JSX text.
 */
function blankNonCode(src) {
  const n = src.length;
  const out = src.split('');
  const blankRange = (a, b) => {
    for (let k = a; k < b && k < n; k++) if (out[k] !== '\n') out[k] = ' ';
  };
  let i = 0;
  while (i < n) {
    const c = src[i];
    const d = i + 1 < n ? src[i + 1] : '';
    if (c === '/' && d === '/') {
      let j = i + 2;
      while (j < n && src[j] !== '\n') j++;
      blankRange(i, j);
      i = j;
      continue;
    }
    if (c === '/' && d === '*') {
      let j = i + 2;
      while (j < n && !(src[j] === '*' && src[j + 1] === '/')) j++;
      j = Math.min(n, j + 2);
      blankRange(i, j);
      i = j;
      continue;
    }
    if (c === '"' || c === "'") {
      let j = i + 1;
      while (j < n && src[j] !== c && src[j] !== '\n') {
        if (src[j] === '\\') {
          j += 2;
          continue;
        }
        j++;
      }
      blankRange(i + 1, j);
      i = src[j] === c ? j + 1 : j;
      continue;
    }
    if (c === '`') {
      let j = i + 1;
      while (j < n) {
        if (src[j] === '\\') {
          blankRange(j, j + 2);
          j += 2;
          continue;
        }
        if (src[j] === '`') {
          j++;
          break;
        }
        if (src[j] === '$' && src[j + 1] === '{') {
          // Keep the ${...} expression verbatim; skip to its matching brace.
          j += 2;
          let depth = 1;
          while (j < n && depth > 0) {
            if (src[j] === '{') depth++;
            else if (src[j] === '}') depth--;
            j++;
          }
          continue;
        }
        if (src[j] !== '\n') out[j] = ' ';
        j++;
      }
      i = j;
      continue;
    }
    i++;
  }
  return out.join('');
}

function makeLineLookup(src) {
  const starts = [0];
  for (let k = 0; k < src.length; k++) {
    if (src[k] === '\n') starts.push(k + 1);
  }
  return (idx) => {
    // binary search for the greatest start <= idx
    let lo = 0;
    let hi = starts.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (starts[mid] <= idx) lo = mid;
      else hi = mid - 1;
    }
    return lo + 1; // 1-based line number
  };
}

function computeSegRegions(blanked) {
  const regions = [];
  RE_SEG_REGION.lastIndex = 0;
  let m;
  while ((m = RE_SEG_REGION.exec(blanked)) !== null) {
    const open = m.index + m[0].length - 1; // index of the '('
    let depth = 0;
    let k = open;
    for (; k < blanked.length; k++) {
      if (blanked[k] === '(') depth++;
      else if (blanked[k] === ')') {
        depth--;
        if (depth === 0) {
          k++;
          break;
        }
      }
    }
    regions.push([open, k]);
  }
  return regions;
}

function analyzeSource(label, raw) {
  const blanked = blankNonCode(raw);
  const lineAt = makeLineLookup(raw);
  const rawLines = raw.split('\n');
  const regions = computeSegRegions(blanked);
  const inRegion = (idx) => regions.some(([a, b]) => idx >= a && idx < b);
  const violations = [];

  // Rule A — data-shape segmentation gate.
  RE_COMPUTE_NULL.lastIndex = 0;
  let m;
  while ((m = RE_COMPUTE_NULL.exec(blanked)) !== null) {
    const idx = m.index;
    const line = lineAt(idx);
    const rawLine = rawLines[line - 1] ?? '';

    const assign = rawLine.match(/\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=/);
    let safe = false;
    if (assign) {
      const v = assign[1];
      const paired = new RegExp(
        `(\\b${v}\\b\\s*&&\\s*isSegmentedPlatform|isSegmentedPlatform\\s*&&\\s*\\b${v}\\b)`
      );
      if (paired.test(blanked)) safe = true;
    }
    if (!safe && rawLine.includes('isSegmentedPlatform')) safe = true;
    if (!safe && inRegion(idx)) safe = true;

    if (!safe) {
      violations.push({
        rule: 'A (data-shape segmentation gate)',
        line,
        text: rawLine.trim(),
      });
    }
  }

  // Rule B — config-derived cloud label inside the AWS-true branch.
  RE_AWS_LABEL.lastIndex = 0;
  while ((m = RE_AWS_LABEL.exec(blanked)) !== null) {
    const line = lineAt(m.index);
    violations.push({
      rule: 'B (config label in AWS branch)',
      line,
      text: (rawLines[line - 1] ?? '').trim(),
    });
  }

  return violations.map((v) => ({ ...v, file: label }));
}

function runFiles() {
  let total = 0;
  for (const rel of GATED_FILES) {
    const abs = resolve(REPO_ROOT, rel);
    let raw;
    try {
      raw = readFileSync(abs, 'utf8');
    } catch (err) {
      console.error(`✗ cannot read gated file: ${rel}\n  ${err.message}`);
      total += 1;
      continue;
    }
    const violations = analyzeSource(rel, raw);
    if (violations.length === 0) {
      console.log(`✓ ${rel}`);
    } else {
      for (const v of violations) {
        console.error(`✗ ${v.file}:${v.line} — Rule ${v.rule}\n    ${v.text}`);
      }
      total += violations.length;
    }
  }

  if (total > 0) {
    console.error(
      `\n✗ AWS-gate guard FAILED: ${total} violation(s).\n` +
        '  Fix: route the segmentation decision through `isSegmentedPlatform`\n' +
        '  (not `compute_cost != null`) and label AWS branches with\n' +
        '  `AWS_CLOUD_LABEL` (not `compute_service`/`compute_display_name`).\n' +
        '  See docs/plan_aws_cost_accuracy_cleanup.md §4.0(c).'
    );
    return 1;
  }
  console.log(`\n✓ AWS-gate guard passed (${GATED_FILES.length} components clean).`);
  return 0;
}

function runSelfTest() {
  const cases = [
    {
      name: 'GOOD: blessed hasSegmented paired with allowlist',
      src: [
        'const hasSegmented = metrics.total_compute_cost != null;',
        'const showSegmented = hasSegmented && isSegmentedPlatform;',
      ].join('\n'),
      expect: 0,
    },
    {
      name: 'GOOD: null-safe formatter inside isSegmentedPlatform region',
      src: [
        '{isSegmentedPlatform && (',
        '  <Cell>{cluster.total_compute_cost != null ? f(cluster.total_compute_cost) : "—"}</Cell>',
        ')}',
      ].join('\n'),
      expect: 0,
    },
    {
      name: 'GOOD: config label only in non-AWS (else) branch',
      src: '<span>{isAws ? AWS_CLOUD_LABEL : (cloudConfig?.compute_service || "Cloud")}</span>',
      expect: 0,
    },
    {
      name: 'GOOD: config label in a comment is ignored',
      src: '// historically labelled from compute_display_name; now AWS_CLOUD_LABEL\nconst x = 1;',
      expect: 0,
    },
    {
      name: 'BAD: showSegmented decided by data shape (no allowlist)',
      src: 'const showSegmented = metrics.total_compute_cost != null;',
      expect: 1,
    },
    {
      name: 'BAD: bare data-shape render gate',
      src: '{job.total_compute_cost != null && (<SegmentedColumns />)}',
      expect: 1,
    },
    {
      name: 'BAD: allowlist swapped for negative !isAws gate',
      src: [
        'const hasSegmented = metrics.total_compute_cost != null;',
        'const showSegmented = hasSegmented && !isAws;',
      ].join('\n'),
      expect: 1,
    },
    {
      name: 'BAD: config label in the AWS-true branch',
      src: '<span>{isAws ? (cloudConfig?.compute_service || "Cloud") : AWS_CLOUD_LABEL}</span>',
      expect: 1,
    },
    {
      name: 'BAD: config label in AWS branch (multi-line ternary)',
      src: ['label={', '  isAws', '    ? cloudConfig?.compute_display_name', '    : AWS_CLOUD_LABEL', '}'].join(
        '\n'
      ),
      expect: 1,
    },
  ];

  let failures = 0;
  for (const c of cases) {
    const got = analyzeSource('<self-test>', c.src).length;
    const ok = got === c.expect;
    if (!ok) failures += 1;
    console.log(`${ok ? '✓' : '✗'} [${got}/${c.expect}] ${c.name}`);
  }
  if (failures > 0) {
    console.error(`\n✗ self-test FAILED: ${failures} case(s) wrong.`);
    return 1;
  }
  console.log(`\n✓ self-test passed (${cases.length} cases).`);
  return 0;
}

const selfTest = process.argv.includes('--self-test');
process.exit(selfTest ? runSelfTest() : runFiles());

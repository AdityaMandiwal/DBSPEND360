#!/usr/bin/env python3
"""CP10 — Pre-merge reconciliation assert for the AWS DEFAULT_SERVICES shrink.

Plan reference: docs/plan_aws_cost_accuracy_cleanup.md §4.8(a), D15, MEDIUM-3.

This is the one-time gate that must pass **before** the §4.1a CE SERVICE-filter
shrink (CP11) lands. It runs the exact same Cost Explorer query twice over the
same window — once with the current 7-entry ``DEFAULT_SERVICES`` and once with
the proposed 2-entry EC2 pair — and asserts that the **tagged** (``ClusterId``
non-empty) total is unchanged. If the assert fails, a dropped service is
carrying cluster-attributable cost and must be re-included before shrinking.

It is deliberately NOT wired into the recurring DABs job; it is an
implementation-time check (CLAUDE.md: scripts in ``claude_scripts/`` are for
testing/verification only).

Credentials / runtime:
    AWS Cost Explorer access uses the Databricks service credential
    ``dbspend-read-ce`` (same as the ETL). This therefore runs cleanly inside a
    Databricks notebook/job where ``dbutils`` + a ``spark`` global exist. When
    run locally via ``uv run`` it will (a) build a Spark session through
    databricks-connect serverless and (b) fall back to a default boto3 session
    if ``dbutils`` is unavailable — in that case standard AWS credential
    resolution (env / profile / role) must grant ``ce:GetCostAndUsage``.

Usage:
    # Match the §1 evidence window (AmortizedCost, 3 days)
    uv run claude_scripts/aws_cost_recon_assert.py --start 2026-06-17 --end 2026-06-20

    # Default window = the last 3 complete UTC days
    uv run claude_scripts/aws_cost_recon_assert.py

Exit code 0 = reconciliation passed (shrink is safe); 1 = mismatch or error.
"""

import argparse
import sys
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Service lists under comparison (mirrors aws_cloud_cost_explorer_app.ipynb)
# ---------------------------------------------------------------------------

# Current production filter (cell 5, AWSCostClient.DEFAULT_SERVICES).
OLD_DEFAULT_SERVICES: List[str] = [
  'Amazon Elastic Compute Cloud - Compute',
  'EC2 - Other',
  'Amazon Elastic Block Store',
  'Amazon Simple Storage Service',
  'Elastic Load Balancing',
  'AWS Data Transfer',
  'Amazon Virtual Private Cloud',
]

# Proposed shrink (plan §4.1a): the EC2 family only. EBS folds into "EC2 - Other".
NEW_DEFAULT_SERVICES: List[str] = [
  'Amazon Elastic Compute Cloud - Compute',
  'EC2 - Other',
]

CE_REGION = 'us-east-1'
DEFAULT_SERVICE_CREDENTIAL = 'dbspend-read-ce'
DEFAULT_METRIC = 'AmortizedCost'
DEFAULT_TAG_KEY = 'ClusterId'
# Floating-point tolerance for the tagged-total comparison (USD).
DEFAULT_EPS = 0.01


# ---------------------------------------------------------------------------
# Cost Explorer client (self-contained mirror of the ETL's AWSCostClient)
# ---------------------------------------------------------------------------


class CEReconClient:
  """Minimal CE client replicating the ETL's query/parse for comparability.

  Kept independent of the ETL notebook so this gate has no ``%run`` dependency,
  but the request shape (dual GroupBy TAG+SERVICE, DAILY, exclusive end) is
  identical so old/new totals are apples-to-apples.
  """

  MAX_CHUNK_DAYS = 30
  MAX_RETRIES = 5
  BASE_RETRY_DELAY = 5

  def __init__(self, service_credential_name: str = DEFAULT_SERVICE_CREDENTIAL):
    import boto3

    botocore_session = _resolve_botocore_session(service_credential_name)
    if botocore_session is not None:
      session = boto3.Session(botocore_session=botocore_session, region_name=CE_REGION)
    else:
      session = boto3.Session(region_name=CE_REGION)
    self.client = session.client('ce')

  def get_tagged_rows(
    self,
    start_date: date,
    end_date: date,
    services: List[str],
    tag_key: str = DEFAULT_TAG_KEY,
    metric: str = DEFAULT_METRIC,
  ) -> List[Dict[str, Any]]:
    """Return parsed CE rows (one per cluster/service/day) for *services*.

    Untagged rows (empty cluster_id) are included here; the caller filters to
    the tagged subset so it can also report what the untagged side looks like.
    """
    rows: List[Dict[str, Any]] = []
    for chunk_start, chunk_end in self._build_chunks(start_date, end_date):
      rows.extend(self._query_with_retries(chunk_start, chunk_end, tag_key, services, metric))
    return rows

  def _build_chunks(self, start: date, end: date) -> List[Tuple[date, date]]:
    chunks = []
    current = start
    while current <= end:
      chunk_end = min(current + timedelta(days=self.MAX_CHUNK_DAYS - 1), end)
      chunks.append((current, chunk_end))
      current = chunk_end + timedelta(days=1)
    return chunks

  def _build_ce_params(
    self, start: date, end: date, tag_key: str, services: List[str], metric: str
  ) -> dict:
    return {
      'TimePeriod': {
        'Start': start.isoformat(),
        'End': (end + timedelta(days=1)).isoformat(),  # CE End is exclusive
      },
      'Granularity': 'DAILY',
      'Metrics': [metric],
      'GroupBy': [
        {'Type': 'TAG', 'Key': tag_key},
        {'Type': 'DIMENSION', 'Key': 'SERVICE'},
      ],
      'Filter': {'Dimensions': {'Key': 'SERVICE', 'Values': services}},
    }

  def _query_with_retries(
    self, start: date, end: date, tag_key: str, services: List[str], metric: str
  ) -> List[Dict[str, Any]]:
    from botocore.exceptions import ClientError

    params = self._build_ce_params(start, end, tag_key, services, metric)
    last_exception: Optional[Exception] = None

    for attempt in range(self.MAX_RETRIES):
      try:
        return self._execute_paginated_query(params, metric)
      except ClientError as e:
        last_exception = e
        error_code = e.response['Error']['Code']
        if error_code == 'LimitExceededException':
          wait = min(self.BASE_RETRY_DELAY * (2**attempt), 120)
          print(f'  rate limited (attempt {attempt + 1}/{self.MAX_RETRIES}); waiting {wait}s')
          time.sleep(wait)
        elif attempt < self.MAX_RETRIES - 1:
          wait = 2**attempt
          print(f'  ClientError {error_code} (attempt {attempt + 1}); retrying in {wait}s')
          time.sleep(wait)
        else:
          raise
      except Exception as e:  # noqa: BLE001 - mirror ETL transient retry
        last_exception = e
        if attempt < self.MAX_RETRIES - 1:
          wait = 2**attempt
          print(f'  unexpected error (attempt {attempt + 1}); retrying in {wait}s: {e}')
          time.sleep(wait)
        else:
          raise

    assert last_exception is not None
    raise last_exception

  def _execute_paginated_query(self, params: dict, metric: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    request_params = params.copy()
    while True:
      response = self.client.get_cost_and_usage(**request_params)
      rows.extend(self._parse_response(response, metric))
      next_token = response.get('NextPageToken')
      if not next_token:
        break
      request_params['NextPageToken'] = next_token
      time.sleep(0.5)
    return rows

  def _parse_response(self, response: dict, metric: str) -> List[Dict[str, Any]]:
    rows = []
    for time_block in response.get('ResultsByTime', []):
      period_date = time_block['TimePeriod']['Start']
      for group in time_block.get('Groups', []):
        keys = group.get('Keys', [])
        if len(keys) < 2:
          continue
        raw_tag = keys[0]
        cluster_id = raw_tag.split('$')[-1] if '$' in raw_tag else raw_tag
        service_name = keys[1]
        metric_data = group['Metrics'].get(metric, {})
        amount = float(Decimal(metric_data.get('Amount', '0')))
        if amount == 0.0:
          continue
        rows.append({
          'cluster_id': cluster_id,
          'service_name': service_name,
          'cost': amount,
          'currency': metric_data.get('Unit', 'USD'),
          'cost_incurred_date': period_date,
        })
    return rows


def _resolve_botocore_session(service_credential_name: str):
  """Get a botocore session from the Databricks service credential, or None.

  Mirrors the ETL: ``dbutils.credentials.getServiceCredentialsProvider`` is the
  authoritative path inside Databricks. Returns ``None`` when ``dbutils`` is not
  present so the caller falls back to default AWS credential resolution.
  """
  dbutils = _get_dbutils()
  if dbutils is None:
    print(
      'dbutils unavailable — falling back to default boto3 credential resolution '
      '(env / profile / role must grant ce:GetCostAndUsage).'
    )
    return None
  try:
    return dbutils.credentials.getServiceCredentialsProvider(service_credential_name)
  except Exception as e:  # noqa: BLE001
    print(f'Could not load service credential {service_credential_name!r}: {e}')
    print('Falling back to default boto3 credential resolution.')
    return None


def _get_dbutils():
  """Return a dbutils handle if running inside (or connected to) Databricks."""
  try:
    return dbutils  # type: ignore[name-defined]  # injected in notebooks
  except NameError:
    pass
  try:
    from databricks.sdk.runtime import dbutils as _dbutils

    return _dbutils
  except Exception:  # noqa: BLE001
    return None


# ---------------------------------------------------------------------------
# Reconciliation (pure, Spark-free so it is unit-testable)
# ---------------------------------------------------------------------------


def tagged_total(rows: List[Dict[str, Any]]) -> float:
  """Sum cost over rows with a non-empty cluster_id.

  Equivalent to ``utils_common.filter_valid_cost_rows`` followed by
  ``SUM(cost)`` — the definition of cluster-attributable AWS spend.
  """
  return float(sum(r['cost'] for r in rows if (r.get('cluster_id') or '').strip()))


def tagged_by_service(rows: List[Dict[str, Any]]) -> Dict[str, float]:
  """Tagged cost grouped by service_name (for the per-dropped-service report)."""
  out: Dict[str, float] = {}
  for r in rows:
    if (r.get('cluster_id') or '').strip():
      out[r['service_name']] = out.get(r['service_name'], 0.0) + r['cost']
  return out


def reconcile(
  old_rows: List[Dict[str, Any]],
  new_rows: List[Dict[str, Any]],
  old_services: List[str],
  new_services: List[str],
) -> Dict[str, Any]:
  """Compare tagged totals and itemize the cost on each dropped service."""
  old_total = tagged_total(old_rows)
  new_total = tagged_total(new_rows)
  by_service = tagged_by_service(old_rows)
  dropped = [s for s in old_services if s not in set(new_services)]
  dropped_breakdown = {s: by_service.get(s, 0.0) for s in dropped}
  return {
    'old_total': old_total,
    'new_total': new_total,
    'diff': new_total - old_total,
    'dropped_services': dropped,
    'dropped_breakdown': dropped_breakdown,
    'dropped_tagged_total': float(sum(dropped_breakdown.values())),
  }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _default_window() -> Tuple[date, date]:
  """The last 3 complete UTC days (yesterday-2 .. yesterday)."""
  end = datetime.now(timezone.utc).date() - timedelta(days=1)
  return end - timedelta(days=2), end


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
  """Parse CLI arguments; defaults to the last 3 complete UTC days."""
  start_default, end_default = _default_window()
  p = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
  )
  p.add_argument(
    '--start', type=date.fromisoformat, default=start_default, help='Start YYYY-MM-DD (incl).'
  )
  p.add_argument(
    '--end', type=date.fromisoformat, default=end_default, help='Window end YYYY-MM-DD (incl).'
  )
  p.add_argument('--eps', type=float, default=DEFAULT_EPS, help=f'USD tolerance ({DEFAULT_EPS}).')
  p.add_argument('--metric', default=DEFAULT_METRIC, help=f'CE metric (def {DEFAULT_METRIC}).')
  p.add_argument('--tag-key', default=DEFAULT_TAG_KEY, help=f'CE tag key (def {DEFAULT_TAG_KEY}).')
  p.add_argument(
    '--service-credential',
    default=DEFAULT_SERVICE_CREDENTIAL,
    help=f'Databricks service credential (def {DEFAULT_SERVICE_CREDENTIAL}).',
  )
  return p.parse_args(argv)


def run_assert(args: argparse.Namespace) -> int:
  """Run both CE queries, print the reconciliation report, return exit code."""
  if args.start > args.end:
    print(f'ERROR: --start {args.start} is after --end {args.end}.')
    return 1

  print('=' * 72)
  print('CP10 — AWS DEFAULT_SERVICES shrink reconciliation assert')
  print('=' * 72)
  print(f'Window : {args.start} -> {args.end} (inclusive)')
  print(f'Metric : {args.metric}   Tag key: {args.tag_key}   EPS: ${args.eps}')
  print(f'Old filter ({len(OLD_DEFAULT_SERVICES)} services): {OLD_DEFAULT_SERVICES}')
  print(f'New filter ({len(NEW_DEFAULT_SERVICES)} services): {NEW_DEFAULT_SERVICES}')
  print('-' * 72)

  client = CEReconClient(service_credential_name=args.service_credential)

  print('Querying CE with OLD (7-entry) filter ...')
  old_rows = client.get_tagged_rows(
    args.start, args.end, OLD_DEFAULT_SERVICES, tag_key=args.tag_key, metric=args.metric
  )
  print(f'  -> {len(old_rows)} non-zero rows')

  print('Querying CE with NEW (2-entry) filter ...')
  new_rows = client.get_tagged_rows(
    args.start, args.end, NEW_DEFAULT_SERVICES, tag_key=args.tag_key, metric=args.metric
  )
  print(f'  -> {len(new_rows)} non-zero rows')
  print('-' * 72)

  result = reconcile(old_rows, new_rows, OLD_DEFAULT_SERVICES, NEW_DEFAULT_SERVICES)

  print('Tagged (ClusterId non-empty) totals:')
  print(f'  old = ${result["old_total"]:.4f}')
  print(f'  new = ${result["new_total"]:.4f}')
  print(f'  diff (new - old) = ${result["diff"]:.4f}')
  print()
  print('Tagged cost on dropped services (must be ~0 for a safe shrink):')
  for svc in result['dropped_services']:
    print(f'  {svc:<42} ${result["dropped_breakdown"][svc]:.4f}')
  print(f'  {"TOTAL dropped tagged":<42} ${result["dropped_tagged_total"]:.4f}')
  print('=' * 72)

  if abs(result['diff']) < args.eps:
    print(
      f'PASS: tagged total unchanged within ${args.eps} '
      '— the DEFAULT_SERVICES shrink drops no cluster-attributable cost.'
    )
    return 0

  print(
    'FAIL: DEFAULT_SERVICES shrink dropped tagged cost: '
    f'old={result["old_total"]:.4f}, new={result["new_total"]:.4f}; '
    'a dropped service carries ClusterId — re-include it before shrinking.'
  )
  return 1


def main(argv: Optional[List[str]] = None) -> int:
  """CLI entrypoint: parse args, run the assert, map errors to exit codes."""
  args = _parse_args(argv)
  try:
    return run_assert(args)
  except KeyboardInterrupt:
    print('\nInterrupted by user.')
    return 130
  except Exception as e:  # noqa: BLE001
    print(f'ERROR: {e}')
    return 1


if __name__ == '__main__':
  sys.exit(main())

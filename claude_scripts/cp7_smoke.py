"""CP7 smoke verification for the Instance Pools router + LLM analysis.

Exercises every endpoint mounted by `server/routers/instance_pools.py`
plus the LLM cloud-cost caveat assertion per plan §8 CP7 exit
criteria 1–4 and §9 acceptance criterion #10:

1. `nohup ./watch.sh` started cleanly (precondition — checked by
   asserting `/health` returns 200).
2. All 6 endpoints return 200 with the expected JSON shape.
3. `total_count` on `/grouped` equals `total_pools` on `/summary`.
4. `/{pool_id}/analyze` response includes the v1 cloud-cost caveat.

Run with:
    uv run python claude_scripts/cp7_smoke.py
"""

import json
import os
import sys
import urllib.request
from datetime import date, timedelta

BASE = os.environ.get('DBSPEND360_BASE_URL', 'http://localhost:8000')
WINDOW_DAYS = int(os.environ.get('DBSPEND360_CP7_WINDOW_DAYS', '33'))

# Pool cloud contains only ClusterId-free idle/warm capacity. Active
# pool-backed VM cost remains on the Job or All-Purpose lens.
CAVEAT_CANDIDATES = (
    'active pool-backed VM cost is attributed to the Job or All-Purpose tab '
    'and is not included here',
    'Active pool-backed VM cost is attributed to the Job or All-Purpose tab '
    'and is not included here',
)


def _get(url: str, timeout: float = 30.0) -> tuple[int, object]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode('utf-8')
            return resp.getcode(), json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8', errors='replace')
        try:
            payload = json.loads(body)
        except Exception:
            payload = body
        return exc.code, payload


def main() -> int:
    failures: list[str] = []
    end = date.today()
    start = end - timedelta(days=WINDOW_DAYS)
    window = f'start_date={start.isoformat()}&end_date={end.isoformat()}'
    print(f'[cp7] BASE={BASE}')
    print(f'[cp7] window: {start} -> {end} ({WINDOW_DAYS}d)')

    # ---- 1. /health ---------------------------------------------------
    print('\n[cp7 #1] GET /api/instance-pools/health')
    code, body = _get(f'{BASE}/api/instance-pools/health')
    print(f'   status={code} body={body}')
    if code != 200:
        failures.append(f'/health returned {code}')
    elif not isinstance(body, dict) or body.get('service') != 'instance-pools':
        failures.append(f'/health unexpected body: {body}')

    # ---- 2. /summary --------------------------------------------------
    print('\n[cp7 #2] GET /api/instance-pools/summary')
    code, body = _get(f'{BASE}/api/instance-pools/summary?{window}')
    print(f'   status={code}')
    summary = body if isinstance(body, dict) else {}
    if code != 200:
        failures.append(f'/summary returned {code}: {body}')
    else:
        for key in ('total_pools', 'total_clusters', 'orphaned_pools', 'total_spend'):
            if key not in summary:
                failures.append(f'/summary missing field {key!r}')
        # CP8: total_cloud_cost is now the real summed pool EC2/EBS cost (or
        # None when no pool-day in the window has a cloud row yet) — no longer
        # forced to None.
        print(
            f"   total_pools={summary.get('total_pools')} "
            f"total_clusters={summary.get('total_clusters')} "
            f"orphaned_pools={summary.get('orphaned_pools')} "
            f"total_spend={summary.get('total_spend')}"
        )

    # ---- 3. /grouped --------------------------------------------------
    print('\n[cp7 #3] GET /api/instance-pools/grouped (per_page=5)')
    code, body = _get(f'{BASE}/api/instance-pools/grouped?{window}&page=1&per_page=5')
    print(f'   status={code}')
    grouped = body if isinstance(body, dict) else {}
    if code != 200:
        failures.append(f'/grouped returned {code}: {body}')
    else:
        if 'total_count' not in grouped or 'data' not in grouped:
            failures.append('/grouped missing total_count or data')
        # Exit criterion #3: total_count == total_pools
        if (
            isinstance(summary.get('total_pools'), int)
            and isinstance(grouped.get('total_count'), int)
            and summary['total_pools'] != grouped['total_count']
        ):
            failures.append(
                f"/grouped.total_count ({grouped['total_count']}) != "
                f"/summary.total_pools ({summary['total_pools']})"
            )
        first = (grouped.get('data') or [None])[0]
        print(
            f"   total_count={grouped.get('total_count')} "
            f"data_len={len(grouped.get('data') or [])} "
            f"first_pool={first.get('instance_pool_id') if first else None}"
        )

    # ---- 4. /top-pools ------------------------------------------------
    print('\n[cp7 #4] GET /api/instance-pools/top-pools (limit=3)')
    code, body = _get(f'{BASE}/api/instance-pools/top-pools?{window}&limit=3')
    print(f'   status={code}')
    tops = body if isinstance(body, list) else []
    if code != 200:
        failures.append(f'/top-pools returned {code}: {body}')
    else:
        for row in tops:
            print(
                f"   pool={row.get('instance_pool_id')} "
                f"name={row.get('pool_name')!r} "
                f"total={row.get('total_cost')} "
                f"days_len={len(row.get('days') or [])}"
            )
            if row.get('days'):
                failures.append(
                    f"/top-pools row {row.get('instance_pool_id')} has non-empty days[] "
                    f"({len(row['days'])}); endpoint must skip drill-down enrichment"
                )

    # ---- 5. /{id}/details — sentinel ---------------------------------
    fake_id = 'cp7-fake-pool-zzz'
    print(f'\n[cp7 #5a] GET /api/instance-pools/{fake_id}/details (sentinel)')
    code, body = _get(f'{BASE}/api/instance-pools/{fake_id}/details')
    print(f"   status={code} pool_snapshot_missing={body.get('pool_snapshot_missing') if isinstance(body, dict) else 'N/A'}")
    if code != 200:
        failures.append(f'/{fake_id}/details returned {code}: {body}')
    elif not body.get('pool_snapshot_missing'):
        failures.append(
            f'/{fake_id}/details should return pool_snapshot_missing=True for an unknown id'
        )

    # ---- 5b. /{id}/details — real -----------------------------------
    real_id = None
    if tops:
        real_id = tops[0].get('instance_pool_id')
    if real_id:
        print(f'\n[cp7 #5b] GET /api/instance-pools/{real_id}/details (real)')
        code, body = _get(f'{BASE}/api/instance-pools/{real_id}/details')
        print(
            f"   status={code} "
            f"name={body.get('pool_name') if isinstance(body, dict) else None!r} "
            f"creator_id={body.get('pool_creator_id') if isinstance(body, dict) else None!r}"
        )
        if code != 200:
            failures.append(f'/{real_id}/details returned {code}: {body}')
    else:
        print('\n[cp7 #5b] SKIP: no real pool ids from /top-pools')

    # ---- 6. /{id}/analyze ---------------------------------------------
    if real_id:
        print(f'\n[cp7 #6] GET /api/instance-pools/{real_id}/analyze')
        code, body = _get(
            f'{BASE}/api/instance-pools/{real_id}/analyze', timeout=120.0
        )
        print(f'   status={code}')
        analysis = body.get('analysis') if isinstance(body, dict) else None
        if code != 200:
            failures.append(f'/{real_id}/analyze returned {code}: {body}')
        elif not analysis:
            failures.append(f'/{real_id}/analyze returned empty analysis')
        else:
            print(f'   analysis length={len(analysis)} chars')
            if not any(c in analysis for c in CAVEAT_CANDIDATES):
                failures.append(
                    '/{id}/analyze response does NOT include the v1 cloud-cost '
                    'caveat string (plan §9 acceptance #10)'
                )
            else:
                print('   v1 cloud-cost caveat detected in analysis text')
    else:
        print('\n[cp7 #6] SKIP: no real pool ids to analyze')

    print('\n[cp7] DONE')
    if failures:
        print(f'[cp7] FAILED ({len(failures)} assertion(s)):')
        for f in failures:
            print(f'   - {f}')
        return 1
    print('[cp7] All CP7 exit criteria passed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())

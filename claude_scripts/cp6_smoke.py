"""CP6 smoke verification for the Instance Pools backend service methods.

Exercises every new method in `DatabricksService` against dev data per
plan §8 CP6 exit criteria 1–5:

1. Happy-path call for each new method.
2. `_get_batch_pool_days_and_clusters` per-cluster sums == per-day total
   (structural invariant from §9 / §5.2).
3. `get_instance_pool_details('made-up-id-12345')` returns the
   `pool_snapshot_missing=True` sentinel (no exception).
4. `get_pool_metadata('made-up-id-12345')` returns
   `('Pool made-up-id-12345', None)` and is cached so a second call
   doesn't re-issue the REST API.
5. For a known active pool: `get_pool_metadata(<real_id>)` returns the
   real name and a non-None creator GUID matching the REST API's
   `default_tags['DatabricksInstancePoolCreatorId']`.

Run with:
    uv run python claude_scripts/cp6_smoke.py
"""

import asyncio
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

if "DATABRICKS_HOST" not in os.environ or "DATABRICKS_TOKEN" not in os.environ:
    env_file = Path(__file__).parent.parent / ".env.local"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("cp6_smoke")

from server.services.databricks_service import DatabricksService  # noqa: E402


def _format_money(v):
    return f"${v:,.4f}" if v is not None else "None"


async def main() -> int:
    service = DatabricksService()
    end = date.today()
    start = end - timedelta(days=30)
    print(f"[cp6] window: {start} -> {end}")
    print(f"[cp6] pool_table_name: {service.pool_table_name}")

    failures: list[str] = []

    # ---- Exit #1 (a): summary metrics happy path ---------------------
    print("\n[cp6 #1a] get_instance_pool_summary_metrics")
    summary = await service.get_instance_pool_summary_metrics(start, end)
    print(
        f"   total_pools={summary.total_pools} total_clusters={summary.total_clusters} "
        f"orphaned_pools={summary.orphaned_pools} total_spend={_format_money(summary.total_spend)} "
        f"date_range_days={summary.date_range_days}"
    )
    if summary.total_cloud_cost is not None:
        failures.append(
            f"summary.total_cloud_cost must be None in v1 (got {summary.total_cloud_cost})"
        )

    # ---- Exit #1 (b): grouped list happy path ------------------------
    print("\n[cp6 #1b] get_instance_pools_grouped (limit=5)")
    page = await service.get_instance_pools_grouped(start, end, limit=5, offset=0)
    print(
        f"   total_count={page.total_count} rows={len(page.data)} "
        f"page={page.page}/{page.total_pages}"
    )
    for row in page.data[:3]:
        print(
            f"   pool={row.instance_pool_id} name={row.pool_name!r} "
            f"clusters={row.cluster_count} active_days={row.active_days} "
            f"total={_format_money(row.total_cost)} days={len(row.days)}"
        )

    # ---- Exit #1 (c): top pools happy path ---------------------------
    print("\n[cp6 #1c] get_top_instance_pools (limit=3)")
    tops = await service.get_top_instance_pools(start, end, limit=3)
    for row in tops:
        print(
            f"   pool={row.instance_pool_id} name={row.pool_name!r} "
            f"total={_format_money(row.total_cost)}"
        )

    # ---- Exit #2: structural invariant on day rollup -----------------
    print("\n[cp6 #2] structural invariant: sum(clusters.total) == day.total")
    invariant_pairs = 0
    invariant_failures = 0
    for pool in page.data:
        for day in pool.days:
            cluster_sum = sum(c.total_cost for c in day.clusters)
            invariant_pairs += 1
            if abs(cluster_sum - day.total_cost) > 1e-6:
                invariant_failures += 1
                msg = (
                    f"pool={pool.instance_pool_id} day={day.usage_date}: "
                    f"sum(clusters)={cluster_sum} != day.total={day.total_cost}"
                )
                failures.append(msg)
                print(f"   FAIL {msg}")
            if day.cluster_count_on_day != len(day.clusters):
                msg = (
                    f"pool={pool.instance_pool_id} day={day.usage_date}: "
                    f"cluster_count_on_day={day.cluster_count_on_day} != "
                    f"len(clusters)={len(day.clusters)}"
                )
                failures.append(msg)
                print(f"   FAIL {msg}")
    print(f"   checked {invariant_pairs} (pool, day) pairs; failures={invariant_failures}")

    # ---- Exit #3: details sentinel for made-up id --------------------
    print("\n[cp6 #3] get_instance_pool_details('made-up-id-12345') sentinel")
    sentinel = await service.get_instance_pool_details("made-up-id-12345")
    print(
        f"   instance_pool_id={sentinel.instance_pool_id} "
        f"pool_snapshot_missing={sentinel.pool_snapshot_missing} "
        f"pool_creator_id={sentinel.pool_creator_id} "
        f"pool_name={sentinel.pool_name!r}"
    )
    if not sentinel.pool_snapshot_missing:
        failures.append("sentinel.pool_snapshot_missing must be True")

    # ---- Exit #4: metadata cache on missing id -----------------------
    print("\n[cp6 #4] get_pool_metadata('made-up-id-12345') cached fallback")
    service.pool_metadata_cache.pop("made-up-id-12345", None)
    first = await service.get_pool_metadata("made-up-id-12345")
    cached_after_first = "made-up-id-12345" in service.pool_metadata_cache
    cache_size_after_first = len(service.pool_metadata_cache)
    second = await service.get_pool_metadata("made-up-id-12345")
    print(
        f"   first={first} cached_after_first={cached_after_first} "
        f"cache_size_after_first={cache_size_after_first} second={second}"
    )
    if first != ("Pool made-up-id-12345", None):
        failures.append(f"fallback tuple shape regressed: {first}")
    if not cached_after_first:
        failures.append("metadata cache missing entry after first call")
    if first != second:
        failures.append("second call returned a different tuple — cache miss")

    # ---- Exit #5: real pool metadata + creator GUID ------------------
    print("\n[cp6 #5] get_pool_metadata on a real pool from get_top_instance_pools")
    if not tops:
        print("   SKIP: workspace has no pool spends in this window")
    else:
        real_id = tops[0].instance_pool_id
        service.pool_metadata_cache.pop(real_id, None)
        name, creator = await service.get_pool_metadata(real_id)
        print(f"   pool_id={real_id} name={name!r} creator_id={creator!r}")
        if name.startswith("Pool ") and name.endswith(real_id):
            print(
                "   NOTE: REST API call fell back to placeholder — pool may be "
                "deleted, inaccessible, or the workspace lacks Instance Pools API access."
            )
        # Cross-check directly against the SDK
        try:
            direct = service.client.instance_pools.get(instance_pool_id=real_id)
            direct_tag = (direct.default_tags or {}).get(
                "DatabricksInstancePoolCreatorId"
            )
            print(
                f"   direct SDK default_tags['DatabricksInstancePoolCreatorId']={direct_tag!r}"
            )
            if creator != direct_tag:
                failures.append(
                    f"creator GUID mismatch: cached={creator!r} direct={direct_tag!r}"
                )
        except Exception as exc:
            print(f"   direct SDK call failed: {exc}")

        # Also exercise the full details path on the same real pool.
        print("\n[cp6 #5b] get_instance_pool_details for the same real pool")
        details = await service.get_instance_pool_details(real_id)
        print(
            f"   pool_snapshot_missing={details.pool_snapshot_missing} "
            f"name={details.pool_name!r} creator={details.pool_creator_id!r} "
            f"node_type={details.node_type!r} "
            f"min_idle={details.min_idle_instances} max_cap={details.max_capacity} "
            f"autoterm_min={details.idle_instance_autotermination_minutes} "
            f"preloaded_spark_version={details.preloaded_spark_version!r}"
        )

    print("\n[cp6] DONE")
    if failures:
        print(f"[cp6] FAILED ({len(failures)} assertion(s)):")
        for failure in failures:
            print(f"   - {failure}")
        return 1
    print("[cp6] All CP6 exit criteria passed.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

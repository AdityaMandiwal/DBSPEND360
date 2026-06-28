// By-Pool table for the Instance Pools tab with two-level row expansion.
//
// Plan §3.3 / §5.2 / CP10:
//
//   Level 0 (pool row)           — one row per instance pool in the window
//                                   with denormalized config from
//                                   `system.compute.instance_pools`. Three
//                                   §3.5 badge states encoded by
//                                   `pool_snapshot_missing` +
//                                   `pool_deleted_at`. Pool name is
//                                   clickable and opens
//                                   `InstancePoolDetailsModal`.
//   Level 1 (pool → per-day)    — expand the pool row to see daily DBU
//                                   and cluster-count rows. Sorted by
//                                   `usage_date` ascending.
//   Level 2 (day → per-cluster) — expand a day row to see the per-cluster
//                                   breakdown. Capped at the top-25 clusters
//                                   by `total_cost` with an "Other (N) — $X"
//                                   rollup row when the cap kicks in — see
//                                   the §5.2 real-workspace calibration
//                                   (a single shared pool can fan out to
//                                   ~295 clusters/day, which is unusable
//                                   inside a nested table).
//
// Per plan §3.4 / §4.1 there is intentionally NO creator column here.
// Creator info is modal-only in v1; CP10 exit criterion #4 specifically
// asserts that the column is absent. Adding it here would require
// per-row REST API enrichment that the rollup table can't satisfy.
//
// `__pool_overhead__` cluster rows (the §3.3 edge case for billing rows
// with `instance_pool_id` set but `cluster_id` NULL) render as italicized
// "Pool overhead". They are NOT clickable for the cluster details modal —
// there's no real cluster behind them.

import { Fragment, useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronLeft, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ErrorState } from '@/components/ui/error-state';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { useInstancePools } from '@/hooks/useInstancePools';
import { useDatabricksHost } from '@/hooks/useDatabricksHost';
import { useCloudPlatform } from '@/contexts/CloudPlatformContext';
import { useIsAws, AWS_CLOUD_LABEL } from '@/hooks/useCloudGate';
import {
  POOL_CLOUD_MISSING_NOTE,
  POOL_PER_CLUSTER_CLOUD_NOTE,
} from '@/lib/pool-display';
import type {
  GroupedInstancePool,
  InstancePoolClusterSpend,
  InstancePoolDailySpend,
} from '@/types/instance-pool';
import type { DateRange } from '@/types/job-spend';
import { formatCalendarDate, formatLocalISODate } from '@/lib/utils';
import { ClusterDetailsModal } from './JobBreakdownModal';
import { InstancePoolDetailsModal } from './InstancePoolDetailsModal';

interface InstancePoolsTableProps {
  dateRange: DateRange;
  searchTerm: string;
}

const currencyFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const formatCurrency = (amount: number) => currencyFormatter.format(amount);

// `usage_date` is a calendar date (YYYY-MM-DD); `formatCalendarDate` anchors it
// to local midnight so it stays calendar-stable on negative-UTC zones.
const formatDate = (dateStr: string) => formatCalendarDate(dateStr);

// `pool_deleted_at` is a timestamp; render its LOCAL calendar day as ISO so the
// badge label doesn't shift a day vs. the user's timezone (plan §3.4).
const formatBadgeDate = (dateStr?: string | null): string | null =>
  dateStr ? formatLocalISODate(dateStr) : null;

const PAGE_SIZE = 25;

// Plan §5.2 / CP10 implementation note — cap rendering at the top 25
// clusters per day to keep the nested expansion usable on pools that
// fan out to hundreds of distinct clusters/day. Server-side rows
// arrive already sorted DESC by `total_cost` per the §5.2 SQL.
const CLUSTER_DISPLAY_CAP = 25;

// EC2/EBS cloud cell for the pool + per-day grain (plan §4.4 / §5). Renders the
// real $ when known — including a genuine `$0.00` — or "—" + a typed note when
// the value is NULL (no pool-tag cloud row landed yet). Pool VM cost is
// pool-level, so this cell never appears on per-cluster rows (those use
// `PerClusterCloudCell`).
const PoolCloudCostCell = ({ cloudCost }: { cloudCost?: number | null }) => {
  if (cloudCost == null) {
    return (
      <span
        className="text-muted-foreground cursor-help"
        title={POOL_CLOUD_MISSING_NOTE}
        aria-label={POOL_CLOUD_MISSING_NOTE}
      >
        —
      </span>
    );
  }
  return <span>{formatCurrency(cloudCost)}</span>;
};

// Per-cluster cloud cell — always "—". Pool VM cost is tracked at the pool
// level (on the synthesized `__pool_overhead__` row), not attributable to a
// specific attached cluster (plan §4.4).
const PerClusterCloudCell = () => (
  <span
    className="text-muted-foreground cursor-help"
    title={POOL_PER_CLUSTER_CLOUD_NOTE}
    aria-label={POOL_PER_CLUSTER_CLOUD_NOTE}
  >
    —
  </span>
);

export const InstancePoolsTable = ({
  dateRange,
  searchTerm,
}: InstancePoolsTableProps) => {
  const { config: cloudConfig } = useCloudPlatform();
  const isAws = useIsAws();
  // Pool cloud cost is a single EC2/EBS bucket (no compute/storage/network
  // segmentation — the pool explorer lands one `cloud_cost` per pool-day), so
  // we always render ONE cloud column. Only the label is platform-aware
  // (plan §4.7 / §1.4): `EC2 / EBS` on AWS, otherwise the provider's generic
  // compute-service name.
  const cloudLabel = isAws
    ? AWS_CLOUD_LABEL
    : `Total ${cloudConfig?.compute_service || 'Cloud'}`;
  const { data: databricksHost } = useDatabricksHost();
  const [page, setPage] = useState(1);
  const [expandedPools, setExpandedPools] = useState<Set<string>>(new Set());
  const [expandedDays, setExpandedDays] = useState<Set<string>>(new Set());
  const [activePoolModal, setActivePoolModal] = useState<string | null>(null);
  const [activeClusterModal, setActiveClusterModal] = useState<string | null>(
    null,
  );

  // Reset to page 1 when filters change so the user doesn't land on an
  // out-of-range page after the result set shrinks. Mirrors
  // `AllPurposeClustersTable` / `GroupedJobTable`.
  useEffect(() => {
    setPage(1);
    // Filter changes can swap the underlying pool/day set entirely, so drop all
    // expansion state to avoid showing stale or mismatched drill-downs (#P2).
    setExpandedPools(new Set());
    setExpandedDays(new Set());
  }, [searchTerm, dateRange.start_date, dateRange.end_date]);

  const { data, isLoading, isFetching, error, refetch } = useInstancePools({
    start_date: dateRange.start_date,
    end_date: dateRange.end_date,
    search: searchTerm || undefined,
    page,
    per_page: PAGE_SIZE,
  });

  const isInitialLoading = isLoading && !data;
  const isBackgroundFetching = isFetching && !!data;

  const rows = data?.data ?? [];
  const totalCount = data?.total_count ?? 0;
  const totalPages = data?.total_pages ?? 0;

  const togglePool = (poolId: string) => {
    setExpandedPools((prev) => {
      const next = new Set(prev);
      if (next.has(poolId)) {
        next.delete(poolId);
        // Collapsing a pool drops its per-day expansion state so re-expanding
        // the pool later starts clean instead of restoring stale day rows.
        // Day keys are prefixed with `${poolId}|` (see PoolDayBreakdown).
        setExpandedDays((days) => {
          const prefix = `${poolId}|`;
          let changed = false;
          const nextDays = new Set(days);
          for (const key of days) {
            if (key.startsWith(prefix)) {
              nextDays.delete(key);
              changed = true;
            }
          }
          return changed ? nextDays : days;
        });
      } else {
        next.add(poolId);
      }
      return next;
    });
  };

  const toggleDay = (key: string) => {
    setExpandedDays((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const workspaceHost = useMemo(() => {
    if (!databricksHost) return null;
    // Strip any `/apps/<name>` suffix that's present in deployed
    // environments — the pool URL lives at the workspace root.
    return databricksHost.replace(/\/apps\/[^\/]+$/, '');
  }, [databricksHost]);

  const poolUrl = (poolId: string) =>
    workspaceHost ? `${workspaceHost}/compute/instance-pools/${poolId}` : '#';

  // 8 data columns (incl. EC2/EBS cloud) + 1 expander.
  const columnCount = 9;

  return (
    <div className="space-y-4">
      <div className="rounded-md border relative overflow-hidden">
        {isBackgroundFetching && (
          <div
            className="absolute left-0 right-0 top-0 h-0.5 bg-blue-500/70 animate-pulse z-10"
            aria-hidden="true"
          />
        )}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10 px-2" />
              <TableHead className="px-4">Pool</TableHead>
              <TableHead className="px-4">Node Type</TableHead>
              <TableHead className="px-4 text-right">Clusters</TableHead>
              <TableHead className="px-4 text-right">Active Days</TableHead>
              <TableHead className="px-4 text-right">Min Idle</TableHead>
              <TableHead className="px-4 text-right">{cloudLabel}</TableHead>
              <TableHead className="px-4 text-right">DBU Cost</TableHead>
              <TableHead className="px-4 text-right">Total Cost</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {error ? (
              <TableRow>
                <TableCell colSpan={columnCount} className="h-24 text-center">
                  <ErrorState
                    compact
                    message={`Error loading instance pool data: ${error.message}`}
                    onRetry={() => refetch()}
                  />
                </TableCell>
              </TableRow>
            ) : isInitialLoading ? (
              [...Array(8)].map((_, i) => (
                <TableRow key={i}>
                  {[...Array(columnCount)].map((_, j) => (
                    <TableCell key={j} className="px-4">
                      <Skeleton className="h-8 w-full" />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : rows.length > 0 ? (
              rows.map((pool) => {
                const isExpanded = expandedPools.has(pool.instance_pool_id);
                const hasName =
                  !!pool.pool_name && pool.pool_name.trim().length > 0;
                const displayName = hasName
                  ? pool.pool_name!
                  : `Pool ${pool.instance_pool_id}`;
                return (
                  <Fragment key={pool.instance_pool_id}>
                    <TableRow className="hover:bg-muted/50">
                      <TableCell className="px-2">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => togglePool(pool.instance_pool_id)}
                          className="h-8 w-8 p-0"
                          aria-expanded={isExpanded}
                          aria-label={
                            isExpanded ? 'Collapse pool' : 'Expand pool'
                          }
                        >
                          {isExpanded ? (
                            <ChevronDown className="h-4 w-4" aria-hidden="true" />
                          ) : (
                            <ChevronRight className="h-4 w-4" aria-hidden="true" />
                          )}
                        </Button>
                      </TableCell>
                      <TableCell className="px-4 max-w-[300px]">
                        <button
                          type="button"
                          onClick={() =>
                            setActivePoolModal(pool.instance_pool_id)
                          }
                          className="text-left truncate font-medium text-blue-600 hover:text-blue-800 hover:underline"
                          title={`View details for ${pool.instance_pool_id}`}
                        >
                          <span className={hasName ? '' : 'font-mono'}>
                            {displayName}
                          </span>
                        </button>
                        <div className="text-xs text-muted-foreground font-mono truncate">
                          {workspaceHost ? (
                            <a
                              href={poolUrl(pool.instance_pool_id)}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="hover:underline"
                              title="Open in Databricks"
                            >
                              {pool.instance_pool_id}
                            </a>
                          ) : (
                            <span>{pool.instance_pool_id}</span>
                          )}
                        </div>
                        <PoolStateBadge pool={pool} />
                      </TableCell>
                      <TableCell className="px-4 max-w-[180px]">
                        <div
                          className="text-xs font-mono truncate"
                          title={pool.node_type ?? undefined}
                        >
                          {pool.node_type ?? '—'}
                        </div>
                      </TableCell>
                      <TableCell className="px-4 text-right">
                        <Badge variant="secondary" className="text-xs">
                          {pool.cluster_count}
                        </Badge>
                      </TableCell>
                      <TableCell className="px-4 text-right text-sm">
                        {pool.active_days}
                      </TableCell>
                      <TableCell className="px-4 text-right text-sm">
                        {pool.min_idle_instances ?? '—'}
                        {pool.max_capacity != null && (
                          <div className="text-xs text-muted-foreground">
                            max {pool.max_capacity}
                          </div>
                        )}
                      </TableCell>
                      <TableCell className="px-4 text-right font-medium text-blue-600">
                        <PoolCloudCostCell cloudCost={pool.total_cloud_cost} />
                      </TableCell>
                      <TableCell className="px-4 text-right font-medium text-red-600">
                        {formatCurrency(pool.total_databricks_cost)}
                      </TableCell>
                      <TableCell className="px-4 text-right">
                        <div className="font-bold text-lg">
                          {formatCurrency(pool.total_cost)}
                        </div>
                        {pool.total_cost > 1000 && (
                          <Badge variant="destructive" className="text-xs">
                            High Cost
                          </Badge>
                        )}
                      </TableCell>
                    </TableRow>
                    {isExpanded && (
                      <TableRow
                        key={`${pool.instance_pool_id}-expanded`}
                        className="bg-muted/30"
                      >
                        <TableCell colSpan={columnCount} className="p-0">
                          <PoolDayBreakdown
                            pool={pool}
                            cloudLabel={cloudLabel}
                            expandedDays={expandedDays}
                            onToggleDay={toggleDay}
                            onSelectCluster={setActiveClusterModal}
                          />
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                );
              })
            ) : (
              <TableRow>
                <TableCell colSpan={columnCount} className="h-24 text-center">
                  <div className="text-muted-foreground">
                    No instance pools found for the selected filters.
                  </div>
                  <div className="text-xs text-muted-foreground mt-2">
                    Pools may not be in use, or the date range is too narrow.
                  </div>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      {totalCount > 0 && (
        <div className="flex items-center justify-between">
          <div className="text-sm text-muted-foreground">
            Showing {rows.length} pool{rows.length === 1 ? '' : 's'} of{' '}
            {totalCount} total
            {searchTerm && ` (filtered by "${searchTerm}")`}
          </div>

          <div className="flex items-center space-x-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1 || isInitialLoading}
            >
              <ChevronLeft className="h-4 w-4 mr-1" /> Previous
            </Button>
            <div className="text-sm font-medium flex items-center gap-2">
              <span>
                Page {page} of {Math.max(totalPages, 1)}
              </span>
              {isBackgroundFetching && (
                <span className="text-xs text-muted-foreground" aria-live="polite">
                  Updating…
                </span>
              )}
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => p + 1)}
              disabled={page >= totalPages || isInitialLoading}
            >
              Next <ChevronRight className="h-4 w-4 ml-1" />
            </Button>
          </div>
        </div>
      )}

      {activePoolModal && (
        <InstancePoolDetailsModal
          poolId={activePoolModal}
          isOpen
          onClose={() => setActivePoolModal(null)}
        />
      )}

      {/* Re-use the existing cluster details modal for cluster-level
          drill-down inside a pool's per-day expansion. A pool's cluster
          can be either a job or all-purpose cluster, and the pool
          rollup row doesn't carry `cluster_source`, so we omit
          `clusterKind` and let the backend auto-detect from
          `system.compute.clusters.cluster_source`. /cluster/{id}/details
          is source-agnostic anyway; the routing matters for the analyze
          endpoint's cost-summary half (CP10 review #2 / plan §13). */}
      {activeClusterModal && (
        <ClusterDetailsModal
          clusterId={activeClusterModal}
          isOpen
          onClose={() => setActiveClusterModal(null)}
        />
      )}
    </div>
  );
};

// Plan §3.5 badge — three states, distinct UX:
//   - active            : no badge
//   - "Deleted YYYY-MM-DD" : pool exists in snapshot but `delete_time` set
//   - "Snapshot missing"   : no snapshot row for billed pool ID
const PoolStateBadge = ({ pool }: { pool: GroupedInstancePool }) => {
  if (pool.pool_deleted_at) {
    const dateLabel = formatBadgeDate(pool.pool_deleted_at);
    return (
      <Badge
        variant="secondary"
        className="mt-1 text-[10px] bg-amber-100 text-amber-700 hover:bg-amber-100 dark:bg-amber-500/15 dark:text-amber-300 dark:hover:bg-amber-500/15"
        title="Pool was deleted; metadata is as of that date. Cost data is still accurate."
      >
        Deleted {dateLabel}
      </Badge>
    );
  }
  if (pool.pool_snapshot_missing) {
    return (
      <Badge
        variant="secondary"
        className="mt-1 text-[10px] bg-amber-100 text-amber-700 hover:bg-amber-100 dark:bg-amber-500/15 dark:text-amber-300 dark:hover:bg-amber-500/15"
        title="Pool metadata not found in system.compute.instance_pools — likely deleted before retention or located in another region. DBU cost is still accurate."
      >
        Snapshot missing
      </Badge>
    );
  }
  return null;
};

// Per-day expansion panel for one pool. Renders one row per usage_date,
// and each row can itself expand to a per-cluster breakdown
// (`InstancePoolClusterSpend`). The day-level total is computed in
// Python at the service layer as a structural sum of the cluster array
// (plan §5.2), so the cluster-list inline tally always reconciles with
// the day total minus rounding.
const PoolDayBreakdown = ({
  pool,
  cloudLabel,
  expandedDays,
  onToggleDay,
  onSelectCluster,
}: {
  pool: GroupedInstancePool;
  cloudLabel: string;
  expandedDays: Set<string>;
  onToggleDay: (key: string) => void;
  onSelectCluster: (clusterId: string) => void;
}) => {
  // Sort once per `pool.days` change rather than on every render (#P3).
  const sortedDays = useMemo(
    () =>
      [...pool.days].sort((a, b) => a.usage_date.localeCompare(b.usage_date)),
    [pool.days],
  );

  if (pool.days.length === 0) {
    return (
      <div className="p-4 border-l-4 border-l-blue-500 bg-muted/20 text-sm text-muted-foreground">
        No daily breakdown returned for this pool.
      </div>
    );
  }

  return (
    <div className="p-4 border-l-4 border-l-blue-500 bg-muted/20">
      <h4 className="font-semibold text-sm text-muted-foreground mb-3">
        Daily breakdown ({pool.days.length} day
        {pool.days.length === 1 ? '' : 's'})
      </h4>
      <div className="space-y-2">
        {sortedDays.map((day) => {
            const key = `${pool.instance_pool_id}|${day.usage_date}`;
            const isDayExpanded = expandedDays.has(key);
            return (
              <div
                key={key}
                className="rounded-md border bg-background overflow-hidden"
              >
                <div className="flex items-center justify-between p-3">
                  <div className="flex items-center space-x-3">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => onToggleDay(key)}
                      className="h-7 w-7 p-0"
                      aria-expanded={isDayExpanded}
                      aria-label={
                        isDayExpanded ? 'Collapse day' : 'Expand day'
                      }
                    >
                      {isDayExpanded ? (
                        <ChevronDown className="h-4 w-4" aria-hidden="true" />
                      ) : (
                        <ChevronRight className="h-4 w-4" aria-hidden="true" />
                      )}
                    </Button>
                    <div className="text-sm font-medium">
                      {formatDate(day.usage_date)}
                    </div>
                    <Badge variant="secondary" className="text-xs">
                      {day.cluster_count_on_day} cluster
                      {day.cluster_count_on_day === 1 ? '' : 's'}
                    </Badge>
                  </div>
                  <div className="flex items-center space-x-4">
                    <div className="text-sm text-blue-600">
                      {cloudLabel}:{' '}
                      <PoolCloudCostCell cloudCost={day.cloud_cost} />
                    </div>
                    <div className="text-sm text-red-600">
                      DBU: {formatCurrency(day.databricks_cost)}
                    </div>
                    <div className="text-sm font-semibold">
                      Total: {formatCurrency(day.total_cost)}
                    </div>
                  </div>
                </div>
                {isDayExpanded && (
                  <DayClusterBreakdown
                    day={day}
                    cloudLabel={cloudLabel}
                    onSelectCluster={onSelectCluster}
                  />
                )}
              </div>
            );
          })}
      </div>
    </div>
  );
};

// Per-cluster expansion inside a day. Caps display at the top-25 clusters
// by `total_cost`, with an "Other (N) — $X" rollup row when the cap
// kicks in (see plan §5.2 / CP10 — pools that share fanout across
// hundreds of clusters per day are common on shared job substrate).
const DayClusterBreakdown = ({
  day,
  cloudLabel,
  onSelectCluster,
}: {
  day: InstancePoolDailySpend;
  cloudLabel: string;
  onSelectCluster: (clusterId: string) => void;
}) => {
  if (day.clusters.length === 0) {
    return (
      <div className="border-t p-3 bg-muted/40 text-xs text-muted-foreground">
        No cluster breakdown returned for this day.
      </div>
    );
  }

  // Server already orders by total_cost DESC per the §5.2 SQL; we
  // defensively re-sort in case future shapes drop the ORDER BY.
  const sorted = [...day.clusters].sort((a, b) => b.total_cost - a.total_cost);
  const visible = sorted.slice(0, CLUSTER_DISPLAY_CAP);
  const overflow = sorted.slice(CLUSTER_DISPLAY_CAP);
  const overflowCount = overflow.length;
  const overflowTotal = overflow.reduce((acc, c) => acc + c.total_cost, 0);
  const overflowDbu = overflow.reduce((acc, c) => acc + c.databricks_cost, 0);

  return (
    <div className="border-t bg-muted/40">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="px-4 py-2 text-xs">Cluster</TableHead>
            <TableHead className="px-4 py-2 text-xs text-right">
              {cloudLabel}
            </TableHead>
            <TableHead className="px-4 py-2 text-xs text-right">DBU</TableHead>
            <TableHead className="px-4 py-2 text-xs text-right">
              Total
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {visible.map((cluster) => (
            <ClusterRow
              key={cluster.cluster_id}
              cluster={cluster}
              onSelectCluster={onSelectCluster}
            />
          ))}
          {overflowCount > 0 && (
            <TableRow className="bg-background/60">
              <TableCell className="px-4 py-2 text-xs italic text-muted-foreground">
                Other clusters ({overflowCount})
                <span className="ml-2 text-muted-foreground/80 not-italic">
                  · top-{CLUSTER_DISPLAY_CAP} shown
                </span>
              </TableCell>
              <TableCell className="px-4 py-2 text-xs text-right">
                <PerClusterCloudCell />
              </TableCell>
              <TableCell className="px-4 py-2 text-xs text-right text-red-600">
                {formatCurrency(overflowDbu)}
              </TableCell>
              <TableCell className="px-4 py-2 text-xs text-right font-semibold">
                {formatCurrency(overflowTotal)}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
};

const ClusterRow = ({
  cluster,
  onSelectCluster,
}: {
  cluster: InstancePoolClusterSpend;
  onSelectCluster: (clusterId: string) => void;
}) => {
  // Plan §3.3 edge case — billing rows where `cluster_id IS NULL` are
  // bucketed under `__pool_overhead__` in the pipeline so they don't
  // get silently dropped. There's no real cluster to drill into, so
  // the row is non-clickable and italicized.
  const isPoolOverhead = cluster.cluster_id === '__pool_overhead__';

  return (
    <TableRow className="hover:bg-muted/50">
      <TableCell className="px-4 py-2">
        {isPoolOverhead ? (
          <span
            className="italic text-sm text-muted-foreground"
            title="DBU charged at the pool level, not attributable to a specific cluster."
          >
            Pool overhead
          </span>
        ) : (
          <button
            type="button"
            onClick={() => onSelectCluster(cluster.cluster_id)}
            className="text-sm font-mono text-blue-600 hover:text-blue-800 hover:underline truncate max-w-[300px] inline-block text-left"
            title={`View cluster details for ${cluster.cluster_id}`}
          >
            {cluster.cluster_id}
          </button>
        )}
      </TableCell>
      <TableCell className="px-4 py-2 text-right text-sm">
        <PerClusterCloudCell />
      </TableCell>
      <TableCell className="px-4 py-2 text-right text-sm text-red-600">
        {formatCurrency(cluster.databricks_cost)}
      </TableCell>
      <TableCell className="px-4 py-2 text-right text-sm font-semibold">
        {formatCurrency(cluster.total_cost)}
      </TableCell>
    </TableRow>
  );
};

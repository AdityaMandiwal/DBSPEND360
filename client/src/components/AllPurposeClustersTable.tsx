// By-Cluster table for the All-Purpose tab.
//
// Mirrors `GroupedJobTable.tsx` for the Job Clusters tab but adapted to the
// (cluster_id, owner, usage_date) model:
//
//   - Each top-level row is one all-purpose cluster in the window, with
//     denormalized owner + `data_security_mode` for attribution-quality
//     badge rendering (plan §3.2).
//   - Expanding a row reveals the per-day breakdown for that cluster.
//   - Clicking the cluster's name (or the Details icon) opens the
//     existing `ClusterDetailsModal` (re-used from `JobBreakdownModal`),
//     passing `clusterKind="all_purpose"` so the LLM analysis pulls cost
//     context from `dbspend360_total_all_purpose_spends`.
//
// See plan §4.1 / CP10 (`docs/plan_all_purpose_clusters_tab.md`).

import { Fragment, useEffect, useMemo, useState } from 'react';
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronRight as ChevronRightIcon,
  Eye,
  Search,
} from 'lucide-react';
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
import { useAllPurposeClustersByCluster } from '@/hooks/useAllPurposeClusters';
import { useDatabricksHost } from '@/hooks/useDatabricksHost';
import type {
  AllPurposeUserSpend,
  GroupedAllPurposeCluster,
} from '@/types/all-purpose';
import type { DateRange } from '@/types/job-spend';
import { useCloudPlatform } from '@/contexts/CloudPlatformContext';
import {
  useIsAws,
  useIsSegmentedPlatform,
  AWS_CLOUD_LABEL,
} from '@/hooks/useCloudGate';
import { formatCalendarDate } from '@/lib/utils';
import { ALL_PURPOSE_CLOUD_MISSING_NOTE } from '@/lib/all-purpose-display';
import { CloudCostCell } from '@/components/CloudCostCell';
import { OtherCostBreakdownModal } from './OtherCostBreakdownModal';
import { ClusterDetailsModal } from './JobBreakdownModal';

interface AllPurposeClustersTableProps {
  dateRange: DateRange;
  searchTerm: string;
}

// Plan §3.2 — `data_security_mode` -> attribution-quality badge.
// `Dedicated` is exact (single-user cluster, only the owner runs); other
// modes are approximate (shared / legacy / unknown).
type AttributionBadge = {
  label: string;
  className: string;
  tooltip: string;
};

const ATTRIBUTION_BADGES: Record<string, AttributionBadge> = {
  SINGLE_USER: {
    label: 'Dedicated',
    className:
      'bg-green-100 text-green-700 hover:bg-green-100 dark:bg-green-500/15 dark:text-green-300 dark:hover:bg-green-500/15',
    tooltip:
      'Single-user cluster — only the owner runs workloads here, so cost attribution is exact.',
  },
  USER_ISOLATION: {
    label: 'Shared',
    className:
      'bg-amber-100 text-amber-700 hover:bg-amber-100 dark:bg-amber-500/15 dark:text-amber-300 dark:hover:bg-amber-500/15',
    tooltip:
      'Shared cluster — multiple users may run on it, but cost rolls up to the owner. Attribution is approximate.',
  },
  LEGACY_PASSTHROUGH: {
    label: 'Legacy',
    className:
      'bg-gray-100 text-gray-700 hover:bg-gray-100 dark:bg-gray-500/15 dark:text-gray-300 dark:hover:bg-gray-500/15',
    tooltip: 'Legacy access mode. Attribution is approximate.',
  },
  LEGACY_SINGLE_USER: {
    label: 'Legacy',
    className:
      'bg-gray-100 text-gray-700 hover:bg-gray-100 dark:bg-gray-500/15 dark:text-gray-300 dark:hover:bg-gray-500/15',
    tooltip: 'Legacy single-user access mode. Attribution is approximate.',
  },
  LEGACY_TABLE_ACL: {
    label: 'Legacy',
    className:
      'bg-gray-100 text-gray-700 hover:bg-gray-100 dark:bg-gray-500/15 dark:text-gray-300 dark:hover:bg-gray-500/15',
    tooltip: 'Legacy table ACL access mode. Attribution is approximate.',
  },
  NONE: {
    label: 'Legacy',
    className:
      'bg-gray-100 text-gray-700 hover:bg-gray-100 dark:bg-gray-500/15 dark:text-gray-300 dark:hover:bg-gray-500/15',
    tooltip: 'No security mode set. Attribution is approximate.',
  },
};

const UNKNOWN_BADGE: AttributionBadge = {
  label: 'Unknown',
  className:
    'bg-muted text-muted-foreground hover:bg-muted dark:bg-muted/40 dark:text-muted-foreground',
  tooltip:
    'Security mode unknown — cluster snapshot may be missing. Attribution is approximate.',
};

const currencyFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const formatCurrency = (amount: number) => currencyFormatter.format(amount);

// EC2/EBS cloud cost cell — delegates to shared CloudCostCell.
const CloudCostValue = ({
  value,
  workspaceCovered = true,
}: {
  value: number | null | undefined;
  workspaceCovered?: boolean;
}) => (
  <CloudCostCell
    value={value}
    workspaceCovered={workspaceCovered}
    missingNote={ALL_PURPOSE_CLOUD_MISSING_NOTE}
  />
);

// `usage_date` is a calendar date (YYYY-MM-DD); `formatCalendarDate` anchors it
// to local midnight so it never rolls back a day on negative-UTC zones.
const formatDate = (dateStr: string) => formatCalendarDate(dateStr);

const PAGE_SIZE = 25;

export const AllPurposeClustersTable = ({
  dateRange,
  searchTerm,
}: AllPurposeClustersTableProps) => {
  const { config: cloudConfig } = useCloudPlatform();
  const isAws = useIsAws();
  const isSegmentedPlatform = useIsSegmentedPlatform();
  const { data: databricksHost } = useDatabricksHost();
  const [page, setPage] = useState(1);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [otherBreakdownCluster, setOtherBreakdownCluster] = useState<string | null>(
    null,
  );
  const [activeClusterModal, setActiveClusterModal] = useState<string | null>(null);

  // Reset to page 1 when the user changes filters so they don't land on an
  // out-of-range page after the result set shrinks. Same guard
  // `GroupedJobTable` uses for jobFilter / date range.
  useEffect(() => {
    setPage(1);
  }, [searchTerm, dateRange.start_date, dateRange.end_date]);

  const { data, isLoading, isFetching, error, refetch } = useAllPurposeClustersByCluster({
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

  const toggleRow = (clusterId: string) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(clusterId)) next.delete(clusterId);
      else next.add(clusterId);
      return next;
    });
  };

  const workspaceHost = useMemo(() => {
    if (!databricksHost) return null;
    // Strip any `/apps/<name>` suffix that's present in deployed
    // environments — the cluster URL lives at the workspace root.
    return databricksHost.replace(/\/apps\/[^\/]+$/, '');
  }, [databricksHost]);

  const clusterUrl = (clusterId: string) =>
    workspaceHost ? `${workspaceHost}/compute/clusters/${clusterId}` : '#';

  // Column count for colspan calcs in skeleton / empty / expanded rows.
  // The segmented Compute/Storage/Network trio renders only for Azure/GCP
  // (positive allowlist); AWS/Unknown/loading drop them for the single
  // EC2 / EBS cloud column (D4, D14).
  const columnCount = isSegmentedPlatform ? 9 : 6;

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
              <TableHead className="px-4">Cluster</TableHead>
              <TableHead className="px-4">Owner</TableHead>
              <TableHead className="px-4 text-right">Active Days</TableHead>
              {isSegmentedPlatform && (
                <>
                  <TableHead className="px-4 text-right">Compute</TableHead>
                  <TableHead className="px-4 text-right">Storage</TableHead>
                  <TableHead className="px-4 text-right">Network</TableHead>
                </>
              )}
              <TableHead className="px-4 text-right">
                {isAws
                  ? AWS_CLOUD_LABEL
                  : `Total ${cloudConfig?.compute_service || 'Cloud'}`}
              </TableHead>
              <TableHead className="px-4 text-right">DBU</TableHead>
              <TableHead className="px-4 text-right">Total Cost</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {error ? (
              <TableRow>
                <TableCell colSpan={columnCount + 1} className="h-24 text-center">
                  <ErrorState
                    compact
                    message={`Error loading all-purpose cluster data: ${error.message}`}
                    onRetry={() => refetch()}
                  />
                </TableCell>
              </TableRow>
            ) : isInitialLoading ? (
              [...Array(8)].map((_, i) => (
                <TableRow key={i}>
                  {[...Array(columnCount + 1)].map((_, j) => (
                    <TableCell key={j} className="px-4">
                      <Skeleton className="h-8 w-full" />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : rows.length > 0 ? (
              rows.map((cluster) => {
                const isExpanded = expandedRows.has(cluster.cluster_id);
                const badge = pickAttributionBadge(cluster.data_security_mode);
                const hasName =
                  !!cluster.cluster_name && cluster.cluster_name.trim().length > 0;
                const displayName = hasName
                  ? cluster.cluster_name!
                  : `Cluster ${cluster.cluster_id}`;
                const isUnknownOwner = cluster.owner_user_id === '__unknown__';
                return (
                  <Fragment key={cluster.cluster_id}>
                    <TableRow className="hover:bg-muted/50">
                      <TableCell className="px-2">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => toggleRow(cluster.cluster_id)}
                          className="h-8 w-8 p-0"
                          aria-expanded={isExpanded}
                          aria-label={isExpanded ? 'Collapse row' : 'Expand row'}
                        >
                          {isExpanded ? (
                            <ChevronDown className="h-4 w-4" aria-hidden="true" />
                          ) : (
                            <ChevronRightIcon className="h-4 w-4" aria-hidden="true" />
                          )}
                        </Button>
                      </TableCell>
                      <TableCell className="px-4 max-w-[260px]">
                        <button
                          type="button"
                          onClick={() => setActiveClusterModal(cluster.cluster_id)}
                          className="text-left truncate font-medium text-blue-600 hover:text-blue-800 hover:underline"
                          title={`View details for ${cluster.cluster_id}`}
                        >
                          <span className={hasName ? '' : 'font-mono'}>
                            {displayName}
                          </span>
                        </button>
                        <div className="text-xs text-muted-foreground font-mono truncate">
                          {workspaceHost ? (
                            <a
                              href={clusterUrl(cluster.cluster_id)}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="hover:underline"
                              title="Open in Databricks"
                            >
                              {cluster.cluster_id}
                            </a>
                          ) : (
                            <span>{cluster.cluster_id}</span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="px-4 max-w-[220px]">
                        <div
                          className={`text-sm truncate ${
                            isUnknownOwner ? 'italic text-muted-foreground' : ''
                          }`}
                          title={
                            isUnknownOwner
                              ? 'Owner could not be resolved (snapshot row missing)'
                              : cluster.owner_user_id
                          }
                        >
                          {isUnknownOwner ? 'Unknown' : cluster.owner_user_id}
                        </div>
                        <div className="mt-1">
                          <Badge
                            variant="secondary"
                            className={`text-[10px] ${badge.className}`}
                            title={badge.tooltip}
                          >
                            {badge.label}
                          </Badge>
                        </div>
                      </TableCell>
                      <TableCell className="px-4 text-right text-sm">
                        {cluster.active_days}
                      </TableCell>
                      {isSegmentedPlatform && (
                        <>
                          <TableCell className="px-4 text-right font-medium text-blue-600">
                            {cluster.total_compute_cost != null
                              ? formatCurrency(cluster.total_compute_cost)
                              : '—'}
                          </TableCell>
                          <TableCell className="px-4 text-right font-medium text-green-600">
                            {cluster.total_storage_cost != null
                              ? formatCurrency(cluster.total_storage_cost)
                              : '—'}
                          </TableCell>
                          <TableCell className="px-4 text-right font-medium text-amber-600">
                            {cluster.total_network_cost != null
                              ? formatCurrency(cluster.total_network_cost)
                              : '—'}
                          </TableCell>
                        </>
                      )}
                      <TableCell className="px-4 text-right font-medium text-blue-600">
                        <CloudCostValue
                          value={cluster.total_cloud_cost}
                          workspaceCovered={cluster.workspace_covered}
                        />
                        {/* "Other (Unclassified)" drill-down is hidden on
                            AWS/Unknown (D7) — only segmented platforms expose it. */}
                        {isSegmentedPlatform &&
                          (cluster.total_other_cost ?? 0) > 0 && (
                            <button
                              type="button"
                              className="text-xs text-muted-foreground cursor-pointer hover:text-foreground inline-flex items-center gap-0.5 ml-1"
                              onClick={(e) => {
                                e.stopPropagation();
                                setOtherBreakdownCluster(cluster.cluster_id);
                              }}
                              title="Click to view breakdown of unclassified costs"
                              aria-label="View breakdown of unclassified costs"
                            >
                              (+{formatCurrency(cluster.total_other_cost ?? 0)}{' '}
                              other <Search className="h-2.5 w-2.5" aria-hidden="true" />)
                            </button>
                          )}
                      </TableCell>
                      <TableCell className="px-4 text-right font-medium text-red-600">
                        {formatCurrency(cluster.total_databricks_cost)}
                      </TableCell>
                      <TableCell className="px-4 text-right">
                        <div className="font-bold text-lg">
                          {formatCurrency(cluster.total_cost)}
                        </div>
                        {cluster.total_cost > 1000 && (
                          <Badge variant="destructive" className="text-xs">
                            High Cost
                          </Badge>
                        )}
                      </TableCell>
                    </TableRow>
                    {isExpanded && (
                      <TableRow
                        key={`${cluster.cluster_id}-expanded`}
                        className="bg-muted/30"
                      >
                        <TableCell colSpan={columnCount + 1} className="p-0">
                          <ClusterDayBreakdown
                            cluster={cluster}
                            isSegmentedPlatform={isSegmentedPlatform}
                            computeLabel={
                              isAws
                                ? AWS_CLOUD_LABEL
                                : cloudConfig?.compute_service || 'Cloud'
                            }
                            onOpenDetails={() =>
                              setActiveClusterModal(cluster.cluster_id)
                            }
                          />
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                );
              })
            ) : (
              <TableRow>
                <TableCell colSpan={columnCount + 1} className="h-24 text-center">
                  <div className="text-muted-foreground">
                    No all-purpose clusters found for the selected filters.
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
            Showing {rows.length} cluster{rows.length === 1 ? '' : 's'} of{' '}
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

      {/* Cluster details modal (re-used; threads cluster_kind="all_purpose"
          so the LLM cost context comes from the all-purpose rollup). */}
      {activeClusterModal && (
        <ClusterDetailsModal
          clusterId={activeClusterModal}
          isOpen
          onClose={() => setActiveClusterModal(null)}
          clusterKind="all_purpose"
        />
      )}

      {/* Other-cost breakdown modal — only mounted for segmented platforms;
          its only trigger is hidden on AWS/Unknown (D7). */}
      {isSegmentedPlatform && otherBreakdownCluster && (
        <OtherCostBreakdownModal
          dateRange={dateRange}
          clusterId={otherBreakdownCluster}
          isOpen
          onClose={() => setOtherBreakdownCluster(null)}
        />
      )}
    </div>
  );
};

// Per-day expansion panel for one cluster. The `users` array on a
// `GroupedAllPurposeCluster` is the per-day breakdown (under v1 owner
// attribution every day has one user — see plan §3.3); each entry maps
// to one row here.
const ClusterDayBreakdown = ({
  cluster,
  isSegmentedPlatform,
  computeLabel,
  onOpenDetails,
}: {
  cluster: GroupedAllPurposeCluster;
  isSegmentedPlatform: boolean;
  computeLabel: string;
  onOpenDetails: () => void;
}) => {
  if (cluster.users.length === 0) {
    return (
      <div className="p-4 border-l-4 border-l-blue-500 bg-muted/20 text-sm text-muted-foreground">
        No daily breakdown returned for this cluster.
      </div>
    );
  }

  return (
    <div className="p-4 border-l-4 border-l-blue-500 bg-muted/20">
      <div className="flex items-center justify-between mb-3">
        <h4 className="font-semibold text-sm text-muted-foreground">
          Daily breakdown ({cluster.users.length} day
          {cluster.users.length === 1 ? '' : 's'})
        </h4>
        <Button size="sm" variant="outline" className="h-7" onClick={onOpenDetails}>
          <Eye className="h-3 w-3 mr-1" /> Cluster details & analysis
        </Button>
      </div>
      <div className="space-y-2">
        {[...cluster.users]
          .sort((a, b) => a.usage_date.localeCompare(b.usage_date))
          .map((day: AllPurposeUserSpend) => (
            <div
              key={`${day.cluster_id}-${day.user_id}-${day.usage_date}`}
              className="flex items-center justify-between p-3 bg-background rounded-md border"
            >
              <div className="flex items-center space-x-4">
                <div className="text-sm font-medium">{formatDate(day.usage_date)}</div>
                <div className="text-xs text-muted-foreground truncate max-w-[200px]">
                  {day.user_id === '__unknown__' ? (
                    <span className="italic">Unknown owner</span>
                  ) : (
                    day.user_id
                  )}
                </div>
              </div>
              <div className="flex items-center space-x-4">
                {/* Positive allowlist (D14): segmented spans render only for
                    Azure/GCP. AWS/Unknown/loading show the single EC2 / EBS
                    (cloud_cost) line — never the data-shape branch. */}
                {isSegmentedPlatform ? (
                  <>
                    <div className="text-sm text-blue-600">
                      Compute: {formatCurrency(day.compute_cost ?? 0)}
                    </div>
                    <div className="text-sm text-green-600">
                      Storage: {formatCurrency(day.storage_cost ?? 0)}
                    </div>
                    <div className="text-sm text-amber-600">
                      Network: {formatCurrency(day.network_cost ?? 0)}
                    </div>
                    {(day.other_cost ?? 0) > 0 && (
                      <div className="text-sm text-muted-foreground">
                        Other: {formatCurrency(day.other_cost ?? 0)}
                      </div>
                    )}
                  </>
                ) : (
                  <div className="text-sm text-blue-600">
                    {computeLabel}:{' '}
                    <CloudCostValue
                      value={day.cloud_cost}
                      workspaceCovered={day.workspace_covered}
                    />
                  </div>
                )}
                <div className="text-sm text-red-600">
                  DBU: {formatCurrency(day.databricks_cost)}
                </div>
                <div className="text-sm font-semibold">
                  Total: {formatCurrency(day.total_cost)}
                </div>
              </div>
            </div>
          ))}
      </div>
    </div>
  );
};

const pickAttributionBadge = (
  mode: string | null | undefined,
): AttributionBadge => {
  if (!mode) return UNKNOWN_BADGE;
  return ATTRIBUTION_BADGES[mode] ?? UNKNOWN_BADGE;
};

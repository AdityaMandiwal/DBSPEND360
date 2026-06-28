// By-User chargeback table for the All-Purpose tab.
//
// One row per cluster owner (user) in the window. Expanding a row reveals
// the per-cluster breakdown for that user — clicking a cluster opens the
// reused `ClusterDetailsModal` with `clusterKind="all_purpose"`.
//
// Note that `user_active_days` is the DISTINCT days the user was active
// across ALL clusters (not summed across clusters) — see plan §5.2 for
// why summing would double-count.

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
import { useAllPurposeClustersByUser } from '@/hooks/useAllPurposeClusters';
import { useDatabricksHost } from '@/hooks/useDatabricksHost';
import type {
  AllPurposeClusterSpend,
  GroupedAllPurposeUser,
} from '@/types/all-purpose';
import type { DateRange } from '@/types/job-spend';
import { useCloudPlatform } from '@/contexts/CloudPlatformContext';
import {
  useIsAws,
  useIsSegmentedPlatform,
  AWS_CLOUD_LABEL,
} from '@/hooks/useCloudGate';
import { ClusterDetailsModal } from './JobBreakdownModal';
import { OtherCostBreakdownModal } from './OtherCostBreakdownModal';

interface AllPurposeUsersTableProps {
  dateRange: DateRange;
  searchTerm: string;
}

const currencyFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const formatCurrency = (n: number) => currencyFormatter.format(n);

const PAGE_SIZE = 25;

export const AllPurposeUsersTable = ({
  dateRange,
  searchTerm,
}: AllPurposeUsersTableProps) => {
  const { config: cloudConfig } = useCloudPlatform();
  const isAws = useIsAws();
  const isSegmentedPlatform = useIsSegmentedPlatform();
  const { data: databricksHost } = useDatabricksHost();
  const [page, setPage] = useState(1);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [activeClusterModal, setActiveClusterModal] = useState<string | null>(null);
  const [otherBreakdownCluster, setOtherBreakdownCluster] = useState<string | null>(
    null,
  );

  useEffect(() => {
    setPage(1);
  }, [searchTerm, dateRange.start_date, dateRange.end_date]);

  const { data, isLoading, isFetching, error, refetch } = useAllPurposeClustersByUser({
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

  const toggleRow = (userId: string) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(userId)) next.delete(userId);
      else next.add(userId);
      return next;
    });
  };

  const workspaceHost = useMemo(() => {
    if (!databricksHost) return null;
    return databricksHost.replace(/\/apps\/[^\/]+$/, '');
  }, [databricksHost]);

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
              <TableHead className="px-4">User (Owner)</TableHead>
              <TableHead className="px-4 text-right">Clusters</TableHead>
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
                    message={`Error loading by-user data: ${error.message}`}
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
              rows.map((user) => {
                const isExpanded = expandedRows.has(user.user_id);
                const isUnknown = user.user_id === '__unknown__';
                return (
                  <Fragment key={user.user_id}>
                    <TableRow className="hover:bg-muted/50">
                      <TableCell className="px-2">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => toggleRow(user.user_id)}
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
                      <TableCell className="px-4 max-w-[280px]">
                        <div
                          className={`text-sm truncate ${
                            isUnknown ? 'italic text-muted-foreground' : 'font-medium'
                          }`}
                          title={
                            isUnknown
                              ? 'Owner could not be resolved (cluster snapshot missing)'
                              : user.user_id
                          }
                        >
                          {isUnknown ? 'Unknown' : user.user_id}
                        </div>
                      </TableCell>
                      <TableCell className="px-4 text-right">
                        <Badge variant="secondary" className="text-xs">
                          {user.cluster_count}
                        </Badge>
                      </TableCell>
                      <TableCell className="px-4 text-right text-sm">
                        {user.user_active_days}
                      </TableCell>
                      {isSegmentedPlatform && (
                        <>
                          <TableCell className="px-4 text-right font-medium text-blue-600">
                            {user.total_compute_cost != null
                              ? formatCurrency(user.total_compute_cost)
                              : '—'}
                          </TableCell>
                          <TableCell className="px-4 text-right font-medium text-green-600">
                            {user.total_storage_cost != null
                              ? formatCurrency(user.total_storage_cost)
                              : '—'}
                          </TableCell>
                          <TableCell className="px-4 text-right font-medium text-amber-600">
                            {user.total_network_cost != null
                              ? formatCurrency(user.total_network_cost)
                              : '—'}
                          </TableCell>
                        </>
                      )}
                      <TableCell className="px-4 text-right font-medium text-blue-600">
                        {formatCurrency(user.total_cloud_cost)}
                      </TableCell>
                      <TableCell className="px-4 text-right font-medium text-red-600">
                        {formatCurrency(user.total_databricks_cost)}
                      </TableCell>
                      <TableCell className="px-4 text-right">
                        <div className="font-bold text-lg">
                          {formatCurrency(user.total_cost)}
                        </div>
                        {user.total_cost > 1000 && (
                          <Badge variant="destructive" className="text-xs">
                            High Cost
                          </Badge>
                        )}
                      </TableCell>
                    </TableRow>
                    {isExpanded && (
                      <TableRow
                        key={`${user.user_id}-expanded`}
                        className="bg-muted/30"
                      >
                        <TableCell colSpan={columnCount + 1} className="p-0">
                          <UserClusterBreakdown
                            user={user}
                            workspaceHost={workspaceHost}
                            isSegmentedPlatform={isSegmentedPlatform}
                            computeLabel={
                              isAws
                                ? AWS_CLOUD_LABEL
                                : cloudConfig?.compute_service || 'Cloud'
                            }
                            onSelectCluster={setActiveClusterModal}
                            onSelectOther={setOtherBreakdownCluster}
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
                    No users found for the selected filters.
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
            Showing {rows.length} user{rows.length === 1 ? '' : 's'} of {totalCount}{' '}
            total
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

      {activeClusterModal && (
        <ClusterDetailsModal
          clusterId={activeClusterModal}
          isOpen
          onClose={() => setActiveClusterModal(null)}
          clusterKind="all_purpose"
        />
      )}

      {/* Other-cost breakdown modal — only mounted for segmented platforms;
          its only trigger (the per-cluster "Other" line) is rendered only on
          Azure/GCP, matching the By-Cluster table (D7 / plan §5.4). */}
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

// Per-cluster expansion for one user. Clicking a cluster name opens the
// cluster details modal (which reuses /api/cluster/{id}/details +
// /api/cluster/{id}/analyze, threaded with clusterKind="all_purpose").
const UserClusterBreakdown = ({
  user,
  workspaceHost,
  isSegmentedPlatform,
  computeLabel,
  onSelectCluster,
  onSelectOther,
}: {
  user: GroupedAllPurposeUser;
  workspaceHost: string | null;
  isSegmentedPlatform: boolean;
  computeLabel: string;
  onSelectCluster: (clusterId: string) => void;
  onSelectOther: (clusterId: string) => void;
}) => {
  if (user.clusters.length === 0) {
    return (
      <div className="p-4 border-l-4 border-l-purple-500 bg-muted/20 text-sm text-muted-foreground">
        No cluster breakdown returned for this user.
      </div>
    );
  }

  // `user.cluster_count` is the authoritative DISTINCT cluster count for the
  // window. `user.clusters` is server-truncated to the top-N by cost (see
  // `_get_batch_user_clusters` in databricks_service.py), so we use
  // `cluster_count` for the heading and surface a hint when truncated.
  const isTruncated = user.clusters.length < user.cluster_count;

  return (
    <div className="p-4 border-l-4 border-l-purple-500 bg-muted/20">
      <h4 className="font-semibold mb-1 text-sm text-muted-foreground">
        Clusters owned ({user.cluster_count})
      </h4>
      {isTruncated && (
        <p className="mb-3 text-xs text-muted-foreground italic">
          Showing top {user.clusters.length} by cost
        </p>
      )}
      <div className="space-y-2">
        {[...user.clusters]
          .sort((a, b) => b.total_cost - a.total_cost)
          .map((cluster: AllPurposeClusterSpend) => {
            const hasName =
              !!cluster.cluster_name &&
              cluster.cluster_name.trim().length > 0;
            const displayName = hasName
              ? cluster.cluster_name!
              : `Cluster ${cluster.cluster_id}`;
            return (
              <div
                key={cluster.cluster_id}
                className="flex items-center justify-between p-3 bg-background rounded-md border hover:bg-muted/50 transition-colors"
              >
                <div className="flex items-center space-x-4 min-w-0">
                  <button
                    type="button"
                    onClick={() => onSelectCluster(cluster.cluster_id)}
                    className="text-left text-sm font-medium text-blue-600 hover:text-blue-800 hover:underline truncate max-w-[260px]"
                    title={`View details for ${cluster.cluster_id}`}
                  >
                    <span className={hasName ? '' : 'font-mono'}>{displayName}</span>
                  </button>
                  <div className="text-xs text-muted-foreground font-mono truncate max-w-[200px]">
                    {workspaceHost ? (
                      <a
                        href={`${workspaceHost}/compute/clusters/${cluster.cluster_id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="hover:underline"
                        title="Open in Databricks"
                      >
                        {cluster.cluster_id}
                      </a>
                    ) : (
                      cluster.cluster_id
                    )}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {cluster.cluster_active_days} day
                    {cluster.cluster_active_days === 1 ? '' : 's'}
                  </div>
                </div>
                <div className="flex items-center space-x-4 shrink-0">
                  {/* Positive allowlist (D14): segmented spans render only for
                      Azure/GCP. AWS/Unknown/loading show the single EC2 / EBS
                      (cloud_cost) line — never the data-shape branch, and never
                      the `EC2:` label from compute_service. */}
                  {isSegmentedPlatform ? (
                    <>
                      <div className="text-sm text-blue-600">
                        Compute: {formatCurrency(cluster.compute_cost ?? 0)}
                      </div>
                      <div className="text-sm text-green-600">
                        Storage: {formatCurrency(cluster.storage_cost ?? 0)}
                      </div>
                      <div className="text-sm text-amber-600">
                        Network: {formatCurrency(cluster.network_cost ?? 0)}
                      </div>
                      {(cluster.other_cost ?? 0) > 0 && (
                        <button
                          type="button"
                          className="text-sm text-muted-foreground cursor-pointer hover:text-foreground inline-flex items-center gap-0.5"
                          onClick={() => onSelectOther(cluster.cluster_id)}
                          title="Click to view breakdown of unclassified costs"
                          aria-label="View breakdown of unclassified costs"
                        >
                          Other: {formatCurrency(cluster.other_cost ?? 0)}{' '}
                          <Search className="h-2.5 w-2.5" aria-hidden="true" />
                        </button>
                      )}
                    </>
                  ) : (
                    <div className="text-sm text-blue-600">
                      {computeLabel}: {formatCurrency(cluster.cloud_cost)}
                    </div>
                  )}
                  <div className="text-sm text-red-600">
                    DBU: {formatCurrency(cluster.databricks_cost)}
                  </div>
                  <div className="text-sm font-semibold">
                    Total: {formatCurrency(cluster.total_cost)}
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7"
                    onClick={() => onSelectCluster(cluster.cluster_id)}
                  >
                    <Eye className="h-3 w-3 mr-1" /> Details
                  </Button>
                </div>
              </div>
            );
          })}
      </div>
    </div>
  );
};

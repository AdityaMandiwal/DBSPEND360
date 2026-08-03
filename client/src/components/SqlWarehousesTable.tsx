// By-Warehouse table for the SQL Warehouses tab with single-level row
// expansion (plan §3d):
//
//   Level 0 (warehouse row) — one row per warehouse in the window, with
//                             metadata denormalized from
//                             `system.compute.warehouses`. The warehouse name
//                             is clickable and opens
//                             `SqlWarehouseDetailsModal`; a neutral
//                             three-state badge sits under it.
//   Level 1 (warehouse→day) — expand to see per-day DBU / total rows. The
//                             rollup is already at `(warehouse_id,
//                             usage_date)` grain, so the sum of `days[]`
//                             equals the row total by construction.
//
// There is no cloud-cost column: SQL Warehouses run on Databricks-managed
// compute, so DBU IS the complete cost. Rows arrive sorted by total_cost
// descending from the backend.

import { Fragment, useEffect, useState } from 'react';
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronRight as ChevronRightIcon,
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
import { useSqlWarehouses } from '@/hooks/useSqlWarehouses';
import {
  formatCurrency,
  warehouseTypeBadgeClasses,
  warehouseTypeLabel,
} from '@/lib/sql-warehouse-display';
import type {
  GroupedSqlWarehouse,
  SqlWarehouseDailySpend,
} from '@/types/sql-warehouse';
import type { DateRange } from '@/types/job-spend';
import {
  formatCalendarDate,
  formatLocalISODate,
  HIGH_COST_USD,
} from '@/lib/utils';
import { SqlWarehouseDetailsModal } from './SqlWarehouseDetailsModal';

interface SqlWarehousesTableProps {
  dateRange: DateRange;
  searchTerm: string;
}

// `usage_date` is a calendar date (YYYY-MM-DD); `formatCalendarDate` anchors it
// to local midnight so it never rolls back a day on negative-UTC zones.
const formatDate = (dateStr: string) => formatCalendarDate(dateStr);

// `warehouse_deleted_at` is a timestamp; render its LOCAL calendar day as ISO
// so the badge label doesn't shift a day vs. the user's timezone.
const formatBadgeDate = (dateStr?: string | null): string | null =>
  dateStr ? formatLocalISODate(dateStr) : null;

const PAGE_SIZE = 25;

export const SqlWarehousesTable = ({
  dateRange,
  searchTerm,
}: SqlWarehousesTableProps) => {
  const [page, setPage] = useState(1);
  const [expandedWarehouses, setExpandedWarehouses] = useState<Set<string>>(
    new Set(),
  );
  const [activeModal, setActiveModal] = useState<GroupedSqlWarehouse | null>(
    null,
  );

  // Reset to page 1 when any filter changes so the user doesn't land on an
  // out-of-range page after the result set shrinks.
  useEffect(() => {
    setPage(1);
  }, [searchTerm, dateRange.start_date, dateRange.end_date]);

  const { data, isLoading, isFetching, error, refetch } = useSqlWarehouses({
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

  const toggleWarehouse = (id: string) => {
    setExpandedWarehouses((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // 6 data columns + 1 expander.
  const columnCount = 7;

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
              <TableHead className="px-4">Warehouse</TableHead>
              <TableHead className="px-4">Type</TableHead>
              <TableHead className="px-4">Size</TableHead>
              <TableHead className="px-4 text-right">Active Days</TableHead>
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
                    message={`Error loading SQL warehouse data: ${error.message}`}
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
              rows.map((warehouse) => {
                const isExpanded = expandedWarehouses.has(
                  warehouse.warehouse_id,
                );
                const hasName =
                  !!warehouse.warehouse_name &&
                  warehouse.warehouse_name.trim().length > 0;
                const displayName = hasName
                  ? warehouse.warehouse_name!
                  : `Warehouse ${warehouse.warehouse_id}`;
                return (
                  <Fragment key={warehouse.warehouse_id}>
                    <TableRow className="hover:bg-muted/50">
                      <TableCell className="px-2">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() =>
                            toggleWarehouse(warehouse.warehouse_id)
                          }
                          className="h-8 w-8 p-0"
                          aria-expanded={isExpanded}
                          aria-label={
                            isExpanded
                              ? 'Collapse warehouse'
                              : 'Expand warehouse'
                          }
                        >
                          {isExpanded ? (
                            <ChevronDown className="h-4 w-4" aria-hidden="true" />
                          ) : (
                            <ChevronRightIcon
                              className="h-4 w-4"
                              aria-hidden="true"
                            />
                          )}
                        </Button>
                      </TableCell>
                      <TableCell className="px-4 max-w-[280px]">
                        <button
                          type="button"
                          onClick={() => setActiveModal(warehouse)}
                          className="text-left truncate font-medium text-blue-600 hover:text-blue-800 hover:underline"
                          title={`View details for ${warehouse.warehouse_id}`}
                        >
                          <span className={hasName ? '' : 'font-mono'}>
                            {displayName}
                          </span>
                        </button>
                        <div
                          className="text-xs text-muted-foreground font-mono truncate"
                          title={warehouse.warehouse_id}
                        >
                          {warehouse.warehouse_id}
                        </div>
                        <WarehouseStateBadge warehouse={warehouse} />
                      </TableCell>
                      <TableCell className="px-4">
                        <Badge
                          variant="secondary"
                          className={`text-[10px] ${warehouseTypeBadgeClasses(
                            warehouse.warehouse_type,
                          )}`}
                        >
                          {warehouseTypeLabel(warehouse.warehouse_type)}
                        </Badge>
                      </TableCell>
                      <TableCell className="px-4">
                        <div className="text-sm">
                          {warehouse.warehouse_size ?? (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="px-4 text-right text-sm">
                        {warehouse.active_days}
                      </TableCell>
                      <TableCell className="px-4 text-right font-medium text-red-600">
                        {formatCurrency(warehouse.total_databricks_cost)}
                      </TableCell>
                      <TableCell className="px-4 text-right">
                        <div className="font-bold text-lg">
                          {formatCurrency(warehouse.total_cost)}
                        </div>
                        {warehouse.total_cost > HIGH_COST_USD && (
                          <Badge variant="destructive" className="text-xs">
                            High Cost
                          </Badge>
                        )}
                      </TableCell>
                    </TableRow>
                    {isExpanded && (
                      <TableRow
                        key={`${warehouse.warehouse_id}-expanded`}
                        className="bg-muted/30"
                      >
                        <TableCell colSpan={columnCount} className="p-0">
                          <WarehouseDayBreakdown warehouse={warehouse} />
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
                    No SQL warehouses found for the selected filters.
                  </div>
                  <div className="text-xs text-muted-foreground mt-2">
                    Try widening the date range or clearing the search.
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
            Showing {rows.length} warehouse{rows.length === 1 ? '' : 's'} of{' '}
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
                <span
                  className="text-xs text-muted-foreground"
                  aria-live="polite"
                >
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

      {activeModal && (
        <SqlWarehouseDetailsModal
          warehouseId={activeModal.warehouse_id}
          costSummary={{
            totalCost: activeModal.total_cost,
            databricksCost: activeModal.total_databricks_cost,
            activeDays: activeModal.active_days,
            startDate: dateRange.start_date,
            endDate: dateRange.end_date,
          }}
          isOpen
          onClose={() => setActiveModal(null)}
        />
      )}
    </div>
  );
};

// Three-state metadata badge:
//   - active                 : no badge
//   - "Deleted YYYY-MM-DD"   : snapshot exists but `delete_time` set (amber)
//   - "Metadata unavailable" : no `system.compute.warehouses` row — the case
//                              for roughly three quarters of warehouses, so
//                              it renders small and NEUTRAL grey, not as a
//                              warning
const WarehouseStateBadge = ({
  warehouse,
}: {
  warehouse: GroupedSqlWarehouse;
}) => {
  if (warehouse.warehouse_deleted_at) {
    const dateLabel = formatBadgeDate(warehouse.warehouse_deleted_at);
    return (
      <Badge
        variant="secondary"
        className="mt-1 text-[10px] bg-amber-100 text-amber-700 hover:bg-amber-100 dark:bg-amber-500/15 dark:text-amber-300 dark:hover:bg-amber-500/15"
        title="Warehouse was deleted; metadata is as of that date. Cost data is still accurate."
      >
        Deleted {dateLabel}
      </Badge>
    );
  }
  if (warehouse.metadata_missing) {
    return (
      <Badge
        variant="secondary"
        className="mt-1 text-[10px] bg-muted text-muted-foreground hover:bg-muted"
        title="No row in system.compute.warehouses — common for older warehouses or ones outside the table's retention window. Cost data is still accurate."
      >
        Metadata unavailable
      </Badge>
    );
  }
  return null;
};

// Per-day expansion panel for one warehouse. One row per usage_date; the
// invariant "sum of days[].total_cost == warehouse total_cost" is structural.
const WarehouseDayBreakdown = ({
  warehouse,
}: {
  warehouse: GroupedSqlWarehouse;
}) => {
  if (warehouse.days.length === 0) {
    return (
      <div className="p-4 border-l-4 border-l-blue-500 bg-muted/20 text-sm text-muted-foreground">
        No daily breakdown returned for this warehouse.
      </div>
    );
  }

  return (
    <div className="p-4 border-l-4 border-l-blue-500 bg-muted/20">
      <h4 className="font-semibold text-sm text-muted-foreground mb-3">
        Daily breakdown ({warehouse.days.length} day
        {warehouse.days.length === 1 ? '' : 's'})
      </h4>
      <div className="space-y-2">
        {[...warehouse.days]
          .sort((a, b) => a.usage_date.localeCompare(b.usage_date))
          .map((day) => (
            <DayRow
              key={`${warehouse.warehouse_id}|${day.usage_date}`}
              day={day}
            />
          ))}
      </div>
    </div>
  );
};

const DayRow = ({ day }: { day: SqlWarehouseDailySpend }) => (
  <div className="rounded-md border bg-background overflow-hidden">
    <div className="flex items-center justify-between p-3">
      <div className="flex items-center space-x-3">
        <div className="text-sm font-medium">{formatDate(day.usage_date)}</div>
        {day.warehouse_type && (
          <Badge
            variant="secondary"
            className={`text-[10px] ${warehouseTypeBadgeClasses(
              day.warehouse_type,
            )}`}
          >
            {warehouseTypeLabel(day.warehouse_type)}
          </Badge>
        )}
        {day.sku_name && (
          <span
            className="text-xs text-muted-foreground font-mono truncate max-w-[280px]"
            title={day.sku_name}
          >
            {day.sku_name}
          </span>
        )}
      </div>
      <div className="flex items-center space-x-4">
        <div className="text-sm text-red-600">
          DBU: {formatCurrency(day.databricks_cost)}
        </div>
        <div className="text-sm font-semibold">
          Total: {formatCurrency(day.total_cost)}
        </div>
      </div>
    </div>
  </div>
);

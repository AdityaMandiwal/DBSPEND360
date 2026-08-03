// SqlWarehousesDashboard — top-level container for the SQL Warehouses tab.
//
// Mirrors `PipelineDashboard.tsx` (single view, no inner `<Tabs>`) but is
// simpler in two ways (plan §3d): there is no workload-type chip filter, and
// there is no cloud-cost surface anywhere. All three warehouse types run on
// Databricks-managed compute, so DBU IS the complete cost — the only honesty
// caveat left is that DBU is list price, which the table footnote discloses.

import { useEffect, useMemo, useRef, useState } from 'react';
import { format, subDays } from 'date-fns';
import { AlertTriangle, Database, DollarSign, Layers, Search } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorState } from '@/components/ui/error-state';
import { CoverageBanner } from './CoverageBanner';
import { SqlWarehousesTable } from './SqlWarehousesTable';
import {
  useSqlWarehouseSummary,
  useTopSqlWarehouses,
} from '@/hooks/useSqlWarehouses';
import { useDatePresets } from '@/hooks/useJobSpends';
import {
  formatCurrency,
  warehouseTypeBadgeClasses,
  warehouseTypeLabel,
} from '@/lib/sql-warehouse-display';
import { cn, formatCalendarDate, isInvalidDateRange } from '@/lib/utils';
import type { DateRange } from '@/types/job-spend';

const integerFormatter = new Intl.NumberFormat('en-US');
const formatNumber = (n: number) => integerFormatter.format(n);
const formatPercent = (part: number, whole: number) =>
  whole > 0 ? `${Math.round((part / whole) * 100)}%` : '0%';

const SqlWarehousesDashboard = () => {
  // Match the other four tabs' default window (last 30 days) so users pivoting
  // between tabs see consistent scope until they pick a preset.
  const defaultDateRange: DateRange = {
    start_date: format(subDays(new Date(), 30), 'yyyy-MM-dd'),
    end_date: format(new Date(), 'yyyy-MM-dd'),
  };

  const [dateRange, setDateRange] = useState<DateRange>(defaultDateRange);
  const [searchTerm, setSearchTerm] = useState<string>('');

  return (
    <div className="space-y-6">
      <CoverageBanner tab="sql_warehouse" />
      <SqlWarehouseSummaryCards dateRange={dateRange} />

      <Card>
        <CardHeader>
          <CardTitle>Filters & Controls</CardTitle>
        </CardHeader>
        <CardContent>
          <SqlWarehouseFilterControls
            dateRange={dateRange}
            onDateRangeChange={setDateRange}
            searchTerm={searchTerm}
            onSearchTermChange={setSearchTerm}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>SQL Warehouse Spending</CardTitle>
          <p className="text-sm text-muted-foreground mt-1">
            One row per SQL warehouse. Click the arrow to expand and see daily
            spend; click the warehouse name for config and AI analysis.
          </p>
          <p className="text-xs text-muted-foreground mt-2">
            SQL Warehouses run on Databricks-managed compute (Classic, Pro, and
            Serverless), so the DBU figure is the complete cost — there is no
            separate VM line to add. DBU is list price and excludes
            account-level discounts (list ≠ your invoice). Most warehouses have
            no configuration snapshot in{' '}
            <span className="font-mono">system.compute.warehouses</span>; those
            rows are labeled "Metadata unavailable" and their cost figures are
            still exact.
          </p>
        </CardHeader>
        <CardContent>
          {/* Remount the table on any filter change so pagination + expansion
              reset cleanly in one render pass. */}
          <SqlWarehousesTable
            key={`${dateRange.start_date}|${dateRange.end_date}|${searchTerm}`}
            dateRange={dateRange}
            searchTerm={searchTerm}
          />
        </CardContent>
      </Card>
    </div>
  );
};

// KPI strip + type breakdown + top-5 highlight.
//
// Both splits from the summary endpoint are exhaustive three-bucket splits
// (classic + pro + serverless), so the counts and the `$` figures each sum to
// their total and the wording never implies a two-bucket split.
const SqlWarehouseSummaryCards = ({ dateRange }: { dateRange: DateRange }) => {
  const {
    data: metrics,
    isLoading: isMetricsLoading,
    isError: isMetricsError,
    refetch: refetchMetrics,
  } = useSqlWarehouseSummary(dateRange);
  const {
    data: topWarehouses,
    isLoading: isTopLoading,
    isError: isTopError,
    refetch: refetchTop,
  } = useTopSqlWarehouses(dateRange, 5);

  // Whole-tab daily run-rate: total shown spend / days in the window. This is
  // NOT a per-warehouse-day average, so the tile is labeled "per day avg" to
  // match its actual denominator.
  const dailyAverageSpend = metrics
    ? metrics.total_spend / Math.max(metrics.date_range_days, 1)
    : 0;

  const typeEntries = metrics
    ? ([
        ['SERVERLESS', metrics.serverless_spend, metrics.serverless_warehouses],
        ['PRO', metrics.pro_spend, metrics.pro_warehouses],
        ['CLASSIC', metrics.classic_spend, metrics.classic_warehouses],
      ] as const)
        .filter(([, , count]) => count > 0)
        .sort((a, b) => b[1] - a[1])
    : [];

  return (
    <div className="space-y-6">
      {isMetricsLoading ? (
        <KpiStripSkeleton />
      ) : isMetricsError ? (
        <ErrorState
          message="Couldn't load SQL warehouse summary metrics. Please try again."
          onRetry={() => refetchMetrics()}
        />
      ) : !metrics ? (
        <Card>
          <CardContent className="p-6">
            <div className="text-center text-muted-foreground">
              No SQL warehouse data available for the selected date range
            </div>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Total Spend</CardTitle>
              <DollarSign className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-blue-600">
                {formatCurrency(metrics.total_spend)}
              </div>
              <p className="text-xs text-muted-foreground mt-1">
                {metrics.date_range_days} day
                {metrics.date_range_days !== 1 ? 's' : ''} period ·{' '}
                {formatCurrency(dailyAverageSpend)}/day avg
                {(metrics.dbu_in_non_covered_workspaces ?? 0) > 0 && (
                  <>
                    {' '}
                    ·{' '}
                    {formatCurrency(
                      metrics.dbu_in_non_covered_workspaces ?? 0,
                    )}{' '}
                    DBU in non-covered workspaces
                  </>
                )}
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Warehouses</CardTitle>
              <Layers className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-purple-600">
                {formatNumber(metrics.total_warehouses)}
              </div>
              <p className="text-xs text-muted-foreground mt-1">
                {formatNumber(metrics.serverless_warehouses)} serverless ·{' '}
                {formatNumber(metrics.pro_warehouses)} pro ·{' '}
                {formatNumber(metrics.classic_warehouses)} classic
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">DBU Cost</CardTitle>
              <Database className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-red-600">
                {formatCurrency(metrics.total_databricks_cost)}
              </div>
              <p className="text-xs text-muted-foreground mt-1">
                100% of total — managed compute has no separate VM cost
              </p>
            </CardContent>
          </Card>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Spend by warehouse type — the exhaustive three-bucket $ split. */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <Database className="h-5 w-5 text-muted-foreground" />
              Spend by Type
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isMetricsLoading ? (
              <BreakdownSkeleton />
            ) : isMetricsError ? (
              <ErrorState
                compact
                message="Couldn't load the warehouse type breakdown."
                onRetry={() => refetchMetrics()}
              />
            ) : !metrics || typeEntries.length === 0 ? (
              <div className="text-center text-muted-foreground py-4 text-sm">
                No warehouse data for this period
              </div>
            ) : (
              <div className="space-y-3">
                {typeEntries.map(([type, spend, count]) => (
                  <div
                    key={type}
                    className="flex items-center justify-between gap-2"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <Badge
                        variant="secondary"
                        className={`text-[10px] shrink-0 ${warehouseTypeBadgeClasses(
                          type,
                        )}`}
                      >
                        {warehouseTypeLabel(type)}
                      </Badge>
                      <span className="text-xs text-muted-foreground shrink-0">
                        {formatNumber(count)}
                      </span>
                    </div>
                    <div className="text-right shrink-0">
                      <div className="text-sm font-semibold">
                        {formatCurrency(spend)}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {formatPercent(spend, metrics.total_spend)}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-lg">
              Top 5 Costliest Warehouses
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isTopLoading ? (
              <TopListSkeleton />
            ) : isTopError ? (
              <ErrorState
                compact
                message="Couldn't load top warehouses."
                onRetry={() => refetchTop()}
              />
            ) : topWarehouses && topWarehouses.length > 0 ? (
              <div className="space-y-3">
                {topWarehouses.map((warehouse, index) => {
                  const hasName =
                    !!warehouse.warehouse_name &&
                    warehouse.warehouse_name.trim().length > 0;
                  const label = hasName
                    ? warehouse.warehouse_name!
                    : `Warehouse ${warehouse.warehouse_id}`;
                  return (
                    <div
                      key={warehouse.warehouse_id}
                      className="flex justify-between items-center gap-2"
                    >
                      <div className="flex items-center space-x-2 min-w-0">
                        <span className="text-xs bg-muted text-muted-foreground px-2 py-1 rounded shrink-0">
                          #{index + 1}
                        </span>
                        <span
                          className={`text-sm font-medium truncate ${
                            hasName ? '' : 'font-mono text-muted-foreground'
                          }`}
                          title={
                            hasName
                              ? `${label} — ${warehouse.warehouse_id}`
                              : `Unnamed — ${warehouse.warehouse_id}`
                          }
                        >
                          {label}
                        </span>
                        <Badge
                          variant="secondary"
                          className={`text-[10px] shrink-0 ${warehouseTypeBadgeClasses(
                            warehouse.warehouse_type,
                          )}`}
                        >
                          {warehouseTypeLabel(warehouse.warehouse_type)}
                        </Badge>
                      </div>
                      <div className="text-right shrink-0 ml-2">
                        <div className="text-sm font-semibold">
                          {formatCurrency(warehouse.total_cost)}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {warehouse.active_days} day
                          {warehouse.active_days === 1 ? '' : 's'}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="text-center text-muted-foreground py-4 text-sm">
                No warehouses found for this period
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

// Date presets + range inputs + debounced search. Parallels
// `PipelineFilterControls` minus the workload chips.
const SqlWarehouseFilterControls = ({
  dateRange,
  onDateRangeChange,
  searchTerm,
  onSearchTermChange,
}: {
  dateRange: DateRange;
  onDateRangeChange: (dateRange: DateRange) => void;
  searchTerm: string;
  onSearchTermChange: (search: string) => void;
}) => {
  const { data: presets } = useDatePresets();
  const [localFilter, setLocalFilter] = useState(searchTerm);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setLocalFilter(searchTerm);
  }, [searchTerm]);

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  const handleFilterChange = (value: string) => {
    setLocalFilter(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => onSearchTermChange(value), 300);
  };

  const dateRangeInvalid = useMemo(
    () => isInvalidDateRange(dateRange.start_date, dateRange.end_date),
    [dateRange.start_date, dateRange.end_date],
  );

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div className="space-y-4">
        <Label className="text-sm font-semibold">Date Range</Label>

        {presets && (
          <div className="flex flex-wrap gap-2">
            {Object.entries(presets).map(([key, preset]) => (
              <Button
                key={key}
                variant="outline"
                size="sm"
                onClick={() =>
                  onDateRangeChange({
                    start_date: preset.start_date,
                    end_date: preset.end_date,
                  })
                }
                className={cn(
                  'text-xs',
                  dateRange.start_date === preset.start_date &&
                    dateRange.end_date === preset.end_date &&
                    'bg-blue-50 border-blue-200 text-blue-700 dark:bg-blue-500/15 dark:border-blue-500/40 dark:text-blue-300',
                )}
              >
                {preset.label}
              </Button>
            ))}
          </div>
        )}

        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <div>
              <Label htmlFor="wh-start-date" className="text-sm font-medium">
                Start Date
              </Label>
              <Input
                id="wh-start-date"
                type="date"
                value={dateRange.start_date}
                onChange={(e) =>
                  onDateRangeChange({
                    start_date: e.target.value,
                    end_date: dateRange.end_date,
                  })
                }
                className="mt-1"
              />
            </div>
            <div>
              <Label htmlFor="wh-end-date" className="text-sm font-medium">
                End Date
              </Label>
              <Input
                id="wh-end-date"
                type="date"
                value={dateRange.end_date}
                onChange={(e) =>
                  onDateRangeChange({
                    start_date: dateRange.start_date,
                    end_date: e.target.value,
                  })
                }
                aria-invalid={dateRangeInvalid}
                className={cn(
                  'mt-1',
                  dateRangeInvalid &&
                    'border-red-500 focus-visible:ring-red-500',
                )}
              />
            </div>
          </div>
          {dateRangeInvalid && (
            <div
              className="flex items-center gap-1.5 text-xs text-red-600"
              role="alert"
            >
              <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
              <span>Start date must be on or before the end date.</span>
            </div>
          )}
        </div>
      </div>

      <div className="space-y-4">
        <Label htmlFor="wh-search" className="text-sm font-semibold">
          Search Warehouses
        </Label>

        <div className="relative">
          <Search
            className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            id="wh-search"
            placeholder="Search by warehouse name or warehouse ID..."
            value={localFilter}
            onChange={(e) => handleFilterChange(e.target.value)}
            className="pl-10"
          />
        </div>

        <div className="text-xs text-muted-foreground space-y-1">
          <div>
            <strong>Date Range:</strong>{' '}
            {formatCalendarDate(dateRange.start_date)} to{' '}
            {formatCalendarDate(dateRange.end_date)}
          </div>
          {searchTerm && (
            <div>
              <strong>Search:</strong> "{searchTerm}"
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

const KpiStripSkeleton = () => (
  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
    {[...Array(3)].map((_, i) => (
      <Card key={i}>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <Skeleton className="h-4 w-[100px]" />
          <Skeleton className="h-4 w-4" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-8 w-[120px] mb-2" />
          <Skeleton className="h-3 w-[80px]" />
        </CardContent>
      </Card>
    ))}
  </div>
);

const BreakdownSkeleton = () => (
  <div className="space-y-3">
    {[...Array(3)].map((_, i) => (
      <div key={i} className="flex items-center justify-between">
        <Skeleton className="h-4 w-[80px]" />
        <Skeleton className="h-4 w-[60px]" />
      </div>
    ))}
  </div>
);

const TopListSkeleton = () => (
  <div className="space-y-3">
    {[...Array(5)].map((_, i) => (
      <div key={i} className="flex justify-between items-center">
        <Skeleton className="h-4 w-[160px]" />
        <Skeleton className="h-4 w-[100px]" />
      </div>
    ))}
  </div>
);

export default SqlWarehousesDashboard;

import { useState, useEffect } from 'react';
import {
  ColumnDef,
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  SortingState,
  useReactTable,
  Row,
} from '@tanstack/react-table';
import { ArrowUpDown, ChevronLeft, ChevronRight, ChevronDown, ChevronRight as ChevronRightIcon, Eye, Search, Loader2, Info } from 'lucide-react';
import { Button } from '@/components/ui/button';
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
import { useGroupedJobSpends } from '@/hooks/useGroupedJobSpends';
import { useJobRuns } from '@/hooks/useJobRuns';
import { useDatabricksHost } from '@/hooks/useDatabricksHost';
import { DateRange, GroupedJob, JobRun } from '@/types/job-spend';
import { cn } from '@/lib/utils';
import { useCloudPlatform } from '@/contexts/CloudPlatformContext';
import { useIsAws, useIsSegmentedPlatform, AWS_CLOUD_LABEL } from '@/hooks/useCloudGate';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { OtherCostBreakdownModal } from './OtherCostBreakdownModal';

const formatRunCurrency = (amount: number) =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);

const formatRunDay = (dateStr: string) => {
  try {
    return new Date(dateStr).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return dateStr;
  }
};

const formatRunRange = (startDate: string, endDate: string) =>
  startDate === endDate
    ? formatRunDay(startDate)
    : `${formatRunDay(startDate)} — ${formatRunDay(endDate)}`;

interface ExpandedJobRunsProps {
  job: GroupedJob;
  dateRange: DateRange;
  colSpan: number;
  computeLabel: string;
  isSegmentedPlatform: boolean;
  onRunClick: (jobId: string, run: JobRun) => void;
}

// Renders the per-job run breakdown. Runs are fetched lazily on expand (the
// grouped list query no longer embeds them), so this row shows its own loading
// and error states while the request is in flight.
const ExpandedJobRuns = ({ job, dateRange, colSpan, computeLabel, isSegmentedPlatform, onRunClick }: ExpandedJobRunsProps) => {
  const { data: runs, isLoading, error } = useJobRuns(
    job.job_id,
    { start_date: dateRange.start_date, end_date: dateRange.end_date, limit: 10 },
    true,
  );

  return (
    <TableRow className="bg-muted/30">
      <TableCell colSpan={colSpan} className="p-0">
        <div className="p-4 border-l-4 border-l-blue-500 bg-muted/20">
          {isLoading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>Loading runs…</span>
            </div>
          ) : error ? (
            <div className="text-sm text-red-600 py-2">
              Failed to load runs: {error.message}
            </div>
          ) : !runs || runs.length === 0 ? (
            <div className="text-sm text-muted-foreground py-2">
              No runs found for this job in the selected range.
            </div>
          ) : (
            <>
              <h4 className="font-semibold mb-3 text-sm text-muted-foreground">
                Individual Runs ({runs.length} of {job.run_count} total runs shown)
              </h4>
              <div className="space-y-2">
                {runs.map((run) => (
                  <div
                    key={run.run_id}
                    className="flex items-center justify-between p-3 bg-background rounded-md border hover:bg-muted/50 cursor-pointer transition-colors"
                    onClick={() => onRunClick(job.job_id, run)}
                  >
                    <div className="flex items-center space-x-4">
                      <div className="text-sm font-mono text-muted-foreground">
                        Run: {run.run_id}
                      </div>
                      <div className="text-sm text-muted-foreground">
                        {formatRunRange(run.start_date, run.end_date)}
                      </div>
                      <div className="text-sm text-muted-foreground max-w-[150px] truncate">
                        {run.cluster_id}
                      </div>
                    </div>
                    <div className="flex items-center space-x-4">
                      {isSegmentedPlatform ? (
                        <>
                          <div className="text-sm text-blue-600">
                            Compute: {formatRunCurrency(run.compute_cost ?? 0)}
                          </div>
                          <div className="text-sm text-green-600">
                            Storage: {formatRunCurrency(run.storage_cost ?? 0)}
                          </div>
                          <div className="text-sm text-amber-600">
                            Network: {formatRunCurrency(run.network_cost ?? 0)}
                          </div>
                          {(run.other_cost ?? 0) > 0 && (
                            <div className="text-sm text-muted-foreground">
                              Other: {formatRunCurrency(run.other_cost ?? 0)}
                            </div>
                          )}
                        </>
                      ) : (
                        <div className="text-sm text-blue-600">
                          {computeLabel}: {formatRunCurrency(run.cloud_cost)}
                        </div>
                      )}
                      <div className="text-sm text-red-600">
                        DBU: {formatRunCurrency(run.databricks_cost)}
                      </div>
                      <div className="text-sm font-semibold">
                        Total: {formatRunCurrency(run.total_cost)}
                      </div>
                      <Button size="sm" variant="outline" className="h-7">
                        <Eye className="h-3 w-3 mr-1" />
                        Details
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </TableCell>
    </TableRow>
  );
};

interface GroupedJobTableProps {
  dateRange: DateRange;
  jobFilter: string;
  onRunClick: (jobId: string, run: JobRun) => void;
  // Reports background refetch state so parents can show search/loading feedback.
  onFetchingChange?: (isFetching: boolean) => void;
}

export const GroupedJobTable = ({ dateRange, jobFilter, onRunClick, onFetchingChange }: GroupedJobTableProps) => {
  const { config: cloudConfig } = useCloudPlatform();
  const isAws = useIsAws();
  const isSegmentedPlatform = useIsSegmentedPlatform();
  const [sorting, setSorting] = useState<SortingState>([
    { id: 'total_cost', desc: true }, // Default sort by total cost descending
  ]);
  const [pagination, setPagination] = useState({
    pageIndex: 0,
    pageSize: 50,
  });
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [otherBreakdownOpen, setOtherBreakdownOpen] = useState(false);

  useEffect(() => {
    setPagination((prev) => ({ ...prev, pageIndex: 0 }));
  }, [jobFilter, dateRange.start_date, dateRange.end_date]);

  const { data, isLoading, isFetching, error } = useGroupedJobSpends({
    start_date: dateRange.start_date,
    end_date: dateRange.end_date,
    job_name: jobFilter || undefined,
    page: pagination.pageIndex + 1,
    per_page: pagination.pageSize,
  });

  // Distinguish initial load (no previous data) from a background refetch
  // (previous page's data is still on screen thanks to keepPreviousData).
  const isInitialLoading = isLoading && !data;
  const isBackgroundFetching = isFetching && !!data;

  // Surface refetch state to the parent (e.g. the search box spinner). Initial
  // load is excluded since the row skeletons already communicate that state.
  useEffect(() => {
    onFetchingChange?.(isBackgroundFetching);
  }, [isBackgroundFetching, onFetchingChange]);

  const { data: databricksHost } = useDatabricksHost();

  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(amount);
  };

  const toggleRowExpansion = (jobId: string) => {
    const newExpandedRows = new Set(expandedRows);
    if (newExpandedRows.has(jobId)) {
      newExpandedRows.delete(jobId);
    } else {
      newExpandedRows.add(jobId);
    }
    setExpandedRows(newExpandedRows);
  };

  const columns: ColumnDef<GroupedJob>[] = [
    {
      id: 'expander',
      header: '',
      cell: ({ row }) => {
        const isExpanded = expandedRows.has(row.original.job_id);
        return (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => toggleRowExpansion(row.original.job_id)}
            className="h-8 w-8 p-0"
          >
            {isExpanded ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRightIcon className="h-4 w-4" />
            )}
          </Button>
        );
      },
    },
    {
      accessorKey: 'job_id',
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
          className="h-8 px-2"
        >
          Job ID
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => {
        const jobId = row.getValue('job_id') as string;
        // Ensure we use the correct workspace URL for job links
        // Remove any /apps/appname suffix that might be present in deployed environments
        const workspaceHost = databricksHost ? databricksHost.replace(/\/apps\/[^\/]+$/, '') : null;
        const jobUrl = workspaceHost ? `${workspaceHost}/jobs/${jobId}` : '#';

        return (
          <div className="font-medium max-w-[200px] truncate">
            {databricksHost ? (
              <a
                href={jobUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-600 hover:text-blue-800 hover:underline"
                title={`Open job ${jobId} in Databricks`}
              >
                {jobId}
              </a>
            ) : (
              <span title={jobId}>{jobId}</span>
            )}
          </div>
        );
      },
    },
    {
      accessorKey: 'job_name',
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
          className="h-8 px-2"
        >
          Job Name
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => {
        const jobName = row.getValue('job_name') as string;
        return (
          <div className="max-w-[250px] truncate text-muted-foreground" title={jobName}>
            {jobName || 'N/A'}
          </div>
        );
      },
    },
    {
      accessorKey: 'run_count',
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
          className="h-8 px-2"
        >
          Runs
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => (
        <div className="text-center">
          <Badge variant="secondary" className="text-xs">
            {row.getValue('run_count')} runs
          </Badge>
        </div>
      ),
    },
    // Segmented compute/storage/network/other columns render only for platforms
    // that emit a full segmentation (Azure/GCP). AWS, Unknown, and the loading
    // window fall to the single EC2 / EBS cloud column below (D4, D14).
    ...(isSegmentedPlatform ? ([
    {
      accessorKey: 'total_compute_cost',
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
          className="h-8 px-2"
        >
          Compute
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => {
        const val = row.original.total_compute_cost;
        return (
          <div className="text-right font-medium text-blue-600">
            {val != null ? formatCurrency(val) : '—'}
          </div>
        );
      },
    },
    {
      accessorKey: 'total_storage_cost',
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
          className="h-8 px-2"
        >
          Storage
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => {
        const val = row.original.total_storage_cost;
        return (
          <div className="text-right font-medium text-green-600">
            {val != null ? formatCurrency(val) : '—'}
          </div>
        );
      },
    },
    {
      accessorKey: 'total_network_cost',
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
          className="h-8 px-2"
        >
          Network
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => {
        const val = row.original.total_network_cost;
        return (
          <div className="text-right font-medium text-amber-600">
            {val != null ? formatCurrency(val) : '—'}
          </div>
        );
      },
    },
    {
      accessorKey: 'total_other_cost',
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
          className="h-8 px-2"
        >
          Other
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => {
        const val = row.original.total_other_cost;
        if (val == null || val === 0) return <div className="text-right text-muted-foreground">—</div>;
        return (
          <div
            className="text-right font-medium text-muted-foreground cursor-pointer hover:text-foreground transition-colors flex items-center justify-end gap-1"
            onClick={(e) => {
              e.stopPropagation();
              setOtherBreakdownOpen(true);
            }}
            title="Click to view breakdown of unclassified costs"
          >
            {formatCurrency(val)}
            <Search className="h-3 w-3" />
          </div>
        );
      },
    },
    ] as ColumnDef<GroupedJob>[]) : []),
    {
      accessorKey: 'total_cloud_cost',
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
          className="h-8 px-2"
        >
          {isAws ? AWS_CLOUD_LABEL : `Total ${cloudConfig?.compute_service || 'Cloud'} Cost`}
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => (
        <div className="text-right font-medium text-blue-600">
          {formatCurrency(row.getValue('total_cloud_cost'))}
        </div>
      ),
    },
    {
      accessorKey: 'total_databricks_cost',
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
          className="h-8 px-2"
        >
          Total Databricks Cost
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => (
        <div className="text-right font-medium text-red-600">
          {formatCurrency(row.getValue('total_databricks_cost'))}
        </div>
      ),
    },
    {
      accessorKey: 'total_cost',
      header: ({ column }) => (
        <div className="flex items-center justify-end gap-1">
          <Button
            variant="ghost"
            onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
            className="h-8 px-2"
          >
            Total Cost
            <ArrowUpDown className="ml-2 h-4 w-4" />
          </Button>
          {isAws && (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="inline-flex text-muted-foreground">
                  <Info className="h-3.5 w-3.5" />
                </span>
              </TooltipTrigger>
              <TooltipContent className="max-w-xs">
                Total Cost = DBU + tagged EC2 / EBS. Excludes non-attributable AWS shared infra (S3, NAT, networking).
              </TooltipContent>
            </Tooltip>
          )}
        </div>
      ),
      cell: ({ row }) => {
        const totalCost = row.getValue('total_cost') as number;
        return (
          <div className="text-right">
            <div className="font-bold text-lg">{formatCurrency(totalCost)}</div>
            {totalCost > 1000 && (
              <Badge variant="destructive" className="text-xs">
                High Cost
              </Badge>
            )}
          </div>
        );
      },
    },
  ];

  const table = useReactTable({
    data: data?.data || [],
    columns,
    pageCount: data?.total_pages || 0,
    state: {
      sorting,
      pagination,
    },
    onSortingChange: setSorting,
    onPaginationChange: setPagination,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    manualPagination: true,
  });

  if (error) {
    return (
      <div className="flex items-center justify-center h-64 border border-dashed border-red-200 dark:border-red-500/40 rounded-lg">
        <div className="text-center">
          <div className="text-red-600 font-medium mb-2">Error loading job data</div>
          <div className="text-sm text-muted-foreground">{error.message}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Table */}
      <div className="rounded-md border relative overflow-hidden">
        {/* Subtle progress bar shown only during background refetches.
            Initial load uses the row skeletons below instead. */}
        {isBackgroundFetching && (
          <div
            className="absolute left-0 right-0 top-0 h-0.5 bg-blue-500/70 animate-pulse z-10"
            aria-hidden="true"
          />
        )}
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableHead key={header.id} className="px-4">
                    {header.isPlaceholder
                      ? null
                      : flexRender(header.column.columnDef.header, header.getContext())}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {isInitialLoading ? (
              // Loading skeleton
              [...Array(10)].map((_, i) => (
                <TableRow key={i}>
                  {columns.map((_, j) => (
                    <TableCell key={j} className="px-4">
                      <Skeleton className="h-8 w-full" />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : table.getRowModel().rows?.length ? (
              <>
                {table.getRowModel().rows.map((row) => (
                  <>
                    <TableRow
                      key={row.id}
                      data-state={row.getIsSelected() && 'selected'}
                      className="hover:bg-muted/50"
                    >
                      {row.getVisibleCells().map((cell) => (
                        <TableCell key={cell.id} className="px-4">
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </TableCell>
                      ))}
                    </TableRow>
                    {expandedRows.has(row.original.job_id) && (
                      <ExpandedJobRuns
                        job={row.original}
                        dateRange={dateRange}
                        colSpan={columns.length}
                        computeLabel={isAws ? AWS_CLOUD_LABEL : (cloudConfig?.compute_service || 'Cloud')}
                        isSegmentedPlatform={isSegmentedPlatform}
                        onRunClick={onRunClick}
                      />
                    )}
                  </>
                ))}
              </>
            ) : (
              <TableRow>
                <TableCell colSpan={columns.length} className="h-24 text-center">
                  <div className="text-muted-foreground">
                    No job data found for the selected filters.
                  </div>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      {/* Pagination */}
      {data && data.total_count > 0 && (
        <div className="flex items-center justify-between">
          <div className="text-sm text-muted-foreground">
            Showing {data.data.length} jobs of {data.total_count} total
            {jobFilter && ` (filtered by "${jobFilter}")`}
          </div>

          <div className="flex items-center space-x-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage() || isInitialLoading}
            >
              <ChevronLeft className="h-4 w-4 mr-1" />
              Previous
            </Button>

            <div className="text-sm font-medium flex items-center gap-2">
              <span>
                Page {table.getState().pagination.pageIndex + 1} of {table.getPageCount()}
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
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage() || isInitialLoading}
            >
              Next
              <ChevronRight className="h-4 w-4 ml-1" />
            </Button>
          </div>
        </div>
      )}

      {/* Other Cost Breakdown Modal — only mounted for segmented platforms;
          the "Other" column (its only trigger) is hidden on AWS/Unknown (D7). */}
      {isSegmentedPlatform && (
        <OtherCostBreakdownModal
          dateRange={dateRange}
          isOpen={otherBreakdownOpen}
          onClose={() => setOtherBreakdownOpen(false)}
        />
      )}
    </div>
  );
};
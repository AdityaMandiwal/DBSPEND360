import { useState, useEffect } from "react";
import {
  ColumnDef,
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  SortingState,
  useReactTable,
} from "@tanstack/react-table";
import {
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  AlertTriangle,
  Eye,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { useInstancePools } from "@/hooks/useInstancePools";
import { useDatabricksHost } from "@/hooks/useDatabricksHost";
import type { DateRange, InstancePoolSpend } from "@/types/job-spend";

interface InstancePoolTableProps {
  dateRange: DateRange;
  searchFilter: string;
  onRowClick: (pool: InstancePoolSpend) => void;
}

const formatCurrency = (amount: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);

const formatIdleTimeout = (minutes?: number | null) => {
  if (minutes == null) return "Disabled";
  if (minutes === 0) return "Disabled";
  return `${minutes} min`;
};

const formatIdleInstances = (n?: number | null) => {
  if (n == null) return "—";
  return n.toString();
};

export const InstancePoolTable = ({
  dateRange,
  searchFilter,
  onRowClick,
}: InstancePoolTableProps) => {
  const [sorting, setSorting] = useState<SortingState>([
    { id: "idle_cloud_cost", desc: true },
  ]);
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: 50 });

  useEffect(() => {
    setPagination((prev) => ({ ...prev, pageIndex: 0 }));
  }, [searchFilter, dateRange.start_date, dateRange.end_date]);

  const { data, isLoading, isFetching, error } = useInstancePools({
    start_date: dateRange.start_date,
    end_date: dateRange.end_date,
    search: searchFilter || undefined,
    page: pagination.pageIndex + 1,
    per_page: pagination.pageSize,
  });

  const isInitialLoading = isLoading && !data;
  const isBackgroundFetching = isFetching && !!data;
  const { data: databricksHost } = useDatabricksHost();

  const columns: ColumnDef<InstancePoolSpend>[] = [
    {
      accessorKey: "instance_pool_name",
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          className="h-8 px-2"
        >
          Pool Name
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => {
        const name = row.original.instance_pool_name;
        const id = row.original.instance_pool_id;
        const workspaceHost = databricksHost
          ? databricksHost.replace(/\/apps\/[^/]+$/, "")
          : null;
        const poolUrl = workspaceHost
          ? `${workspaceHost}/compute/instance-pools/${id}`
          : null;
        return (
          <div className="max-w-[260px]">
            <div className="font-medium truncate" title={name ?? id}>
              {poolUrl ? (
                <a
                  href={poolUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 hover:text-blue-800 hover:underline"
                  title={`Open ${id} in Databricks`}
                  onClick={(e) => e.stopPropagation()}
                >
                  {name || "Pool name unknown"}
                </a>
              ) : (
                <span>{name || "Pool name unknown"}</span>
              )}
            </div>
            <div
              className="text-xs text-muted-foreground font-mono truncate"
              title={id}
            >
              {id}
            </div>
          </div>
        );
      },
    },
    {
      accessorKey: "node_type_id",
      header: "Node Type",
      cell: ({ row }) => (
        <div
          className="max-w-[180px] truncate text-muted-foreground font-mono text-xs"
          title={row.original.node_type_id ?? ""}
        >
          {row.original.node_type_id || "—"}
        </div>
      ),
    },
    {
      accessorKey: "min_idle_instances",
      header: "Min Idle",
      cell: ({ row }) => (
        <div className="text-center text-sm">
          {formatIdleInstances(row.original.min_idle_instances)}
        </div>
      ),
    },
    {
      accessorKey: "idle_instance_autotermination_minutes",
      header: "Idle Timeout",
      cell: ({ row }) => {
        const minutes = row.original.idle_instance_autotermination_minutes;
        const display = formatIdleTimeout(minutes);
        const isDisabled = display === "Disabled";
        return isDisabled ? (
          <Badge variant="destructive" className="text-xs">
            Disabled
          </Badge>
        ) : (
          <span className="text-sm">{display}</span>
        );
      },
    },
    {
      accessorKey: "attached_cluster_count",
      header: "Attached",
      cell: ({ row }) => {
        const count = row.original.attached_cluster_count;
        if (row.original.is_orphan) {
          return (
            <Badge variant="destructive" className="text-xs">
              Orphan
            </Badge>
          );
        }
        return <div className="text-center text-sm">{count}</div>;
      },
    },
    {
      accessorKey: "pool_total_cost",
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          className="h-8 px-2"
        >
          Pool Cloud Cost
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => (
        <div className="text-right font-medium text-blue-600">
          {formatCurrency(row.original.pool_total_cost)}
        </div>
      ),
    },
    {
      accessorKey: "idle_cloud_cost",
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          className="h-8 px-2"
        >
          Idle VM Cost
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => {
        const idle = row.original.idle_cloud_cost;
        return (
          <div className="text-right font-medium text-amber-600">
            {formatCurrency(idle)}
          </div>
        );
      },
    },
    {
      accessorKey: "idle_pct",
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          className="h-8 px-2"
        >
          Idle %
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => {
        const pct = row.original.idle_pct;
        const isHigh = pct > 30;
        return (
          <div className="w-24">
            <div className="flex justify-between text-xs text-muted-foreground mb-1">
              <span className={isHigh ? "text-amber-600 font-semibold" : ""}>
                {pct.toFixed(1)}%
              </span>
              {isHigh && (
                <Badge
                  variant="outline"
                  className="text-[10px] h-4 px-1 border-amber-500 text-amber-600"
                >
                  High
                </Badge>
              )}
            </div>
            <div className="w-full bg-muted rounded-full h-1.5 overflow-hidden">
              <div
                className={`h-1.5 ${isHigh ? "bg-amber-500" : "bg-blue-500"}`}
                style={{ width: `${Math.min(pct, 100)}%` }}
              />
            </div>
          </div>
        );
      },
    },
    {
      accessorKey: "total_cost",
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          className="h-8 px-2"
        >
          Total
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => (
        <div className="text-right font-bold text-base">
          {formatCurrency(row.original.total_cost)}
        </div>
      ),
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <Button
          size="sm"
          variant="outline"
          className="h-7"
          onClick={(e) => {
            e.stopPropagation();
            onRowClick(row.original);
          }}
        >
          <Eye className="h-3 w-3 mr-1" />
          Details
        </Button>
      ),
    },
  ];

  const table = useReactTable({
    data: data?.data || [],
    columns,
    pageCount: data?.total_pages || 0,
    state: { sorting, pagination },
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
          <AlertTriangle className="mx-auto h-6 w-6 text-red-500 mb-2" />
          <div className="text-red-600 font-medium mb-2">
            Error loading instance pools
          </div>
          <div className="text-sm text-muted-foreground">{error.message}</div>
        </div>
      </div>
    );
  }

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
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableHead key={header.id} className="px-4">
                    {header.isPlaceholder
                      ? null
                      : flexRender(
                          header.column.columnDef.header,
                          header.getContext(),
                        )}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {isInitialLoading ? (
              [...Array(8)].map((_, i) => (
                <TableRow key={i}>
                  {columns.map((_, j) => (
                    <TableCell key={j} className="px-4">
                      <Skeleton className="h-8 w-full" />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : table.getRowModel().rows?.length ? (
              table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  className={`hover:bg-muted/50 cursor-pointer ${
                    row.original.is_orphan
                      ? "bg-red-50/40 dark:bg-red-500/5"
                      : ""
                  }`}
                  onClick={() => onRowClick(row.original)}
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id} className="px-4">
                      {flexRender(
                        cell.column.columnDef.cell,
                        cell.getContext(),
                      )}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  className="h-24 text-center"
                >
                  <div className="text-muted-foreground">
                    No instance pools found for the selected filters.
                  </div>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      {data && data.total_count > 0 && (
        <div className="flex items-center justify-between">
          <div className="text-sm text-muted-foreground">
            Showing {data.data.length} of {data.total_count} pools
            {searchFilter && " (filtered)"}
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
                Page {table.getState().pagination.pageIndex + 1} of{" "}
                {table.getPageCount()}
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
    </div>
  );
};

export default InstancePoolTable;

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
import { useSharedClusters } from "@/hooks/useSharedClusters";
import { useDatabricksHost } from "@/hooks/useDatabricksHost";
import type { DateRange, SharedClusterSpend } from "@/types/job-spend";

interface SharedClusterTableProps {
  dateRange: DateRange;
  ownerFilter: string;
  searchFilter: string;
  onRowClick: (cluster: SharedClusterSpend) => void;
}

const formatCurrency = (amount: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);

const formatDate = (dateStr?: string | null) => {
  if (!dateStr) return "—";
  try {
    return new Date(dateStr).toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return dateStr;
  }
};

export const SharedClusterTable = ({
  dateRange,
  ownerFilter,
  searchFilter,
  onRowClick,
}: SharedClusterTableProps) => {
  const [sorting, setSorting] = useState<SortingState>([
    { id: "total_cost", desc: true },
  ]);
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: 50 });

  useEffect(() => {
    setPagination((prev) => ({ ...prev, pageIndex: 0 }));
  }, [ownerFilter, searchFilter, dateRange.start_date, dateRange.end_date]);

  const { data, isLoading, isFetching, error } = useSharedClusters({
    start_date: dateRange.start_date,
    end_date: dateRange.end_date,
    owner: ownerFilter || undefined,
    search: searchFilter || undefined,
    page: pagination.pageIndex + 1,
    per_page: pagination.pageSize,
  });

  const isInitialLoading = isLoading && !data;
  const isBackgroundFetching = isFetching && !!data;
  const { data: databricksHost } = useDatabricksHost();

  const columns: ColumnDef<SharedClusterSpend>[] = [
    {
      accessorKey: "cluster_name",
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          className="h-8 px-2"
        >
          Cluster Name
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => {
        const name = row.original.cluster_name;
        const id = row.original.cluster_id;
        const workspaceHost = databricksHost
          ? databricksHost.replace(/\/apps\/[^/]+$/, "")
          : null;
        const clusterUrl = workspaceHost
          ? `${workspaceHost}/compute/clusters/${id}`
          : null;
        return (
          <div className="max-w-[260px]">
            <div className="font-medium truncate" title={name ?? id}>
              {clusterUrl ? (
                <a
                  href={clusterUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 hover:text-blue-800 hover:underline"
                  title={`Open ${id} in Databricks`}
                  onClick={(e) => e.stopPropagation()}
                >
                  {name || id}
                </a>
              ) : (
                <span>{name || id}</span>
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
      accessorKey: "owned_by",
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          className="h-8 px-2"
        >
          Owner
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => (
        <div
          className="max-w-[200px] truncate text-muted-foreground"
          title={row.original.owned_by ?? ""}
        >
          {row.original.owned_by || "—"}
        </div>
      ),
    },
    {
      accessorKey: "cluster_source",
      header: "Source",
      cell: ({ row }) => (
        <Badge variant="outline" className="text-xs">
          {row.original.cluster_source || "N/A"}
        </Badge>
      ),
    },
    {
      accessorKey: "data_security_mode",
      header: "Security Mode",
      cell: ({ row }) => {
        const mode = row.original.data_security_mode;
        if (!mode) return <span className="text-muted-foreground">—</span>;
        return (
          <Badge variant="secondary" className="text-xs">
            {mode}
          </Badge>
        );
      },
    },
    {
      id: "cloud_split",
      header: "Cloud / DBU",
      cell: ({ row }) => {
        const cloudPct = row.original.cloud_percentage;
        const dbuPct = row.original.databricks_percentage;
        return (
          <div className="w-32">
            <div className="flex justify-between text-xs text-muted-foreground mb-1">
              <span className="text-blue-600">{cloudPct.toFixed(0)}%</span>
              <span className="text-red-600">{dbuPct.toFixed(0)}%</span>
            </div>
            <div className="w-full bg-muted rounded-full h-1.5 flex overflow-hidden">
              <div
                className="bg-blue-500 h-1.5"
                style={{ width: `${cloudPct}%` }}
              />
              <div
                className="bg-red-500 h-1.5"
                style={{ width: `${dbuPct}%` }}
              />
            </div>
          </div>
        );
      },
    },
    {
      accessorKey: "active_days",
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          className="h-8 px-2"
        >
          Active Days
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => (
        <div className="text-center text-sm">{row.original.active_days}</div>
      ),
    },
    {
      accessorKey: "last_active_date",
      header: "Last Seen",
      cell: ({ row }) => (
        <div className="text-sm text-muted-foreground">
          {formatDate(row.original.last_active_date)}
        </div>
      ),
    },
    {
      accessorKey: "cloud_cost",
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          className="h-8 px-2"
        >
          Cloud Cost
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => (
        <div className="text-right font-medium text-blue-600">
          {formatCurrency(row.original.cloud_cost)}
        </div>
      ),
    },
    {
      accessorKey: "databricks_cost",
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          className="h-8 px-2"
        >
          DBU Cost
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => (
        <div className="text-right font-medium text-red-600">
          {formatCurrency(row.original.databricks_cost)}
        </div>
      ),
    },
    {
      accessorKey: "total_cost",
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          className="h-8 px-2"
        >
          Total Cost
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => {
        const total = row.original.total_cost;
        return (
          <div className="text-right">
            <div className="font-bold text-lg">{formatCurrency(total)}</div>
            {total > 1000 && (
              <Badge variant="destructive" className="text-xs">
                High Cost
              </Badge>
            )}
          </div>
        );
      },
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
            Error loading shared clusters
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
                  className="hover:bg-muted/50 cursor-pointer"
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
                    No shared clusters found for the selected filters.
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
            Showing {data.data.length} of {data.total_count} clusters
            {(ownerFilter || searchFilter) && " (filtered)"}
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

export default SharedClusterTable;

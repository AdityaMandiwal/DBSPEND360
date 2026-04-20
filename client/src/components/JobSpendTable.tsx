import { useState } from 'react';
import {
  ColumnDef,
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  SortingState,
  useReactTable,
} from '@tanstack/react-table';
import { ArrowUpDown, ChevronLeft, ChevronRight, Eye } from 'lucide-react';
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
import { useJobSpends } from '@/hooks/useJobSpends';
import { DateRange, JobSpend } from '@/types/job-spend';
import { cn } from '@/lib/utils';
import { useCloudPlatform } from '@/contexts/CloudPlatformContext';

interface JobSpendTableProps {
  dateRange: DateRange;
  jobFilter: string;
  onJobClick: (job: JobSpend) => void;
}

export const JobSpendTable = ({ dateRange, jobFilter, onJobClick }: JobSpendTableProps) => {
  const { config: cloudConfig } = useCloudPlatform();
  const [sorting, setSorting] = useState<SortingState>([
    { id: 'total_cost', desc: true }, // Default sort by total cost descending
  ]);
  const [pagination, setPagination] = useState({
    pageIndex: 0,
    pageSize: 50,
  });

  const { data, isLoading, error } = useJobSpends({
    start_date: dateRange.start_date,
    end_date: dateRange.end_date,
    job_name: jobFilter || undefined,
    page: pagination.pageIndex + 1,
    per_page: pagination.pageSize,
  });

  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(amount);
  };

  const formatDate = (dateStr: string) => {
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

  const columns: ColumnDef<JobSpend>[] = [
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
      cell: ({ row }) => (
        <div className="font-medium max-w-[200px] truncate" title={row.getValue('job_id')}>
          {row.getValue('job_id')}
        </div>
      ),
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
      accessorKey: 'cluster_id',
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
          className="h-8 px-2"
        >
          Cluster ID
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => (
        <div className="max-w-[150px] truncate text-muted-foreground" title={row.getValue('cluster_id')}>
          {row.getValue('cluster_id')}
        </div>
      ),
    },
    {
      accessorKey: 'usage_date',
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
          className="h-8 px-2"
        >
          Usage Date
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => formatDate(row.getValue('usage_date')),
    },
    {
      accessorKey: 'cloud_cost',
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
          className="h-8 px-2"
        >
          {cloudConfig?.compute_display_name || 'Cloud Cost'}
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => (
        <div className="text-right font-medium text-blue-600">
          {formatCurrency(row.getValue('cloud_cost'))}
        </div>
      ),
    },
    {
      accessorKey: 'databricks_cost',
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
          className="h-8 px-2"
        >
          Databricks Cost
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => (
        <div className="text-right font-medium text-red-600">
          {formatCurrency(row.getValue('databricks_cost'))}
        </div>
      ),
    },
    {
      accessorKey: 'total_cost',
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === 'asc')}
          className="h-8 px-2"
        >
          Total Cost
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      ),
      cell: ({ row }) => {
        const totalCost = row.getValue('total_cost') as number;
        return (
          <div className="text-right">
            <div className="font-bold text-lg">{formatCurrency(totalCost)}</div>
            {totalCost > 100 && (
              <Badge variant="destructive" className="text-xs">
                High Cost
              </Badge>
            )}
          </div>
        );
      },
    },
    {
      id: 'actions',
      header: 'Actions',
      cell: ({ row }) => (
        <Button
          variant="outline"
          size="sm"
          onClick={() => onJobClick(row.original)}
          className="h-8"
        >
          <Eye className="h-4 w-4 mr-1" />
          Details
        </Button>
      ),
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
      <div className="flex items-center justify-center h-64 border border-dashed border-red-200 rounded-lg">
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
      <div className="rounded-md border">
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
            {isLoading ? (
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
              table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  data-state={row.getIsSelected() && 'selected'}
                  className="hover:bg-muted/50 cursor-pointer"
                  onClick={() => onJobClick(row.original)}
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id} className="px-4">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))
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
            Showing {data.data.length} of {data.total_count} jobs
            {jobFilter && ` (filtered by "${jobFilter}")`}
          </div>

          <div className="flex items-center space-x-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage() || isLoading}
            >
              <ChevronLeft className="h-4 w-4 mr-1" />
              Previous
            </Button>

            <div className="text-sm font-medium">
              Page {table.getState().pagination.pageIndex + 1} of {table.getPageCount()}
            </div>

            <Button
              variant="outline"
              size="sm"
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage() || isLoading}
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
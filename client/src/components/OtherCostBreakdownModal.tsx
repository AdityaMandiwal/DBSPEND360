import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { Search } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { useOtherCostBreakdown } from '@/hooks/useJobSpends';
import { DateRange } from '@/types/job-spend';

interface OtherCostBreakdownModalProps {
  dateRange: DateRange;
  clusterId?: string;
  isOpen: boolean;
  onClose: () => void;
}

const BAR_COLORS = [
  '#6366f1', '#8b5cf6', '#a78bfa', '#c4b5fd', '#7c3aed',
  '#4f46e5', '#818cf8', '#93c5fd', '#6d28d9', '#5b21b6',
  '#a5b4fc', '#c7d2fe', '#e0e7ff', '#ddd6fe', '#ede9fe',
];

const formatCurrency = (amount: number) =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);

export const OtherCostBreakdownModal = ({
  dateRange,
  clusterId,
  isOpen,
  onClose,
}: OtherCostBreakdownModalProps) => {
  const { data, isLoading, error } = useOtherCostBreakdown(
    dateRange,
    clusterId,
    isOpen,
  );

  const chartData = data?.items.slice(0, 10).map((item) => ({
    name: item.service_name.length > 25
      ? item.service_name.substring(0, 22) + '...'
      : item.service_name,
    fullName: item.service_name,
    cost: item.cost,
    percentage: item.percentage,
  })) ?? [];

  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const d = payload[0].payload;
      return (
        <div className="bg-popover text-popover-foreground p-3 border rounded-lg shadow-lg">
          <p className="font-medium text-sm">{d.fullName}</p>
          <p className="text-indigo-600 dark:text-indigo-400 font-semibold">{formatCurrency(d.cost)}</p>
          <p className="text-xs text-muted-foreground">{d.percentage}% of other cost</p>
        </div>
      );
    }
    return null;
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-xl font-semibold flex items-center">
            <Search className="mr-2 h-5 w-5 text-gray-500" />
            Other Cost Breakdown
          </DialogTitle>
        </DialogHeader>

        {error ? (
          <div className="text-center py-8">
            <div className="text-red-600 font-medium mb-2">Error loading breakdown</div>
            <div className="text-sm text-muted-foreground">{error.message}</div>
          </div>
        ) : isLoading ? (
          <div className="space-y-4 py-6">
            <Skeleton className="h-48 w-full" />
            <div className="space-y-2">
              {[...Array(5)].map((_, i) => (
                <Skeleton key={i} className="h-8 w-full" />
              ))}
            </div>
          </div>
        ) : data && data.items.length > 0 ? (
          <div className="space-y-6 py-4">
            <div className="flex items-center justify-between">
              <div className="text-sm text-muted-foreground">
                {data.start_date} to {data.end_date}
                {clusterId && <span className="ml-2">| Cluster: {clusterId}</span>}
              </div>
              <div className="text-right">
                <div className="text-sm text-muted-foreground">Total Other Cost</div>
                <div className="text-lg font-bold text-foreground">
                  {formatCurrency(data.total_other_cost)}
                </div>
              </div>
            </div>

            {chartData.length > 0 && (
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={chartData}
                    layout="vertical"
                    margin={{ top: 0, right: 20, left: 0, bottom: 0 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                    <XAxis
                      type="number"
                      tickFormatter={(v) => `$${v.toFixed(0)}`}
                      fontSize={11}
                    />
                    <YAxis
                      type="category"
                      dataKey="name"
                      width={160}
                      tick={{ fontSize: 11 }}
                    />
                    <Tooltip content={<CustomTooltip />} />
                    <Bar dataKey="cost" radius={[0, 4, 4, 0]}>
                      {chartData.map((_, index) => (
                        <Cell
                          key={`cell-${index}`}
                          fill={BAR_COLORS[index % BAR_COLORS.length]}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Service</TableHead>
                    <TableHead>Source</TableHead>
                    <TableHead className="text-right">Cost</TableHead>
                    <TableHead className="text-right">% of Other</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((item, idx) => (
                    <TableRow key={idx}>
                      <TableCell className="font-medium max-w-[250px] truncate" title={item.service_name}>
                        {item.service_name}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className="text-xs">
                          {item.source_system}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right font-medium">
                        {formatCurrency(item.cost)}
                      </TableCell>
                      <TableCell className="text-right text-muted-foreground">
                        {item.percentage}%
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        ) : (
          <div className="text-center py-8">
            <div className="text-muted-foreground">
              No other cost breakdown data available for this period.
            </div>
            <div className="text-xs text-muted-foreground mt-1">
              This data is populated when the cost pipeline encounters unclassified services.
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
};

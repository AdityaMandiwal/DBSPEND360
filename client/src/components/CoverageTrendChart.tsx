import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { TrendingUp } from 'lucide-react';
import { useCoverageTrend } from '@/hooks/useJobSpends';

const formatDate = (dateStr: string) => {
  try {
    return new Date(dateStr).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return dateStr;
  }
};

const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    const pct = payload[0].value as number;
    const status = pct >= 95 ? 'text-green-600' : pct >= 80 ? 'text-amber-600' : 'text-red-600';
    return (
      <div className="bg-white p-3 border rounded-lg shadow-lg">
        <p className="text-sm text-muted-foreground">{formatDate(label)}</p>
        <p className={`font-semibold ${status}`}>{pct.toFixed(1)}% classified</p>
      </div>
    );
  }
  return null;
};

export const CoverageTrendChart = () => {
  const { data, isLoading } = useCoverageTrend(30);

  if (isLoading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <Skeleton className="h-5 w-40" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-32 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (!data || data.data.length < 2) {
    return null;
  }

  const chartData = data.data.map((p) => ({
    date: p.report_date,
    coverage: p.coverage_pct,
  }));

  const latestPct = chartData[chartData.length - 1]?.coverage ?? 0;
  const gradientColor = latestPct >= 95 ? '#22c55e' : latestPct >= 80 ? '#f59e0b' : '#ef4444';

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium flex items-center">
          <TrendingUp className="mr-2 h-4 w-4 text-muted-foreground" />
          Classification Coverage Trend
        </CardTitle>
        <span
          className={`text-sm font-semibold ${
            latestPct >= 95 ? 'text-green-600' : latestPct >= 80 ? 'text-amber-600' : 'text-red-600'
          }`}
        >
          {latestPct.toFixed(1)}%
        </span>
      </CardHeader>
      <CardContent>
        <div className="h-36">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="coverageGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={gradientColor} stopOpacity={0.3} />
                  <stop offset="95%" stopColor={gradientColor} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="date"
                tickFormatter={formatDate}
                fontSize={10}
                tickLine={false}
                axisLine={false}
              />
              <YAxis
                domain={[
                  (min: number) => Math.max(0, Math.floor(min - 5)),
                  100,
                ]}
                tickFormatter={(v) => `${v}%`}
                fontSize={10}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip content={<CustomTooltip />} />
              <ReferenceLine
                y={95}
                stroke="#22c55e"
                strokeDasharray="3 3"
                strokeOpacity={0.5}
              />
              <ReferenceLine
                y={80}
                stroke="#f59e0b"
                strokeDasharray="3 3"
                strokeOpacity={0.5}
              />
              <Area
                type="monotone"
                dataKey="coverage"
                stroke={gradientColor}
                fill="url(#coverageGradient)"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <div className="flex items-center justify-between mt-2 text-xs text-muted-foreground">
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-green-500" /> &ge;95%
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-amber-500" /> 80-95%
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-red-500" /> &lt;80%
            </span>
          </div>
          <span>{data.data.length} data points</span>
        </div>
      </CardContent>
    </Card>
  );
};

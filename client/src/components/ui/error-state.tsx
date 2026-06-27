// Shared error UI for data-loading failures (plan §3.1 / #4).
//
// SummaryCards previously rendered the same "No data available" message for a
// genuinely empty date range AND a failed request, hiding real backend errors.
// `ErrorState` gives those (and any other) query failures a distinct,
// retry-able surface so an outage never masquerades as an empty result.
//
//   - Default: a full-width card-style block for the KPI strip.
//   - `compact`: an inline variant for top-N sub-sections that sit inside an
//     existing card.

import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface ErrorStateProps {
  message?: string;
  onRetry?: () => void;
  compact?: boolean;
  className?: string;
}

export const ErrorState = ({
  message = "Something went wrong while loading this data.",
  onRetry,
  compact = false,
  className,
}: ErrorStateProps) => {
  const body = (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 text-center",
        compact ? "py-4" : "py-6",
      )}
    >
      <div className="flex items-center gap-2 text-destructive">
        <AlertTriangle
          className={compact ? "h-4 w-4" : "h-5 w-5"}
          aria-hidden="true"
        />
        <span className={compact ? "text-sm font-medium" : "font-medium"}>
          {message}
        </span>
      </div>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );

  if (compact) {
    return <div className={cn("w-full", className)}>{body}</div>;
  }

  return (
    <Card className={cn("border-destructive/40", className)}>
      <CardContent className="p-6">{body}</CardContent>
    </Card>
  );
};

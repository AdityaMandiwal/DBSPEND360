import React, { createContext, useContext, useMemo, useState } from "react";
import { format, subDays } from "date-fns";
import { DateRange } from "@/types/job-spend";

interface DashboardContextValue {
  dateRange: DateRange;
  setDateRange: (range: DateRange) => void;
}

const DashboardContext = createContext<DashboardContextValue | undefined>(
  undefined,
);

export const useDashboard = () => {
  const ctx = useContext(DashboardContext);
  if (!ctx) {
    throw new Error("useDashboard must be used within a DashboardProvider");
  }
  return ctx;
};

interface DashboardProviderProps {
  children: React.ReactNode;
}

// Shared dashboard state that spans tabs. `dateRange` is lifted here so the
// Jobs / Shared Clusters / Instance Pools tabs all reflect the same window
// when the user switches between them. Tab-local concerns (job-name search,
// modal selections, etc.) stay inside their respective tab components.
export const DashboardProvider: React.FC<DashboardProviderProps> = ({
  children,
}) => {
  const [dateRange, setDateRange] = useState<DateRange>(() => ({
    start_date: format(subDays(new Date(), 30), "yyyy-MM-dd"),
    end_date: format(new Date(), "yyyy-MM-dd"),
  }));

  const value = useMemo(() => ({ dateRange, setDateRange }), [dateRange]);

  return (
    <DashboardContext.Provider value={value}>
      {children}
    </DashboardContext.Provider>
  );
};

# Technical Design Document - DBSpend360

## High-Level Design

### System Architecture

DBSpend360 follows a modern three-tier architecture optimized for real-time cost analytics:

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Frontend      │    │   Backend       │    │   Data Layer    │
│   (React)       │◄──►│   (FastAPI)     │◄──►│   (Databricks)  │
│                 │    │                 │    │                 │
│ • Dashboard UI  │    │ • REST APIs     │    │ • SQL Warehouse │
│ • Charts/Tables │    │ • Data Caching  │    │ • Job Spends    │
│ • Export/Email  │    │ • Alert Engine  │    │ • App Configs   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### Technology Stack

**Frontend Stack:**
- **React 18** with TypeScript for type safety
- **Vite** for fast development and optimized builds
- **shadcn/ui** components for professional, consistent UI
- **Tailwind CSS** for responsive, utility-first styling
- **React Query** for efficient data fetching and caching
- **Recharts** for interactive pie charts and visualizations
- **React Table** for advanced table functionality (sorting, filtering, pagination)

**Backend Stack:**
- **FastAPI** for high-performance REST APIs
- **Pydantic** for data validation and serialization
- **Databricks SDK** for SQL warehouse connectivity
- **SQLAlchemy** for query building and data modeling
- **Celery** (optional) for background tasks (scheduled reports)
- **Python-multipart** for file uploads/exports

**Data & Storage:**
- **Primary Data**: `pritam_demo.dbcost360.databricks_job_spends`
- **Configuration**: `pritam_demo.dbcost360.app_configs`
- **SQL Warehouse**: "dbdemos-shared-endpoint"
- **Caching**: In-memory Python cache for query results

### Libraries and Frameworks

**Frontend Dependencies:**
```json
{
  "@tanstack/react-query": "^5.0.0",
  "@tanstack/react-table": "^8.0.0",
  "recharts": "^2.8.0",
  "react-pdf": "^7.0.0",
  "date-fns": "^2.30.0",
  "react-hook-form": "^7.45.0",
  "zod": "^3.22.0",
  "lucide-react": "^0.300.0"
}
```

**Backend Dependencies:**
```python
dependencies = [
    "fastapi>=0.100.0",
    "databricks-sdk>=0.20.0",
    "pydantic>=2.0.0",
    "sqlalchemy>=2.0.0",
    "pandas>=2.0.0",
    "python-multipart>=0.0.6",
    "jinja2>=3.1.0",
    "python-dateutil>=2.8.0"
]
```

### Data Architecture

**Primary Data Model:**
```sql
-- pritam_demo.dbcost360.databricks_job_spends
CREATE TABLE databricks_job_spends (
    cluster_id STRING,
    cloud_cost DOUBLE,
    job_id STRING,
    run_id STRING,
    usage_date DATE,
    databricks_cost DECIMAL(38,6)
);

-- pritam_demo.dbcost360.app_configs
CREATE TABLE app_configs (
    config_key STRING,
    config_value STRING,
    user_id STRING,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

**Data Flow Architecture:**
1. **Real-time Queries**: Direct SQL queries to Databricks for fresh data
2. **Smart Caching**: 5-minute cache for expensive aggregations
3. **Background Processing**: Async jobs for PDF generation and email sending

**Key Queries:**
```sql
-- Main dashboard data with filters
SELECT
    cluster_id,
    job_id,
    run_id,
    usage_date,
    cloud_cost,
    databricks_cost,
    (cloud_cost + databricks_cost) as total_cost
FROM pritam_demo.dbcost360.databricks_job_spends
WHERE usage_date >= ? AND usage_date <= ?
ORDER BY total_cost DESC;

-- Summary metrics
SELECT
    COUNT(*) as total_jobs,
    SUM(cloud_cost + databricks_cost) as total_spend,
    AVG(cloud_cost + databricks_cost) as avg_cost,
    MAX(cloud_cost + databricks_cost) as max_cost
FROM pritam_demo.dbcost360.databricks_job_spends
WHERE usage_date >= ? AND usage_date <= ?;
```

### Integration Points

**Databricks Integration:**
```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementParameterListItem

# SQL Warehouse connection
client = WorkspaceClient()
warehouse_id = "dbdemos-shared-endpoint"

# Execute parameterized queries
response = client.statement_execution.execute_statement(
    warehouse_id=warehouse_id,
    statement="SELECT * FROM pritam_demo.dbcost360.databricks_job_spends WHERE usage_date >= ?",
    parameters=[StatementParameterListItem(name="start_date", value="2025-01-01")]
)
```

**Email Integration:**
```python
# SMTP configuration for alerts and reports
EMAIL_CONFIG = {
    "smtp_server": "smtp.company.com",
    "smtp_port": 587,
    "use_tls": True,
    "username": "dbspend360@company.com"
}
```

## Implementation Plan

### Phase 1: Core Dashboard (Week 1-2)

**Backend Development:**
1. **Database Models & Services**:
   ```python
   # server/models/job_spend.py
   class JobSpend(BaseModel):
       cluster_id: str
       cloud_cost: float
       job_id: str
       run_id: str
       usage_date: date
       databricks_cost: Decimal
       total_cost: float = Field(computed=True)

   # server/services/databricks_service.py
   class DatabricksService:
       async def get_job_spends(self, start_date: date, end_date: date) -> List[JobSpend]
       async def get_summary_metrics(self, start_date: date, end_date: date) -> SummaryMetrics
   ```

2. **REST API Endpoints**:
   ```python
   # server/routers/dashboard.py
   @router.get("/api/job-spends")
   async def get_job_spends(start_date: date, end_date: date, job_name: str = None)

   @router.get("/api/summary")
   async def get_summary_metrics(start_date: date, end_date: date)

   @router.get("/api/job/{job_id}/breakdown")
   async def get_job_cost_breakdown(job_id: str, run_id: str)
   ```

**Frontend Development:**
1. **Core Components**:
   ```tsx
   // client/src/components/Dashboard.tsx
   const Dashboard = () => {
     const [dateRange, setDateRange] = useState(defaultDateRange);
     const [jobFilter, setJobFilter] = useState("");

     return (
       <div className="dashboard-container">
         <SummaryCards />
         <FilterControls />
         <JobSpendTable />
       </div>
     );
   };

   // client/src/components/JobSpendTable.tsx
   const JobSpendTable = () => {
     const { data, isLoading } = useJobSpends(dateRange, jobFilter);

     return (
       <DataTable
         columns={jobSpendColumns}
         data={data}
         onRowClick={handleJobClick}
         pagination
         sorting
       />
     );
   };
   ```

2. **Data Management**:
   ```tsx
   // client/src/hooks/useJobSpends.ts
   export const useJobSpends = (dateRange: DateRange, jobFilter: string) => {
     return useQuery({
       queryKey: ['job-spends', dateRange, jobFilter],
       queryFn: () => apiClient.getJobSpends(dateRange, jobFilter),
       staleTime: 5 * 60 * 1000, // 5 minutes
     });
   };
   ```

### Phase 2: Advanced Analytics (Week 3-4)

**Drill-Down Modal:**
```tsx
// client/src/components/JobBreakdownModal.tsx
const JobBreakdownModal = ({ jobId, runId, isOpen, onClose }) => {
  const { data: breakdown } = useJobBreakdown(jobId, runId);

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-4xl">
        <div className="grid grid-cols-2 gap-6">
          <PieChart data={breakdown.costSplit} />
          <JobDetailsPanel data={breakdown.details} />
        </div>
      </DialogContent>
    </Dialog>
  );
};
```

**Enhanced Filtering:**
```tsx
// client/src/components/FilterControls.tsx
const FilterControls = () => {
  return (
    <div className="filter-controls">
      <DateRangePicker
        value={dateRange}
        presets={["Today", "This Week", "This Month", "Last 30 Days"]}
      />
      <Input
        placeholder="Filter by job name..."
        value={jobFilter}
        onChange={setJobFilter}
      />
    </div>
  );
};
```

### Phase 3: Alerting & Export (Week 5-6)

**Alert Configuration:**
```python
# server/models/alert_config.py
class AlertConfig(BaseModel):
    user_id: str
    threshold_amount: float
    threshold_percentage: float
    email_notifications: bool
    dashboard_highlights: bool

# server/services/alert_service.py
class AlertService:
    async def check_thresholds(self, job_spend: JobSpend) -> List[Alert]
    async def send_email_alert(self, alert: Alert, recipients: List[str])
    async def create_dashboard_highlight(self, alert: Alert)
```

**PDF Export:**
```python
# server/services/export_service.py
class ExportService:
    async def generate_pdf_report(self, job_spends: List[JobSpend], filters: ReportFilters) -> bytes
    async def email_report(self, pdf_data: bytes, recipients: List[str], schedule: str)
```

**Frontend Export Components:**
```tsx
// client/src/components/ExportControls.tsx
const ExportControls = () => {
  const exportToPdf = useMutation({
    mutationFn: (filters) => apiClient.exportJobSpends(filters),
    onSuccess: (pdfBlob) => downloadFile(pdfBlob, 'job-spends.pdf'),
  });

  return (
    <div className="export-controls">
      <Button onClick={() => exportToPdf.mutate(currentFilters)}>
        Export PDF
      </Button>
      <EmailReportDialog />
    </div>
  );
};
```

### Phase 4: Automation & Optimization (Week 7-8)

**Scheduled Reports:**
```python
# server/tasks/scheduled_reports.py
from celery import Celery

@celery.task
async def generate_daily_report():
    job_spends = await databricks_service.get_job_spends(yesterday, yesterday)
    pdf_data = await export_service.generate_pdf_report(job_spends)
    await export_service.email_report(pdf_data, config.daily_recipients)

@celery.task
async def generate_weekly_report():
    # Weekly aggregated report logic
    pass
```

**Performance Optimization:**
```python
# server/services/cache_service.py
from functools import lru_cache
from datetime import datetime, timedelta

class CacheService:
    @lru_cache(maxsize=100)
    async def get_cached_summary(self, date_key: str) -> SummaryMetrics:
        # Cache expensive aggregation queries
        pass

    def invalidate_cache_if_stale(self, cache_time: datetime):
        if datetime.now() - cache_time > timedelta(minutes=5):
            self.get_cached_summary.cache_clear()
```

## Development Workflow

### File Structure
```
server/
├── routers/
│   ├── dashboard.py      # Main dashboard APIs
│   ├── alerts.py         # Alert configuration APIs
│   └── export.py         # PDF export APIs
├── models/
│   ├── job_spend.py      # Data models
│   ├── alert_config.py   # Alert configuration
│   └── summary.py        # Summary metrics
├── services/
│   ├── databricks_service.py  # SQL warehouse integration
│   ├── alert_service.py       # Alert processing
│   ├── export_service.py      # PDF generation
│   └── cache_service.py       # Caching layer
└── tasks/
    └── scheduled_reports.py   # Background tasks

client/src/
├── components/
│   ├── Dashboard.tsx          # Main dashboard layout
│   ├── JobSpendTable.tsx      # Interactive data table
│   ├── SummaryCards.tsx       # Metric cards
│   ├── FilterControls.tsx     # Date/job filtering
│   ├── JobBreakdownModal.tsx  # Drill-down modal
│   └── ExportControls.tsx     # PDF export UI
├── hooks/
│   ├── useJobSpends.ts        # Data fetching
│   ├── useSummaryMetrics.ts   # Summary data
│   └── useAlertConfig.ts      # Alert management
├── lib/
│   ├── api-client.ts          # API integration
│   ├── date-utils.ts          # Date handling
│   └── export-utils.ts        # File download
└── types/
    ├── job-spend.ts           # TypeScript types
    └── api-responses.ts       # API response types
```

### Development Commands
```bash
# Backend development
uv run uvicorn server.app:app --reload --port 8000

# Frontend development
cd client && bun run dev

# Full development stack
./watch.sh

# Type checking
uv run python -m mypy server/
cd client && bun run type-check

# Testing
uv run pytest
cd client && bun test

# Deployment
./deploy.sh
```

### API Design Patterns

**RESTful Endpoints:**
```
GET    /api/job-spends           # List job spends with filters
GET    /api/job-spends/summary   # Summary metrics
GET    /api/job/{id}/breakdown   # Individual job cost breakdown
POST   /api/export/pdf           # Generate PDF export
GET    /api/alerts/config        # Get alert configuration
PUT    /api/alerts/config        # Update alert thresholds
POST   /api/reports/schedule     # Schedule automated reports
```

**Response Format:**
```json
{
  "success": true,
  "data": {
    "job_spends": [...],
    "pagination": {
      "page": 1,
      "per_page": 50,
      "total": 1234
    }
  },
  "meta": {
    "filters_applied": {...},
    "cache_hit": true,
    "query_time_ms": 45
  }
}
```

This technical design provides a robust, scalable foundation for DBSpend360 with clear separation of concerns, efficient data handling, and professional user experience.
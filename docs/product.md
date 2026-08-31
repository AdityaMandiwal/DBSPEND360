# Product Requirements Document - DBSPEND360

## Executive Summary

**Problem Statement:**
Teams running Databricks workloads need clear, interactive visibility into both
the cloud (VM) cost and the Databricks (DBU) cost of their compute, across every
way that compute is consumed — jobs, interactive clusters, instance pools,
pipelines, and SQL warehouses — so they can monitor spend, find cost drivers,
and act on optimization recommendations.

**Solution:**
DBSPEND360 is a Databricks-native cost analytics app that consolidates per-cloud
cost (AWS Cost Explorer today; Azure functional; GCP wired but stubbed) with
DBU cost from Databricks system billing tables. It presents the data through
five focused cost domains and adds AI-driven cost and configuration
recommendations powered by a Databricks foundation model.

## Target Users

### Primary Users
- **Platform / FinOps owners**: monitor cloud + DBU spend across all compute
  types and identify the most expensive jobs, clusters, pools, pipelines, and
  SQL warehouses.
- **Engineering managers**: review their team's workloads and drill into
  individual runs to understand cost breakdowns.

### Secondary Users
- **Administrators**: oversee cost attribution health and reconciliation
  (audit/error logs, cross-tab overlap behavior).

### User Scenarios
- **Cost monitoring**: open the relevant tab, scan summary cards, and review the
  top-N most expensive entities for a chosen date range.
- **Drill-down analysis**: click an entity to see its Cloud vs DBU cost
  breakdown and per-run / per-entity details.
- **Optimization**: run the AI "Analyze" action on a job, cluster, pool, or
  pipeline, or SQL warehouse to get grounded cost and configuration
  recommendations.

## Core Features

### 1. Five cost domains (tabs)
The app is organized into five tabs (see `client/src/components/Dashboard.tsx`),
each backed by its own rollup table and Databricks Job branch:

| Tab | Rollup table (`config/app.dev.config`) |
|---|---|
| **Job Clusters** | `dbspend360.04june.dbspend360_total_job_spends` |
| **All-Purpose Clusters** | `dbspend360.04june.dbspend360_total_all_purpose_spends` |
| **Instance Pools** | `dbspend360.04june.dbspend360_total_pool_spends` |
| **Pipeline Compute** | `dbspend360.04june.dbspend360_total_pipeline_spends` |
| **SQL Warehouses** | `dbspend360.04june.dbspend360_total_sql_warehouse_spends` |

SQL Warehouse cost basis is type-dependent: Serverless DBU includes
infrastructure; Classic and Pro are labeled DBU-only because customer-cloud VM,
disk, and network charges are not currently attributable to `warehouse_id`.

Each tab provides summary cards, date-range presets, filtering, pagination,
top-N context, and entity drill-downs. Sorting and drill-down presentation vary
by domain: the Instance Pools table is cost-ranked and expands pool → day →
cluster, while its modal focuses on pool configuration and AI analysis.

> **Cross-tab cost model:** the five tabs intentionally look at the same compute
> through different lenses, so they **overlap by design and do not sum to the
> AWS bill**. See `README.md` §4 for the full DBU overlap and EC2/EBS
> attribution model.

### 2. Data source & warehouse
- **SQL Warehouse**: `warehouse_id = 8baced1ff014912d`
  (`config/app.dev.config` → `[databricks]`).
- **Schema**: `dbspend360.04june`.
- The five rollup tables above are produced by the DBSPEND360 Databricks Job
  (coverage + cloud ingest → per-domain DBU + spend tasks; SQL Warehouses is
  DBU-only). Tables are created once by `create_all_tables`, not in the job DAG.
  The app also reads `system.lakeflow.jobs` and `system.compute.clusters` to
  enrich names and cluster details when granted.

### 3. Interactive data table
- All relevant columns from each domain's rollup table.
- Sort on fields, filter by name, pagination for large datasets.
- Date-range filtering with presets (Today, This Week, This Month, Last 30
  Days); default view is the last 30 days.

### 4. Cost breakdown drill-down
- **Trigger**: click a row / entity in a tab's table.
- **Display**: entity-specific details appropriate to the domain. Job and
  cluster paths include Cloud-vs-DBU breakdowns; the Instance Pool modal shows
  pool configuration, tags, creator metadata, and grounded AI analysis.

### 5. Summary dashboard cards
- Per-tab key metrics: total spend, cloud vs DBU split, top contributors, and
  counts for the selected date range. Cards update with the date filter.

### 6. AI cost & configuration analysis
- Per-entity **Analyze** actions generate grounded recommendations using the
  `databricks-claude-sonnet-4` foundation model
  (`server/services/llm_service.py`):
  - Job cost analysis (`/api/job/{job_id}/analyze`)
  - Cluster configuration analysis (`/api/cluster/{cluster_id}/analyze`)
  - Instance pool analysis (`/api/instance-pools/{pool_id}/analyze`)
  - Pipeline analysis (`/api/pipelines/{pipeline_id}/analyze`)
- Prompts substitute the active cloud provider so insights stay grounded.
- Gated by `enable_cost_analysis` / `enable_cluster_analysis` flags in
  `config/app.dev.config`.

### 7. Cloud-provider awareness
- `[cloud] platform` (AWS / Azure / GCP) drives notebook selection, cluster
  attribute reads, dynamic UI labels (via `/api/cloud-platform`), and LLM prompt
  wording. AWS and Azure are functional end-to-end; GCP is wired through config
  and the UI/LLM layers but its cost-explorer ETL is a stub.

## User Stories

### Cost monitoring
1. **As a platform owner**, I want to switch between Job Clusters, All-Purpose
   Clusters, Instance Pools, Pipeline Compute, and SQL Warehouses, so I can see
   spend through the lens that matches my question.
2. **As a manager**, I want to filter by name and date range, so I can analyze
   specific workloads or time periods.

### Drill-down & breakdown
1. **As a user**, I want to click an entity to see its Cloud vs DBU cost split
   and details, so I can understand its cost drivers.

### Optimization
1. **As an engineer**, I want AI recommendations for a job/cluster/pool/pipeline,
   so I can act on concrete optimization suggestions.

## Success Metrics

### User Engagement
- Feature adoption across all five tabs and the AI Analyze actions.
- Average session duration sufficient for meaningful drill-down analysis.

### Operational Impact
- Time to identify the top cost drivers for a given window.
- Adoption of AI recommendations for optimization.

### Data Quality & Performance
- Dashboard load time target: < 3 seconds.
- Cost attribution reconciles to its explorer source within $0.01 per grain
  (see `README.md` §4.3).

## Technical Requirements

### Data Integration
- **Rollup tables**: the five `dbspend360.04june.dbspend360_total_*` tables.
- **SQL Warehouse**: `8baced1ff014912d`.
- **System tables** (optional, requires grants): `system.lakeflow.jobs`,
  `system.compute.clusters`.
- **Query pattern**: parameterized SQL via the Databricks SDK; React Query
  caching on the frontend.

### Performance Requirements
- Dashboard load: < 3 seconds.
- Handle large rollup tables efficiently with pagination and grouping.

### User Experience
- Professional shadcn/ui + Tailwind design with light/dark theme toggle.
- Responsive layout; intuitive tab navigation; deep-linkable tabs via `?tab=`.

## Roadmap note

This document describes the **currently shipped** product. Features that have
been discussed but are **not implemented** (e.g. threshold-based alerting, PDF/
CSV export, email/scheduled reports) are intentionally not described here. Note
that `config/app.dev.config` ships `enable_export = true`, but no export
functionality is currently wired to that flag.

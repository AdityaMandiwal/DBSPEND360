# DBSPEND360 technical audience Q&A

This document is presenter prep for conversations with FDEs, solution architects,
platform teams, and FinOps teams. It covers the current backend, data lineage,
security model, deployment, accuracy boundaries, and known gaps. The live demo
script below is what to click; the Q&A after it is what to say when challenged.
It intentionally excludes React implementation details.

The answers are written to be spoken. The source notes are internal references
for follow-up.

## Short positioning statement

DBSPEND360 is a Databricks-native cost analytics app. A Databricks Job combines
DBU usage from system tables with tag-attributable AWS or Azure cloud cost,
writes five Unity Catalog rollups, and a FastAPI service queries those rollups
through a SQL warehouse. Optional AI analysis uses a Databricks-hosted foundation
model and receives selected facts about the workload being analyzed.

## Facts to state clearly

- The five domains are cost lenses, not disjoint billing buckets. Do not add
their totals together.
- AWS and Azure explorer implementations exist. The checked-in workflow still
needs provider-specific deployment edits, especially because Azure workspace
coverage discovery is currently unconditional.
- DBU cost is intended to use Databricks list price, not a customer's negotiated
rate. This assumes one applicable price row for each SKU and time.
- DBU staging values are USD. No foreign-exchange conversion is implemented.
- Classic and Pro SQL warehouse values are DBU-only. Serverless warehouse DBU
includes infrastructure.
- The app has no per-user or row-level authorization layer. Data visibility is
determined by Databricks App access and the app service principal's grants.
- Export, scheduled reports, budgets, and user-configurable spend-threshold
alerts are not implemented. Internal ETL data-quality alarms do exist.



## Product and architecture



### 1. What problem does DBSPEND360 solve?

It attributes Databricks compute spend to operational entities such as jobs,
clusters, pools, pipelines, and SQL warehouses. It combines DBU and attributable
cloud infrastructure cost where both are available.

Source: `README.md`, `docs/data_model.md`

### 2. Which cost domains are covered?

Five: Job Clusters, All-Purpose Clusters, Instance Pools, Pipeline Compute, and
SQL Warehouses. Each domain has its own rollup table and backend API.

Source: `docs/data_model.md`, `config/app.dev.config`

### 3. What is the high-level architecture?

There are two parts: a 12-task Databricks Job that loads curated Delta rollups
in Unity Catalog, and a Databricks App running FastAPI. Tables are created once
by `jobs/ddls/create_all_tables.ipynb`; the job does not include DDL tasks.
`cloud_cost_explorer` and `covered_workspaces` feed four DBU → rollup branches
(Job, All-Purpose, Pool, Pipeline). SQL Warehouses is a fifth DBU → rollup
branch that depends on coverage only. Cloud cost is joined in the rollup
notebooks. The app uses a SQL warehouse for data access and Model Serving for
optional AI analysis.

Source: `jobs/resource_templates/DBSPEND360.yaml`,
`jobs/ddls/create_all_tables.ipynb`, `server/app.py`, `app.yaml`

### 4. Where does the backend run?

It runs as a Databricks App with `uvicorn server.app:app`. In production,
Databricks Apps supplies the runtime OAuth identity used by the Databricks SDK.

Source: `app.yaml`, `server/services/databricks_service.py`

### 5. Can the supplied workflow be deployed unchanged on AWS or Azure?

No. Notebook paths and customer parameters must be changed, and app `platform`
must be aligned manually with the job's `cloud_provider`. The current workflow
also runs Azure-only workspace discovery unconditionally, so an AWS deployment
must skip or replace that task and its dependencies.

Source: `jobs/resource_templates/DBSPEND360.yaml`,
`jobs/notebooks/dbspend360_covered_workspaces_app.ipynb`,
`config/app.dev.config`

### 6. What happens during a typical request?

The FastAPI router validates filters, calls `DatabricksService`, and runs SQL
Statement Execution on the configured warehouse. Sort fields are allowlisted and
text is manually escaped, but the current queries do not use bound parameters.
The JSON APIs can be consumed programmatically through the Databricks App ingress.

Source: `server/routers/`, `server/services/databricks_service.py`,
`server/services/llm_service.py`

### 7. Does the app calculate all costs at request time?

No. The main tab queries use precomputed rollup tables. Request-time work is
mostly filtering, grouping, pagination, and optional system-table enrichment;
the Job DBU product breakdown is a documented live system-table exception.

Source: `docs/data_model_reference.md`, `server/routers/dashboard.py`

## Sources, ingestion, and refresh



### 8. Where does DBU usage come from?

From `system.billing.usage`. The pipeline joins it to
`system.billing.list_prices` and groups different metadata fields for each cost
domain. Accuracy assumes one applicable list-price row for each SKU and time.

Source: `docs/data_model_reference.md`

### 9. Where does cloud infrastructure cost come from?

AWS deployments call AWS Cost Explorer. Azure deployments call Azure Cost
Management. Both write cluster and pool explorer tables. Job, All-Purpose,
Pool, and Pipeline **rollup** notebooks join those tables to DBU staging.
DBU ingest notebooks do not read cloud explorer output.

Source: `jobs/notebooks/aws_cloud_cost_explorer_app.ipynb`,
`jobs/notebooks/azure_cloud_cost_explorer_app.ipynb`,
`jobs/resource_templates/DBSPEND360.yaml`

### 10. Which tables does the app query?

Primary tab spend comes from five `dbspend360_total_*` rollups. The service may
also query system tables for names, configuration, and coverage; the
other-cost table for drill-down; and `system.billing.usage` for the optional Job
product breakdown.

Source: `config/app.dev.config`, `docs/data_model_reference.md`,
`server/services/databricks_service.py`

### 11. How does incremental loading work?

Most cost notebooks derive a date window from the last successful audit record,
rewind by the configured overlap, and MERGE the recomputed slice. The job
template defaults `overlap_days` to 10; Azure covered-workspace discovery is a
separate full-snapshot overwrite.

Source: `jobs/notebooks/utils_common.ipynb`,
`jobs/resource_templates/DBSPEND360.yaml`

### 12. How often is the data refreshed?

The repository does not define a schedule. Freshness is determined by how often
the customer schedules the Databricks Job, plus source-system and cloud-billing
lag; backend summaries expose the latest available dates where applicable.

Source: `jobs/resource_templates/DBSPEND360.yaml`

### 13. How much history is loaded initially?

The first successful ETL window defaults to approximately one year. Older
history is not automatically backfilled unless the deployment changes the
window or loads it separately.

Source: `jobs/notebooks/utils_common.ipynb`

## Data scope, joins, and calculations



### 14. What qualifies as Job Cluster spend?

Billing rows must have a job run ID and belong to a cluster whose
`cluster_source` is `JOB`. The rollup grain is cluster, job, run, and usage date.

Source: `docs/data_model.md`, `docs/data_model_reference.md`

### 15. What qualifies as All-Purpose Cluster spend?

The branch selects clusters with source `UI` or `API` and billing rows without a
job run ID. Its rollup grain is cluster, attributed user, and usage date.

Source: `docs/data_model.md`, `docs/data_model_reference.md`

### 16. How reliable is user attribution for All-Purpose clusters?

It is owner-based: the pipeline uses the latest cluster `owned_by` value, with
`__unknown__` as fallback. It should not be presented as exact per-user query or
session metering on shared clusters.

Source: `docs/data_model_reference.md`

### 17. What qualifies as Instance Pool spend?

Any billing row with `instance_pool_id` is included in the pool lens. The grain
is pool, cluster, and day; rows with no cluster use the synthetic
`__pool_overhead__` key.

Source: `docs/data_model.md`, `docs/data_model_reference.md`

### 18. Does the pool cloud value include all VMs used by the pool?

No. It includes only ClusterId-free idle or warm capacity. Active pool-backed VM
cost remains on cluster-attributed lenses: Job, All-Purpose, and classic
Pipeline where applicable.

Source: `README.md`, `server/services/llm_service.py`

### 19. What qualifies as Pipeline Compute spend?

The branch selects billing rows carrying `dlt_pipeline_id`. It covers DLT and
related products represented by those billing rows, including DBSQL materialized
views, online tables, vector search, model serving, and AI functions.

Source: `docs/data_model_reference.md`

### 20. How is classic pipeline cloud cost allocated?

Cluster-day cloud cost is first allocated to pipelines by their share of DBU on
that cluster and day. It is then distributed across billing products by each
product's DBU share.

Source: `jobs/notebooks/pipeline_spends_app.ipynb`,
`docs/data_model_reference.md`

### 21. How are serverless, classic, and mixed pipelines identified?

A group is serverless when the cluster ID is null, the SKU contains
`SERVERLESS`, or the product is serverless-only. A rollup becomes mixed when
both serverless and classic signals occur in the same grouping.

Source: `jobs/notebooks/dbspend360_pipeline_dbu_cost_app.ipynb`,
`docs/data_model_reference.md`

### 22. What is included for SQL Warehouses?

Billing rows must have `billing_origin_product = 'SQL'` and a non-null warehouse
ID. They are aggregated by warehouse and day and enriched with the latest
warehouse metadata.

Source: `jobs/notebooks/dbspend360_sql_warehouse_dbu_cost_app.ipynb`,
`docs/data_model.md`

### 23. Is SQL Warehouse cost complete?

Serverless is treated as complete because infrastructure is included in the DBU
price. Classic and Pro are labeled `dbu_only` because separate customer-cloud
VM, disk, and network charges are not attributable to `warehouse_id` in the
current model.

Source: `docs/data_model.md`, `server/services/databricks_service.py`

### 24. How is DBU cost calculated?

The intended calculation is `usage_quantity * pricing.default`, joined by SKU
and the applicable price time range. DBU staging is emitted in USD; because
cloud and currency are not price-join keys, deployments should validate that
each usage row has one applicable price row.

Source: `docs/data_model_reference.md`

### 25. How is cluster cloud cost joined to Databricks usage?

AWS `ClusterId` or Azure `clusterid` tags become `cluster_id`. The rollups join
cloud and DBU data by cluster ID, usage date, and exact currency. There is no FX
conversion, so a non-USD cloud row will not join to a USD DBU row.

Source: `README.md`, `docs/data_model_reference.md`

### 26. How is pool cloud cost joined?

Cloud data is grouped by `DatabricksInstancePoolId` and day. Rows that also carry
a cluster tag are removed, and the remaining idle/warm amount is written to the
pool overhead row.

Source: `README.md`, `docs/data_model_reference.md`

### 27. How is `total_cost` calculated when cloud cost is missing?

Rollups use a null-safe sum: available cloud cost plus available DBU cost. A null
cloud value therefore preserves known DBU spend, but the total may be
incomplete.

Source: `docs/data_model_reference.md`

## Understanding cloud cost segments



### 27a. What do `compute_cost`, `storage_cost`, and `network_cost` mean?

They are classifications of attributable customer-cloud charges, not
Databricks DBU charges. On Azure, `compute_cost` is the exact `Virtual Machines`
meter category. `storage_cost` covers meter categories containing `storage` or
`disk`. `network_cost` covers categories containing `bandwidth`,
`virtual network`, `load balancer`, or `network watcher`. These values describe
the tagged cloud-billing slice visible to the explorer; they are not estimates
of every compute, storage, or network charge in the customer's subscription.

Source: `jobs/notebooks/azure_cloud_cost_explorer_app.ipynb`,
`docs/data_model.md`

### 27b. Does storage cost mean all data storage used by a workload?

No. It means Azure charges whose `MeterCategory` matches the storage
classification and whose billing row carries a usable Databricks cluster tag.
It should not be described as the complete cost of DBFS, cloud object storage,
Unity Catalog managed storage, or every disk used elsewhere in the
subscription.

Source: `jobs/notebooks/azure_cloud_cost_explorer_app.ipynb`,
`jobs/notebooks/utils_common.ipynb`

### 27c. Does network cost include all data transfer and shared networking?

No. It includes only cluster-tagged Azure meter categories matching the network
patterns. Shared or untagged costs such as NAT gateways, general VPC or VNet
charges, and unrelated data transfer cannot be defensibly assigned to a
Databricks workload and are not proportionally allocated by the app.

Source: `jobs/notebooks/azure_cloud_cost_explorer_app.ipynb`, `README.md`

### 27d. How are Azure meter categories filtered and classified?

Azure Cost Management is queried for amortized cost grouped by day,
`clusterid`, and `MeterCategory`. Rows without a non-empty cluster ID or a valid
cost date are excluded from the cluster explorer. The remaining meter category
is normalized by trimming whitespace and comparing case-insensitively. Exact
rules run first: `Virtual Machines` maps to compute, while `Virtual Machines Licenses` and `Virtual Machine Licenses` map to other. Storage and network
substring rules run next. Everything unmatched is retained as `other_cost`; it
is not dropped or silently treated as compute.

Source: `jobs/notebooks/azure_cloud_cost_explorer_app.ipynb`,
`jobs/notebooks/utils_common.ipynb`

### 27e. What is `other_cost`?

It is the residual Azure cloud segment. It includes known non-compute items such
as the virtual-machine license categories and any meter category that does not
match the compute, storage, or network rules. Unclassified values are written to
the other-cost breakdown for drill-down and logged for triage. This makes
`other_cost` a reviewable fallback, not an indication that the charge was
discarded.

Source: `jobs/notebooks/azure_cloud_cost_explorer_app.ipynb`,
`release/Azure Credentials and Permissions Setup.md`

### 27f. Are these segments available on every cloud and every tab?

No. Azure cluster-attributed cost is segmented and can flow into the Job,
All-Purpose, and classic Pipeline lenses. AWS currently stores tagged EC2 and
EBS as one `cloud_cost` amount, so its segment columns are null. Pool cost is
also intentionally a single cloud bucket on both providers: the query uses its
grouping capacity to separate idle or warm pool cost from active cluster cost.
Classic and Pro SQL Warehouses remain DBU-only, while serverless warehouse
infrastructure is already included in the DBU price.

Source: `README.md`, `release/AWS Credentials and Permissions Setup.md`,
`docs/data_model.md`

## Accuracy, coverage, and limitations



### 28. Do the five tab totals add up to the cloud bill?

No. They are overlapping analytical lenses. The same DBU can appear under a job,
a pool, and a pipeline, so only compare or aggregate within a chosen lens.

Source: `README.md`, `docs/data_model.md`

### 29. Which cloud costs are deliberately not allocated?

Shared or untagged infrastructure such as NAT gateways, object storage, load
balancers, VPC costs, and data transfer is not proportionally assigned to
workloads. The app is not a general-ledger replacement.

Source: `README.md`

### 30. Does DBU cost reflect the customer's contract or discounts?

No. It uses `system.billing.list_prices` and `pricing.default`. Contracted DBU
discounts, credits, and private pricing adjustments are not applied by the
current pipeline.

Source: `docs/data_model_reference.md`

### 31. How are reservations and savings plans handled in cloud cost?

AWS requests amortized cost. The Azure explorer code does too, but the current
demo schema has not completed a full-history reload on that basis. Do not
describe the displayed Azure values as consistently amortized until the
explorer tables and four cloud-backed rollups have been fully refreshed.

Source: `jobs/notebooks/aws_cloud_cost_explorer_app.ipynb`,
`jobs/notebooks/azure_cloud_cost_explorer_app.ipynb`

### 32. What does a missing cloud value mean?

It means unavailable or unattributable, not zero. Common causes are billing API
lag, missing tags, an uncovered workspace, or serverless infrastructure already
included in DBU.

Source: `README.md`, `docs/data_model.md`

### 33. How does the app disclose cloud-billing coverage?

The current coverage model is Azure-subscription-specific. It discovers
workspaces in one subscription and tags other DBU rows as uncovered. Rollups
preserve known DBU, but the SQL Warehouse headline excludes uncovered DBU and
reports it separately. AWS has no equivalent account-coverage discovery.

Source: `server/routers/coverage.py`, `docs/data_model.md`,
`jobs/notebooks/dbspend360_covered_workspaces_app.ipynb`

### 34. Does it support multiple workspaces?

Only with caveats. ETL can scan or filter multiple workspaces, but Job and
All-Purpose keys omit `workspace_id`, and the Pool key also omits it. Resource ID
collisions across workspaces are therefore not fully prevented; only Pipeline
uses workspace ID in its primary grain.

Source: `jobs/resource_templates/DBSPEND360.yaml`,
`docs/data_model_reference.md`

### 35. Does Azure ingestion support multiple subscriptions?

Not in one configured run. The current Azure path is subscription-scoped;
workspaces outside that scope keep their DBU but are marked as not covered for
cloud cost. Multi-subscription orchestration must be added by the adopter.

Source: `docs/plans/azure-cost-subscription-coverage.md`,
`jobs/resource_templates/DBSPEND360.yaml`

### 36. Is GCP supported?

GCP is not implemented end to end: its cloud-cost explorer raises
`NotImplementedError`. AWS and Azure explorer paths are implemented, but both
still require provider-specific deployment integration described in question 5.

Source: `jobs/notebooks/gcp_cloud_cost_explorer_app.ipynb`, `README.md`

### 37. Which currencies are supported?

DBU values are emitted as USD. AWS and Azure explorers preserve their returned
currency, but the pipeline performs no currency conversion and joins cloud to
DBU on exact currency. Treat non-USD cloud billing as unsupported without an FX
normalization change.

Source: `jobs/notebooks/dbspend360_dbu_cost_app.ipynb`,
`jobs/notebooks/azure_cloud_cost_explorer_app.ipynb`,
`jobs/notebooks/aws_cloud_cost_explorer_app.ipynb`

### 38. How are late-arriving data and corrections handled?

The overlap window reprocesses recent dates and generally upserts matching keys.
Most branches do not remove source-deleted or re-keyed rows; the All-Purpose
branch has bounded stale-key deletion. Older corrections or stale keys may need
a wider backfill and explicit cleanup.

Source: `jobs/notebooks/utils_common.ipynb`, `jobs/notebooks/*_app.ipynb`

### 39. How is attribution quality checked?

Checks vary by branch and provider. All-Purpose, Pool, and Pipeline have explicit
$0.01 reconciliation logic, while audit/error logging and near-zero monitors are
not uniform across every branch. Do not promise a single all-five-domain
reconciliation invariant.

Source: `README.md`, `jobs/ddls/dbspend360_audit_log.ipynb`,
`jobs/ddls/dbspend360_error_log.ipynb`

## Security, permissions, and operations



### 40. What identity does the app use to query Databricks?

In Databricks Apps it uses the app service principal through injected OAuth. In
local development it can use a host and PAT.

Source: `server/services/databricks_service.py`,
`server/services/llm_service.py`

### 41. Is there application-level RBAC or row-level filtering?

No. The FastAPI routes do not apply caller-specific data filters. Databricks App
access controls who can open the app, while the app service principal's grants
define the data every app user can query. A locally exposed backend has no
equivalent route middleware, and CORS is configured for all origins.

Source: `server/routers/`, `README.md`

### 42. What grants do the app and ETL identities need?

The app identity needs warehouse `CAN USE`, UC `USE` and `SELECT`, and model
`CAN QUERY` for AI. The separate ETL run identity needs system-table reads,
catalog/schema writes, and access to the provider credential or secret scope.
Exact grants depend on which endpoints and cost domains are enabled.

Source: `README.md`

### 43. What happens if system-table grants are missing?

Some rollup-only summaries can still load, but this is not universally graceful.
All-Purpose list paths join `system.compute.clusters`, and coverage reads billing,
list-price, and workspace system tables; names, details, and AI baselines also
depend on system access.

Source: `README.md`, `server/services/databricks_service.py`

### 44. How are cloud-provider credentials handled?

AWS uses a Unity Catalog service credential with `ce:GetCostAndUsage`. Azure
uses an Entra service principal and Databricks secret scope; it needs Cost
Management query access plus permission to list subscription resource groups for
coverage discovery. That discovery also reads `system.access.workspaces_latest`.

Source: `release/AWS Credentials and Permissions Setup.md`,
`release/Azure Credentials and Permissions Setup.md`, `deploy.sh`

### 45. Is this a multi-tenant application?

Not at the application layer. A deployment reads the datasets granted to one app
service principal, and there is no tenant key, organization hierarchy, or
caller-based row filter. Separate datasets and deployments, or a new
authorization design, are needed for caller-specific isolation.

Source: `server/services/databricks_service.py`, `server/routers/`

### 46. What controls query latency and scale?

Rollups reduce scan and join work, and list APIs use server-side grouping,
sorting, and pagination. Capacity is still bounded by the selected SQL warehouse
and app process; SDK calls and polling are synchronous inside async-shaped
service methods. Caches are in-process only, and the repo has no published
concurrency benchmark or SLA.

Source: `server/services/databricks_service.py`, `config/app.dev.config`

### 47. How are timeouts, failures, and monitoring handled?

SQL Statement Execution uses a configurable 30-second wait/poll interval by
default, not a guaranteed end-to-end request ceiling. Routers log exceptions and
return generic errors; pipeline operations write audit/error records, and
Databricks App logs are available through the platform.

Source: `server/services/databricks_service.py`, `server/routers/`,
`README.md`, `dba_logz.py`

## AI analysis and adoption



### 48. What model powers the AI analysis, and what does it receive?

The current endpoint is `databricks-claude-sonnet-4`. Inputs are
endpoint-specific and can include selected cost totals, configuration fields,
coverage state, or derived history. The service does not send an unrestricted
dump of the source tables or write prompts and responses to an app-owned table.

Source: `server/services/llm_service.py`

### 49. How does the app reduce hallucination risk, and what if the model fails?

Prompts require claims to cite input numbers, forbid invented benchmarks, and
include domain-specific caveats. The output is not programmatically checked for
citation accuracy. Most model errors use structured fallbacks, but callers
should still handle endpoint errors; analysis is advisory and never changes
customer resources.

Source: `server/services/llm_service.py`

### 50. What is required for adoption, and what is not included?

Adoption requires provider-specific workflow edits, cloud billing access and
tags, Unity Catalog tables, a SQL warehouse, ETL and app grants, and optional
Model Serving access. Recurring freshness also requires the adopter to configure
a schedule; manual runs work. The repo does not ship a complete customer Asset
Bundle, production config, GCP cloud ingestion, per-user RBAC, contracted-rate
pricing, FX conversion, budgets, forecasting, export, user-configurable spend
alerts, or scheduled reports.

Source: `README.md`, `jobs/resource_templates/DBSPEND360.yaml`,
`docs/product.md`

## Live application demo (8–10 minutes)

Job Clusters is the long walkthrough. The other four tabs are short. If time
runs short, skip All-Purpose or Pools before skipping SQL Warehouses: that tab
is the one that most often surprises people (DBU-only Classic/Pro, and KPI
totals that exclude uncovered DBU).

If a coverage banner is visible at the top of a tab, mention it once: some
workspaces are outside the ingested Azure billing subscription. DBU from those
workspaces still appears on Job, All-Purpose, Pool, and Pipeline. SQL Warehouses
excludes that DBU from the headline and shows it as DBU Outside Cloud Scope.

### 1. Application overview

Show

- Five tabs: Job Clusters, All-Purpose Clusters, Instance Pools, Pipeline
  Compute, SQL Warehouses
- Filters & Controls: date presets (Today through Last 90 Days) plus custom
  start/end; search by name or ID
- Summary KPIs, cost mix, and ranked contributors on each tab
- Default window: last 30 days (today plus the previous 29 calendar days)

Speaker guide

- These are five cost lenses, not five slices of one bill. Do not add the tab
  totals together. The same DBU can appear under a job, a pool, and a pipeline.
- Cloud cost is de-duplicated more carefully than DBU: idle/warm pool VMs sit
  on Instance Pools; active cluster VMs sit on Job, All-Purpose, or classic
  Pipeline.
- Default last 30 days. Date range updates the KPIs and the table. Search
  updates the table only.
- Pattern on every tab: summary, then ranked list, then expand, then details
  and optional AI.

### 2. Job Clusters — detailed walkthrough

#### A. Summary view

Show

- Total Spend (period length; DBU from non-covered workspaces is included and
  called out when present)
- Total Jobs, with a daily average spend footnote
- Average Cost per job execution
- Highest Cost for a single job execution
- Cost Breakdown: cloud versus Databricks DBU. On Azure, also compute, storage,
  network, and Other (unclassified); Other is clickable. On AWS, one EC2/EBS
  cloud amount versus DBU
- Top 5 Costliest Jobs, with run counts

Speaker guide

- Immediate spend picture for job-cluster compute in the window.
- Workload volume versus typical execution cost versus the single most expensive
  run.
- Azure segments are tagged customer-cloud charges, not DBU. Other is residual
  meters, not dropped spend.
- Top 5 is the investigation queue.

#### B. Date and search controls

Show

- Switch a preset (Last 7 Days or This Month works well)
- Optionally set a custom range
- Search by job name or Job ID
- Confirm KPIs and Top 5 follow the date range; the table follows date and
  search

Speaker guide

- Flexible reporting period without leaving the tab.
- Search is for targeting a known job, not for changing the headline totals.
- Stakeholder questions like "what did this job cost last week?" are a filter
  change, not a new report.

#### C. Job table

Show

- Job Spending Details, default-sorted by total cost descending
- Columns: Job ID (workspace link), Job Name, Runs, cloud (Azure:
  Compute / Storage / Network / Other; AWS: EC2/EBS), Databricks cost, Total
- High Cost badge when a job's total in the window is above $1,000
- Expand a high-cost job; runs load on expand (first 10, with Show all)

Speaker guide

- Ranked cost drivers for the filtered window.
- Full cost picture: cloud plus list-price DBU.
- Job ID opens the job in the Databricks workspace.
- Expand is job-to-run traceability. Missing cloud on a run often means
  pool-backed compute or billing that has not landed yet.

#### D. Run-level details

Show

- Click a run, then Details
- Cost Distribution pie and covered/uncovered mix
- Job ID, Run ID, Cluster ID(s), usage period
- On Azure, compute / storage / network / other shares of covered cloud
- High Cost Job badge when the run is above $1,000

Speaker guide

- This is cost composition for one execution, not the whole job.
- Covered versus uncovered matters when workspaces sit outside the billing
  subscription.
- Cluster IDs are clickable; that is the path into configuration analysis.
- Evidence for optimization: expensive run, date, cluster, cloud versus DBU.

#### E. AI cost analysis

Show

- AI Cost Analysis in the same details panel (when the cost-analysis flag is
  on)
- Click a Cluster ID and open cluster configuration analysis if time permits

Speaker guide

- Findings are grounded in the numbers and config passed to the model
  (`databricks-claude-sonnet-4`). They are advisory. Nothing is changed in the
  workspace.
- Human review is required. Treat this as a first pass, not an action plan.

### 3. All-Purpose Clusters — brief walkthrough

Show

- Total Spend, Active Clusters, Active Users, Avg per Cluster-Day
- Cost Breakdown (same cloud-versus-DBU mix; Azure segments when present)
- Top 5 Costliest Clusters and Top 5 Costliest Users
- By Cluster and By User
- Expand one cluster for daily cost, or open a cluster name for config and AI

Speaker guide

- Interactive / UI-and-API cluster spend, not job clusters.
- Users are cluster owners (`owned_by`), not per-query session metering. Shared
  clusters will over-attribute to the owner.
- By User is the chargeback-shaped view; By Cluster is the utilization and
  config view.

### 4. Instance Pools — brief walkthrough

Show

- Total Spend, Cost Mix, Active Pools, Active Clusters
- Daily Pool Spend Trend (average and peak)
- Top 5 Costliest Pools
- Expand a pool to days, then a day to attached clusters
- Click a pool name for config and AI (time permitting)

Speaker guide

- Shared capacity: DBU for anything billed with an instance pool ID, plus
  ClusterId-free idle/warm cloud VMs.
- Active pool-backed VM cost stays on Job, All-Purpose, or classic Pipeline.
  That is why this total must not be added to those tabs.
- Trend is for idle/warm plus pool DBU shape, not for every VM the pool ever
  launched.
- Day then cluster is how you attribute pool spend to attached workloads.

### 5. Pipeline Compute — brief walkthrough

Show

- Total Spend, Cost Mix, pipeline count (serverless / classic / mixed)
- Serverless versus classic versus mixed spend footnote
- Spend by Workload (DLT is often not the largest slice)
- Workload-type chips: they narrow both the KPIs and the table
- Expand one pipeline for daily spend; open the name for analysis

Speaker guide

- This tab is pipeline-backed billing (`dlt_pipeline_id`), including DLT, DBSQL
  materialized views, online tables, vector search, model serving, and AI
  functions. Do not call the total "DLT spend".
- Serverless DBU already includes infrastructure (no separate VM line). Classic
  includes DBU plus available cluster cloud cost.
- List price, not invoice. Classic pipelines on pools can also appear on
  Instance Pools.

### 6. SQL Warehouses — brief walkthrough

Show

- Tracked DBU Spend (landed days and daily average)
- Warehouses by type: serverless, Pro, classic
- Cost Basis: serverless complete versus Classic/Pro DBU-only
- DBU Outside Cloud Scope (excluded from the headline, unlike the other tabs)
- Spend by Type and Top 5 Costliest Warehouses
- Expand a warehouse for daily spend; open the name for config and AI

Speaker guide

- There is no attributable customer-cloud VM line on this tab.
- Serverless DBU includes infrastructure. Classic and Pro are DBU-only: VM,
  disk, and network on the customer cloud are not tagged to `warehouse_id`.
- Uncovered-workspace DBU is excluded from Tracked DBU Spend and shown
  separately. Say that out loud so it is not confused with the other tabs.
- "Metadata unavailable" is common; cost can still be exact without a
  `system.compute.warehouses` snapshot.

## Presenter close

The strongest fit is a platform or FinOps team that wants Databricks-native,
entity-level cost investigation and can complete the provider-specific
deployment work. Lead with traceable lineage and drill-down. State the overlap,
USD/list-price basis, coverage, multi-workspace, and authorization boundaries
before the audience has to ask.
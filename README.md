# DBSPEND360

## 1. Overview

* DBSPEND360 is a Databricks-native solution that provides clear job-level visibility into cloud and DBU spends for Databricks workloads.

* Tracks end-to-end cost at job, run, and cluster level for Databricks jobs.
* Combines cloud VM cost (AWS Cost Explorer or Azure Cost Management) with Databricks DBU cost from system billing tables.
* Produces a consolidated `dbspend360_total_job_spends` table as the single source of truth for job-level cost.
* Includes audit and error logging to support incremental loads, monitoring, and reconciliation.
* Powers the DBSPEND360 Databricks App, which provides dashboards and AI-driven cost and performance recommendations.

> **Status:** AWS and Azure are functional end-to-end today. GCP is wired through the config, UI label, and LLM layers, but the GCP cloud cost explorer ETL (`jobs/notebooks/gcp_cloud_cost_explorer_app.ipynb`) is a stub that raises `NotImplementedError` and needs to be implemented before GCP can be selected as the active provider.


<br>
<br>


## 2. Architecture

### Logical Architecture Diagram

![DBSPEND360 logical architecture: cloud cost explorers and Databricks DBU usage feeding the dbspend360_total_job_spends table, which powers the Databricks App with dashboards and LLM-driven insights.](release/readme_images/architecture.png)


### Implementation Flow

![DBSPEND360 implementation flow: per-cloud ETL notebooks ingest into staging tables, dbspend360_dbu_cost_app joins DBU usage, and databricks_job_spends_app produces the consolidated dbspend360_total_job_spends table consumed by the app.](release/readme_images/implementation_flow.png)



## 3. Usage

* Clone the DBSPEND360 Databricks app repo:

    ```bash
    git clone https://github.com/AdityaMandiwal/DBSPEND360.git
    cd DBSPEND360
    ```

* `jobs/` contains all the DDL notebooks, ETL notebooks, and the Databricks Job resource template for DBSPEND360.
* `release/` contains the product release doc and the per-cloud credentials setup guides needed for data ingestion from each cost explorer:
    * `release/AWS Credentials and Permissions Setup.md` — required AWS Cost Explorer / CUR APIs, IAM policy (inline JSON), cluster-tagging convention used to join line items back to Databricks `cluster_id`, credential delivery options (Databricks Secrets / instance profile / SPN), and a verification `aws ce get-cost-and-usage` command.
    * `release/Azure Credentials and Permissions Setup.docx` — Azure Cost Management service principal (SPN) registration, required role assignments on the billing scope, and how to wire the SPN credentials into the notebook.
    * `release/GCP Credentials and Permissions Setup.md` — stub placeholder; pending the GCP cost explorer implementation. Outlines the GCP APIs (Cloud Billing / BigQuery), IAM roles, and verification steps that will be needed once the notebook is implemented.

### Prerequisites

Install the following on your local machine before running `setup.sh` (the script will verify each one):

* Git
* [uv](https://docs.astral.sh/uv/) — Python package manager
* [Bun](https://bun.sh/) — JavaScript package manager
* Node.js 18 or newer
* [Databricks CLI](https://docs.databricks.com/dev-tools/cli/index.html) (v0.265.0+ for `databricks apps` support)
* On macOS only: Homebrew (used by `setup.sh` to install missing dependencies)

### Configure Databricks authentication

Configure local Databricks authentication using **either**:

* **A named profile in `~/.databrickscfg`** (recommended for repeated use). Use any name you like — `DEFAULT` works, but a workspace-specific name is clearer once you have more than one workspace. `setup.sh` lists the profiles found in this file via `databricks auth profiles` and asks which one to use:

    ```ini
    [my-workspace]
    host  = https://<your-workspace>.cloud.databricks.com
    token = <your-personal-access-token>
    ```

* **Environment variables** (set in your shell or `.env.local`). Use these when you don't want a profile file on disk — `setup.sh` will pick them up if you select PAT authentication:

    ```bash
    export DATABRICKS_HOST=https://<your-workspace>.cloud.databricks.com
    export DATABRICKS_TOKEN=<your-personal-access-token>
    ```

### Deploy the data pipeline (Databricks Job)

The Databricks App reads from `dbspend360_total_job_spends`, which is produced by a multi-task Databricks Job. **Deploy and run this pipeline before deploying the app**, otherwise the dashboard renders empty and the AI insights have no data to analyze.

1. Import everything under `jobs/notebooks/` and `jobs/ddls/` into your Databricks workspace.
2. Run `jobs/ddls/create_all_tables.ipynb` once against the catalog/schema you intend to use. This orchestrator notebook invokes every DDL under `jobs/ddls/` and creates: `dbspend360_audit_log`, `dbspend360_error_log`, `dbspend360_cloud_cost_explorer`, `dbspend360_pool_cloud_cost_explorer`, `dbspend360_dbu_cost`, `dbspend360_other_cost_breakdown`, `dbspend360_total_job_spends`, `dbspend360_all_purpose_dbu_cost`, `dbspend360_total_all_purpose_spends`, `dbspend360_pool_dbu_cost`, `dbspend360_total_pool_spends`, `dbspend360_pipeline_dbu_cost`, and `dbspend360_total_pipeline_spends`. These back the four cost tabs in the app — Job Clusters, All-Purpose Clusters, Instance Pools, and Pipeline Compute — each populated by its own parallel branch described in step 3 below.
3. Use `jobs/resource_templates/DBSPEND360.yaml` as the basis for the Databricks Job. It defines nine tasks across four parallel branches that fan out from a shared cloud-cost-ingest task:

   ```
   cloud_cost_explorer
   ├─ Dbspend360dbu_costs ──────────────── databricks_job_spends       (Job Clusters branch)
   ├─ Dbspend360_all_purpose_dbu_costs ─── all_purpose_spends          (All-Purpose Clusters branch)
   └─ Dbspend360_pool_dbu_costs ────────── pool_spends                 (Instance Pools branch)

   Dbspend360_pipeline_dbu_costs ───┐
   cloud_cost_explorer ─────────────┴──── pipeline_spends              (Pipeline Compute branch)
   ```

   * `cloud_cost_explorer` → `${cloud_provider}_cloud_cost_explorer_app` — cloud-source-agnostic; feeds every branch. On AWS it now writes **two** explorer tables: `dbspend360_cloud_cost_explorer` (grouped by `ClusterId`, feeds Job/All-Purpose/Pipeline) and `dbspend360_pool_cloud_cost_explorer` (grouped by `DatabricksInstancePoolId`, feeds Instance Pools).
   * Job Clusters branch (writes `dbspend360_total_job_spends`):
     * `Dbspend360dbu_costs` → `dbspend360_dbu_cost_app`
     * `databricks_job_spends` → `databricks_job_spends_app`
   * All-Purpose Clusters branch (writes `dbspend360_total_all_purpose_spends`):
     * `Dbspend360_all_purpose_dbu_costs` → `dbspend360_all_purpose_dbu_cost_app`
     * `all_purpose_spends` → `all_purpose_spends_app`
   * Instance Pools branch (writes `dbspend360_total_pool_spends`):
     * `Dbspend360_pool_dbu_costs` → `dbspend360_pool_dbu_cost_app`
     * `pool_spends` → `pool_spends_app`
   * Pipeline Compute branch (writes `dbspend360_total_pipeline_spends`):
     * `Dbspend360_pipeline_dbu_costs` → `dbspend360_pipeline_dbu_cost_app`
     * `pipeline_spends` → `pipeline_spends_app` (depends on both its DBU task **and** `cloud_cost_explorer`)

   The branches are independent — failures in one do not block the others — and the app reads each branch's output table through its respective tab. See `docs/plan_all_purpose_clusters_tab.md`, `docs/plan_instance_pools_tab.md`, and `docs/plan_pool_pipeline_ec2_cost.md` for the design rationale (cluster-source filter, owner-based attribution, EC2/EBS cloud-cost joins, and the cross-tab overlap model documented in section 4 below).

   **Update the hard-coded `notebook_path` values** in the YAML to match where you imported the notebooks (the template currently points at a developer workspace path), and review the default `parameters` block (`catalog`, `cloud_provider`, `overlap_days`, `schema`, `workspace_ids`) before deploying.
4. Create the job either via the Databricks Workflows UI using the YAML as a reference, or by wrapping it in a Databricks Asset Bundle.
5. Run the job at least once and confirm `dbspend360_total_job_spends` has rows before moving on to the app deployment steps below.


### Step by step setup

* In the `config/` folder change the values in `app.dev.config` for:
    1. `platform` (under `[cloud]`) — set to the cloud where your Databricks workloads run: `AWS`, `Azure`, or `GCP`. The shipped value may not match your environment, so verify it explicitly. See [Cloud Provider Selection](#cloud-provider-selection) below for what this drives.
    2. `warehouse_id` — the SQL warehouse the app should query.
    3. `table_name` — fully qualified `catalog.schema.table` for `dbspend360_total_job_spends`.
    4. `schema_name` — fully qualified `catalog.schema` used by the app.


![app_dev_config](release/readme_images/app_dev_config.png)

* Run `./setup.sh` and follow the prompts in this order:

![setup_1](release/readme_images/setup_1.png)

  1. **Choose an authentication method:**
     * `1` — Personal Access Token (PAT). `setup.sh` then prompts for `DATABRICKS_HOST` and the PAT itself (hidden input), and writes both to `.env.local`.
     * `2` — Configuration Profile. `setup.sh` runs `databricks auth profiles` to list the profiles in your `~/.databrickscfg`, prompts you to pick one (defaults to `DEFAULT`), and tests the connection. If the profile is missing or invalid you can let it run `databricks auth login --profile <name>` for you.
  2. **App name for deployment** — must be lowercase; digits and hyphens are allowed, but uppercase letters and other special characters are not.
  3. **Source code path** — workspace path under which the app's source code will be stored on deploy (defaults to a path derived from your app name).


![setup_2](release/readme_images/setup_2.png)

![setup_3](release/readme_images/setup_3.png)


* Run the deploy command: `./deploy.sh --verbose --create` (this creates and deploys the app)



![setup_4](release/readme_images/setup_4.png)


### Required Grants for the App Service Principal

When the app is deployed as a Databricks App, it runs under a **service principal** that may not have explicit permissions on your warehouse, Unity Catalog objects, or model serving endpoints — even if it belongs to an admins group. Without these grants, the app will return empty results or fail to render AI insights.

Find your app's service principal ID from the Databricks App settings page, then apply the grants below.

#### SQL warehouse

Grant via the SQL Warehouse permissions UI (or via REST API):

* `CAN USE` on the SQL warehouse referenced by `warehouse_id` in `config/app.dev.config` (or whichever env-specific config file you maintain — only `app.dev.config` ships in the repo today).

#### Unity Catalog (catalog / schema / table)

Run the following SQL in a Databricks SQL editor or notebook:

```sql
-- Replace <YOUR_CATALOG>, <YOUR_SCHEMA>, and <APP_SERVICE_PRINCIPAL_ID> with your values.

-- Allow the service principal to see the catalog
GRANT USE CATALOG ON CATALOG <YOUR_CATALOG> TO `<APP_SERVICE_PRINCIPAL_ID>`;

-- Allow the service principal to see the schema
GRANT USE SCHEMA ON SCHEMA <YOUR_CATALOG>.<YOUR_SCHEMA> TO `<APP_SERVICE_PRINCIPAL_ID>`;

-- Allow the service principal to read all tables in the schema.
-- `SELECT ON SCHEMA` inherits to every existing table AND any tables
-- created later in this schema, so you don't need per-table grants.
GRANT SELECT ON SCHEMA <YOUR_CATALOG>.<YOUR_SCHEMA> TO `<APP_SERVICE_PRINCIPAL_ID>`;
```

#### Model serving endpoint (for AI insights)

The app uses `databricks-claude-sonnet-4` as the foundation model to generate cost and performance recommendations. Grant:

* `CAN QUERY` on the `databricks-claude-sonnet-4` model serving endpoint.

If this grant is missing, the dashboard still loads but the AI Cost Analysis panel will not render.

#### Optional: System Table Access

The app also queries `system.lakeflow.jobs` and `system.compute.clusters` to enrich cost data with job names and cluster details. Granting SELECT on these tables requires **account admin** privileges. Without these grants the app still works, but job names and cluster details may show as null.

If an account admin is available, ask them to run:

```sql
GRANT SELECT ON TABLE system.lakeflow.jobs TO `<APP_SERVICE_PRINCIPAL_ID>`;
GRANT SELECT ON TABLE system.compute.clusters TO `<APP_SERVICE_PRINCIPAL_ID>`;
```


![app_1](release/readme_images/app_1.png)

![app_2](release/readme_images/app_2.png)

![app_3](release/readme_images/app_3.png)


### Cloud Provider Selection

DBSPEND360 is cloud-agnostic at the data layer (`dbspend360_cloud_cost_explorer.cloud_cost`) and label-aware at the UI / LLM layer. Pick a provider in `config/app.dev.config` (or whichever env-specific config file you maintain). The shipped value in the repo is set to one cloud for local development — always set this explicitly for your environment:

```ini
[cloud]
# Supported platforms: AWS, Azure, GCP
platform = AWS   # example only — replace with AWS, Azure, or GCP
```

> **Note:** GCP is selectable in config and wired through the cluster-attribute, label-rendering, and LLM layers, but the `gcp_cloud_cost_explorer_app` notebook is a stub and currently raises `NotImplementedError`. Only AWS and Azure are functional end-to-end today.

The chosen `platform` value drives, end-to-end:

1. **Notebook selection** — the `cloud_provider` job parameter in
   `jobs/resource_templates/DBSPEND360.yaml` resolves to
   `${cloud_provider}_cloud_cost_explorer_app`, i.e.
   `aws_cloud_cost_explorer_app`, `azure_cloud_cost_explorer_app`, or
   `gcp_cloud_cost_explorer_app`.
2. **Cluster-attribute reads** — `get_cluster_details` reads whichever of
   `aws_attributes` / `azure_attributes` / `gcp_attributes` is populated on
   `system.compute.clusters` (see `server/services/databricks_service.py`).
3. **Label rendering** — the `/api/cloud-platform` endpoint feeds
   `CloudPlatformContext` so frontend tables/cards render
   "EC2 Cost", "Azure Compute Cost", or "GCE Cost" dynamically.
4. **LLM prompts** — cluster-analysis prompts in `server/services/llm_service.py`
   substitute the active provider's name so insights stay grounded.



## 4. Cost attribution across tabs (and why they don't sum to the AWS bill)

The app exposes four cost tabs — **Job Clusters**, **All-Purpose Clusters**,
**Instance Pools**, and **Pipeline Compute**. Each one looks at the *same*
underlying compute through a different lens, so **the tabs intentionally overlap
and are not meant to add up to your AWS invoice.** Treat each tab as a focused
view, not a slice of a pie. This is the same already-accepted behavior the DBU
numbers have always had.

### 4.1 DBU overlap is by design

A single run can be counted in more than one tab depending on how you ask about
it. For example, a job whose cluster borrows VMs from an instance pool shows DBU
in both the **Job Clusters** tab (attributed to the job) and the **Instance
Pools** tab (attributed to the pool). That is not double-billing — it is the same
spend described from two angles. Per-tab DBU is correct *within* its lens; summing
DBU *across* tabs is not meaningful. (See `docs/plan_instance_pools_tab.md` §3.6
for the full cross-tab DBU overlap analysis.)

### 4.2 EC2 / EBS cloud cost overlap

Cloud (EC2/EBS) cost is attributed by AWS resource tag, and the two explorer
tables are kept **disjoint** so the cloud numbers do not double-count across tabs:

* `dbspend360_cloud_cost_explorer` groups EC2/EBS by the **`ClusterId`** tag and
  feeds the Job Clusters, All-Purpose Clusters, and Pipeline Compute tabs.
* `dbspend360_pool_cloud_cost_explorer` groups EC2/EBS by the
  **`DatabricksInstancePoolId`** tag and feeds the Instance Pools tab. On this
  account, pooled instances carry the pool tag but **not** `ClusterId` (verified
  empirically — see `docs/plan_pool_pipeline_ec2_cost.md` §4.3, "Case B"), and the
  pool explorer additionally **nets out** any cost that *also* carries
  `ClusterId` (the §4.3 guard). So **pool EC2 cost is disjoint from cluster EC2
  cost — for cloud cost the Instance Pools tab is additive, not overlapping, with
  the other three tabs.**

Even so, **no tab — and no sum of tabs — equals the AWS EC2 bill.** Only
tag-attributable compute is captured; account-wide shared infrastructure (NAT
gateways, S3, ELB, VPC, data transfer, and any untagged compute) is deliberately
**not** allocated onto jobs, clusters, pools, or pipelines. Proportional
allocation of that shared infra is tracked separately in
`docs/plan_aws_cost_attribution_reconciliation.md` and is intentionally out of
scope here.

A few honest-by-design gaps you will see rendered as `—` (a dash) plus a tooltip,
never as a misleading `$0`:

* **Serverless pipelines** — EC2 cost is bundled into the serverless DBU rate;
  there is no separate VM line to show.
* **Per-cluster rows inside a pool drill-down** — pool VM cost is tracked at the
  pool level (AWS tags pool instances with `DatabricksInstancePoolId`, not
  `ClusterId`), not per attached cluster.
* **A classic cluster / pool-day with no matching explorer row yet** — Cost
  Explorer lag or an untagged resource; the value is *unknown*, not zero.

### 4.3 Reconciliation and monitoring

Every cloud-cost join is reconciled back to its explorer source and is
self-monitoring:

* **Reconciliation invariant** — for each `(cluster_id, day, currency)`
  (pipeline) and each `(instance_pool_id, day, currency)` (pools), the cloud cost
  written to the rollup must equal the explorer source within **$0.01**. The
  rollup notebooks assert this on the intermediate join (before the grain
  collapse) and write any mismatch to `dbspend360_error_log` instead of failing
  silently.
* **Post-write monitors** — if a window's pool (or cluster) `cloud_cost`
  collapses to ~0 while DBU is non-zero — the classic signature of a dropped
  billing tag — the explorer and rollup notebooks raise a non-silent alarm rather
  than quietly writing zeros.
* **Audit + error logs** — `dbspend360_audit_log` records per-run row counts and
  windows; `dbspend360_error_log` captures reconciliation mismatches and isolated
  failures (e.g. the pool-tag CE call is wrapped in its own `try/except` so a
  pool-tag failure never breaks the cluster explorer path or the job DAG).

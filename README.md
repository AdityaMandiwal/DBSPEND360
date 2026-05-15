# DBSPEND360

## 1. Overview

* DBSPEND360 is a Databricks-native solution that provides clear job-level visibility into cloud and DBU spends for Databricks workloads.

* Tracks end-to-end cost at job, run, and cluster level for Databricks jobs.
* Combines cloud VM cost (AWS Cost Explorer, Azure Cost Management, or — once implemented — GCP Cloud Billing) with Databricks DBU cost from system billing tables.
* Produces a consolidated dbspend360_total_job_spends table as the single source of truth for job-level cost.
* Includes audit and error logging to support incremental loads, monitoring, and reconciliation.
* Powers the DBSPEND360 Databricks App, which provides dashboards and AI-driven cost and performance recommendations.


<br>
<br>


## 2. Architecture

### Logical Architecture Diagram

![architecture](release/readme_images/architecture.png)


### Implementation Flow

![Implementation](release/readme_images/implementation_flow.png)



## 3. Usage

* Clone the DBSPEND360 Databricks app repo:

    ```bash
    git clone https://github.com/AdityaMandiwal/DBSPEND360.git
    cd DBSPEND360
    ```

* `jobs/` contains all the DDL notebooks, ETL notebooks, and the Databricks Job resource template for DBSPEND360.
* `release/` contains the product release doc and the per-cloud credentials setup guides needed for data ingestion from each cost explorer:
    * `release/AWS Credentials and Permissions Setup.md` — AWS Cost Explorer / CUR setup.
    * `release/Azure Credentials and Permissions Setup.docx` — Azure Cost Management SPN setup.
    * `release/GCP Credentials and Permissions Setup.md` — GCP Cloud Billing setup (stub; pending implementation).

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

* **A profile in `~/.databrickscfg`** (recommended for repeated use):

    ```ini
    [DEFAULT]
    host  = https://<your-workspace>.cloud.databricks.com
    token = <your-personal-access-token>
    ```

* **Environment variables** (set in your shell or `.env.local`):

    ```bash
    export DATABRICKS_HOST=https://<your-workspace>.cloud.databricks.com
    export DATABRICKS_TOKEN=<your-personal-access-token>
    ```

### Step by step setup

* In the config folder change the values in  app.dev.config for:
    1. Warehouse_id
    2. Table_name (catalog.schema.table)
    3. Schema_name (catalog.schema)


![app_dev_config](release/readme_images/app_dev_config.png)

* Run setup.sh and follow the below steps:

![setup1](release/readme_images/setup_1.png)

  1. Choose the Authentication type
  2. Choose the databricks configuration profile you want to use to deploy the app
  3. Give an app name: must be lowercase; digits and hyphens are allowed, but uppercase letters and other special characters are not.
  4. Give the source code path to store all the app related code/assets


![setup2](release/readme_images/setup2.png)

![setup3](release/readme_images/setup3.png)


* Run the deploy command: `./deploy.sh --verbose --create` (this creates and deploys the app)



![setup4](release/readme_images/setup4.png)


### Deploy the data pipeline (Databricks Job)

The Databricks App reads from `dbspend360_total_job_spends`, which is produced by a multi-task Databricks Job. Deploy the pipeline before (or in parallel with) the app:

1. Import everything under `jobs/notebooks/` and `jobs/ddls/` into your Databricks workspace.
2. Run `jobs/ddls/create_all_tables.ipynb` once against the catalog/schema you intend to use, to create `dbspend360_cloud_cost_explorer`, `dbspend360_dbu_cost`, `dbspend360_total_job_spends`, `dbspend360_audit_log`, and `dbspend360_error_log`.
3. Use `jobs/resource_templates/DBSPEND360.yaml` as the basis for the Databricks Job. It defines three tasks executed in order:
   * `cloud_cost_explorer` → `${cloud_provider}_cloud_cost_explorer_app`
   * `Dbspend360dbu_costs` → `dbspend360_dbu_cost_app`
   * `databricks_job_spends` → `databricks_job_spends_app`

   **Update the hard-coded `notebook_path` values** in the YAML to match where you imported the notebooks (the template currently points at a developer workspace path), and review the default `parameters` block (`catalog`, `cloud_provider`, `overlap_days`, `schema`, `workspace_ids`) before deploying.
4. Create the job either via the Databricks Workflows UI using the YAML as a reference, or by wrapping it in a Databricks Asset Bundle.


### Required Grants for the App Service Principal

When the app is deployed as a Databricks App, it runs under a **service principal** that may not have explicit permissions on your warehouse, Unity Catalog objects, or model serving endpoints — even if it belongs to an admins group. Without these grants, the app will return empty results or fail to render AI insights.

Find your app's service principal ID from the Databricks App settings page, then apply the grants below.

#### SQL warehouse

Grant via the SQL Warehouse permissions UI (or via REST API):

* `CAN USE` on the SQL warehouse referenced by `warehouse_id` in `config/app.<env>.config`.

#### Unity Catalog (catalog / schema / table)

Run the following SQL in a Databricks SQL editor or notebook:

```sql
-- Replace <YOUR_CATALOG>, <YOUR_SCHEMA>, and <APP_SERVICE_PRINCIPAL_ID> with your values.

-- Allow the service principal to see the catalog
GRANT USE CATALOG ON CATALOG <YOUR_CATALOG> TO `<APP_SERVICE_PRINCIPAL_ID>`;

-- Allow the service principal to see the schema
GRANT USE SCHEMA ON SCHEMA <YOUR_CATALOG>.<YOUR_SCHEMA> TO `<APP_SERVICE_PRINCIPAL_ID>`;

-- Allow the service principal to read all tables in the schema
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


![app1](release/readme_images/app1.png)

![app2](release/readme_images/app2.png)


### Cloud Provider Selection

DBSPEND360 is cloud-agnostic at the data layer (`dbspend360_cloud_cost_explorer.cloud_cost`) and label-aware at the UI / LLM layer. Pick a provider in `config/app.<env>.config`:

```ini
[cloud]
# Supported platforms: AWS, Azure, GCP
platform = AWS
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

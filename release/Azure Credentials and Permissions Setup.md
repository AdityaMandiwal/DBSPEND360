# Azure Credentials and Permissions Setup — DBSPEND360

This document describes the Azure permissions, credentials, and Databricks
configuration required to run the Azure cloud cost explorer ETL
(`jobs/notebooks/azure_cloud_cost_explorer_app.ipynb`) and to power the
DBSPEND360 dashboard when `[cloud] platform = AZURE` is set in
`config/app.<env>.config`.

It is the Azure counterpart to `AWS Credentials and Permissions Setup.md` in
this same `release/` folder. It is kept as Markdown so the credential wiring and
role names stay reviewable in pull requests.

You will obtain and wire up five things:

- **Subscription ID** — which subscription's cost to read
- **Tenant ID** — the Entra ID (Azure AD) directory
- **Client ID** — the app registration (service principal)
- **Client Secret** — the app registration's password
- **Role assignment** — Cost Management Reader at the subscription scope

---

## 1. Required Azure API

The ETL uses the **Azure Cost Management** API:

| API | Operation | Purpose |
| --- | --- | --- |
| Microsoft Cost Management (`Microsoft.CostManagement`) | `Query.usage` (`POST .../query`) | Daily `ActualCost` grouped by the `clusterid` tag and the `MeterCategory` dimension, used to build per-cluster, per-service daily cost. |

Implementation notes:

- Authenticated with the **`azure-identity`** `ClientSecretCredential`; the
  query is issued through the **`azure-mgmt-costmanagement`** SDK
  (`CostManagementClient.query.usage`). The notebook `%pip install`s both at the
  top, so no cluster library config is required.
- Token audience for `nextLink` pagination is
  `https://management.azure.com/.default`.
- Billing scope is **subscription-level**: `/subscriptions/{subscription_id}`.
- Metric is **`ActualCost`** (sum of `Cost`), `Daily` granularity. Unlike AWS,
  Azure cost is segmented into compute / storage / network / other via
  `MeterCategory` classification.

---

## 2. Get the Subscription ID

The Subscription ID tells Azure which account's costs to read.

1. Go to <https://portal.azure.com> and sign in with your organization account.
2. Search for **Subscriptions** in the top bar and open it.
3. Click the subscription you want to analyze.
4. On the **Overview** page, copy the **Subscription ID**
   (`xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`).

This becomes the notebook's `subscription_id` parameter (see §6).

---

## 3. Create an App Registration (service principal)

This creates a non-human identity so the job can access Azure securely.

1. In the portal, search for **Microsoft Entra ID** (formerly Azure Active
   Directory) and open it.
2. Left menu → **App registrations** → **+ New registration**.
3. Fill in the form:
   - **Name**: `Azure-Cost-Reporter` (any name is fine)
   - **Supported account types**: *Accounts in this organizational directory only*
   - **Redirect URI**: leave empty
4. Click **Register**.

### Copy the Client ID and Tenant ID

After registering, Azure opens the app's **Overview** page. Copy:

| Field on the Overview page | Use as |
| --- | --- |
| Application (client) ID | **Client ID** |
| Directory (tenant) ID | **Tenant ID** |

---

## 4. Create the Client Secret

This is the password for the App Registration.

1. Inside the App Registration, click **Certificates & secrets**.
2. Under **Client secrets**, click **+ New client secret**.
3. Fill in:
   - **Description**: `CostReporterSecret`
   - **Expires**: 12 or 24 months (recommended)
4. Click **Add**.

> ⚠️ **Copy the secret Value immediately** — it cannot be retrieved again after
> you leave the page. Note the expiry date and plan to rotate before it lapses,
> or the ETL will start failing authentication.

This becomes the **Client Secret**.

---

## 5. Assign the required role (most important)

Without this step the ETL fails authorization.

Assign **one** of the following roles to the app registration **at the
Subscription scope**:

| Role | Notes |
| --- | --- |
| **Cost Management Reader** | ✅ Recommended — least privilege for cost reads |
| Reader | Acceptable (broader) |
| Billing Reader | Acceptable |

### How to assign

1. Go to **Subscriptions** → your target subscription.
2. Left menu → **Access control (IAM)**.
3. **+ Add** → **Add role assignment**.
4. **Role**: `Cost Management Reader`.
5. **Assign access to**: *User, group, or service principal*.
6. **Select**: search for your app name (e.g. `Azure-Cost-Reporter`).
7. Click **Save**.

> ⏳ Role assignments can take 1–5 minutes to propagate.

---

## 6. Wire credentials into Databricks

The ETL does **not** take the client secret as a plaintext parameter. It reads
tenant/client/secret from a **Databricks secret scope** at runtime:

```python
tenant_id     = dbutils.secrets.get(scope, "tenant_id")
client_id     = dbutils.secrets.get(scope, "client_id")
client_secret = dbutils.secrets.get(scope, "client_secret")
```

### 6.1 Create the secret scope and secrets

```bash
databricks secrets create-scope dbspend360-azure   # any scope name you like

databricks secrets put-secret dbspend360-azure tenant_id
databricks secrets put-secret dbspend360-azure client_id
databricks secrets put-secret dbspend360-azure client_secret
```

The three secret **keys must be named exactly** `tenant_id`, `client_id`, and
`client_secret`.

### 6.2 Notebook / job parameters (widgets)

| Widget | Meaning |
| --- | --- |
| `catalog` | Unity Catalog catalog for the output tables |
| `schema` | schema for the output tables |
| `overlap_days` | re-query overlap for idempotent MERGE (default `3`, min 2) |
| `subscription_id` | the Azure Subscription ID from §2 |
| `scope` | the **Databricks secret scope** name from §6.1 (e.g. `dbspend360-azure`) |

> Note: the `scope` parameter is the *Databricks secret scope*, not the Azure
> billing scope. The Azure billing scope is derived internally as
> `/subscriptions/{subscription_id}`.

---

## 7. Required cluster tag

The ETL groups Cost Management results by the tag key **`clusterid`** (matched
case-insensitively) and joins on its value, which must equal the Databricks
`cluster_id`.

Ensure every Databricks cluster (interactive and job) propagates a
`clusterid` tag onto its underlying Azure resources (VMs and disks). If the tag
is missing or not yet activated for cost reporting, the query returns rows that
cannot be attributed to a cluster (the "Empty cost data / Missing tags" failure
mode below).

---

## 8. Databricks configuration

```ini
# config/app.<env>.config
[cloud]
platform = AZURE
```

---

## 9. Output tables

The ETL writes two Unity Catalog tables under `<catalog>.<schema>`:

| Table | Contents |
| --- | --- |
| `dbspend360_cloud_cost_explorer` | per-cluster, per-day cost split into `compute_cost` / `storage_cost` / `network_cost` / `other_cost`, summing to `cloud_cost` |
| `dbspend360_other_cost_breakdown` | per-`MeterCategory` detail behind the `other_cost` bucket, for drill-down and unclassified-meter triage |

The invariant `cloud_cost = compute_cost + storage_cost + network_cost + other_cost`
is enforced. Any `MeterCategory` not matching the compute/storage/network
patterns is routed to `other` (never silently to compute) and logged to
`dbspend360_error_log`.

---

## 10. Final checklist

- [ ] Subscription ID captured
- [ ] App registration created; Tenant ID + Client ID captured
- [ ] Client Secret created and stored
- [ ] `Cost Management Reader` assigned to the app at subscription scope
- [ ] Databricks secret scope created with `tenant_id` / `client_id` / `client_secret`
- [ ] `clusterid` tag propagated onto cluster resources
- [ ] Notebook params (`subscription_id`, `scope`, `catalog`, `schema`) set

---

## 11. Verifying setup

Confirm the service principal can read cost (run with its credentials, or use
the Azure CLI logged in as the SP):

```bash
az login --service-principal -u <client_id> -p <client_secret> --tenant <tenant_id>

az rest --method post \
  --url "https://management.azure.com/subscriptions/<subscription_id>/providers/Microsoft.CostManagement/query?api-version=2023-11-01" \
  --body '{
    "type": "ActualCost",
    "timeframe": "MonthToDate",
    "dataset": { "granularity": "Daily",
      "aggregation": { "totalCost": { "name": "Cost", "function": "Sum" } } }
  }'
```

A `200` response with `properties.rows` confirms Cost Management access. Then
run `azure_cloud_cost_explorer_app` end-to-end and confirm rows land in
`<catalog>.<schema>.dbspend360_cloud_cost_explorer`, with a `SUCCESS` entry in
`dbspend360_audit_log`.

---

## 12. Common errors and causes

| Error | Cause |
| --- | --- |
| Authentication failed | Wrong client secret (or expired); wrong tenant ID |
| Authorization failed / Access denied | Role not assigned, still propagating, or assigned at the wrong scope |
| Empty cost data | Missing/unactivated `clusterid` tag on resources, or no spend in the window |
| Wrong subscription | `subscription_id` points at a subscription the SP can't read |
| `429 Too many requests` | Cost Management tenant/QPU rate limit; the ETL backs off and retries, but a sustained tenant-level limit can fail the run |

# AWS Credentials and Permissions Setup — DBSPEND360

This document describes the AWS permissions, credential wiring, and Databricks
configuration required to run the AWS cloud cost explorer ETL
(`jobs/notebooks/aws_cloud_cost_explorer_app.ipynb`) and to power the DBSPEND360
dashboard when `[cloud] platform = AWS` is set in `config/app.<env>.config`.

It is the AWS counterpart to `Azure Credentials and Permissions Setup.md` in
this same `release/` folder. This AWS guide is kept as Markdown so the IAM
policy JSON stays reviewable in pull requests.

---

## 1. Required AWS API

The ETL uses exactly **one** AWS API:

| API | Operation | Purpose |
| --- | --- | --- |
| AWS Cost Explorer (`ce`) | `GetCostAndUsage` | Day-level cost grouped by the `ClusterId` / `DatabricksInstancePoolId` tag and the `SERVICE` dimension, filtered to the cluster-attributable EC2 family. |

Notes:

- **Region**: the Cost Explorer endpoint is only available in **`us-east-1`**,
  regardless of where your clusters run. The notebook hard-codes
  `CE_REGION = 'us-east-1'`.
- **Metric**: the ETL queries the **`AmortizedCost`** metric by default.
- **No CUR / no S3**: the ETL does **not** read Cost and Usage Reports or any
  S3 bucket. It assembles per-cluster and per-pool cost entirely from
  `GetCostAndUsage`.

---

## 2. Authentication — Databricks Unity Catalog Service Credential

The notebook authenticates to AWS through a **Databricks Unity Catalog service
credential** named **`dbspend-read-ce`**:

```python
session = boto3.Session(
    botocore_session=dbutils.credentials.getServiceCredentialsProvider('dbspend-read-ce'),
    region_name='us-east-1',
)
self.client = session.client('ce')
```

A UC service credential maps to an **AWS IAM role** that Databricks assumes on
the job's behalf. There is no long-lived access key, no instance profile, and
no Databricks secret involved.

### 2.1 Create the IAM role

Create an IAM role (e.g. `dbspend360-cost-explorer-read`) with:

**Permission policy** (read-only, minimal):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DBSpend360CostExplorerRead",
      "Effect": "Allow",
      "Action": [
        "ce:GetCostAndUsage"
      ],
      "Resource": "*"
    }
  ]
}
```

> `ce:*` actions do not support resource-level scoping, so `Resource` must be
> `"*"`. The single `ce:GetCostAndUsage` action is all the ETL needs.
>
> Optional: the ad-hoc discovery / reconciliation scripts under
> `claude_scripts/` (`ce_tag_discovery.py`, `aws_cost_recon_assert.py`) also
> call `ce:GetTags` and `ce:GetDimensionValues`. Add those two actions only if
> you intend to run those diagnostics; the production ETL does not need them.

**Trust policy**: allow the Databricks Unity Catalog AWS role to assume this
role. When you create the service credential in Databricks (next step),
Databricks shows you the exact external ID and principal ARN to paste into the
trust relationship. The trust policy follows the standard UC storage/service
credential shape:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "AWS": "<databricks-uc-role-arn-shown-in-ui>" },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": { "sts:ExternalId": "<external-id-shown-in-ui>" }
      }
    }
  ]
}
```

### 2.2 Create the service credential in Databricks

In the Databricks workspace, create a service credential named **exactly**
`dbspend-read-ce` pointing at the IAM role above. Either:

- **UI**: Catalog → Credentials → *Create credential* → *Service credential*,
  or
- **SQL**:

  ```sql
  CREATE SERVICE CREDENTIAL `dbspend-read-ce`
    AWS_IAM_ROLE 'arn:aws:iam::<account-id>:role/dbspend360-cost-explorer-read';
  ```

Grant the job's run-as identity `USE` (i.e. `ACCESS`) on the credential:

```sql
GRANT ACCESS ON SERVICE CREDENTIAL `dbspend-read-ce` TO `<job-run-as-principal>`;
```

> The credential name is passed as the default argument
> `service_credential_name='dbspend-read-ce'`. If you must use a different
> name, override it where `AWSCostClient` is constructed in the notebook.

---

## 3. Required cluster and pool tags

The ETL joins AWS line items back to Databricks resources using two tags. Only
the **EC2 family** (`Amazon Elastic Compute Cloud - Compute` and `EC2 - Other`,
which folds in EBS) carries these tags and is treated as cluster/pool
attributable.

| Tag | Applied to | Value | Used by |
| --- | --- | --- | --- |
| `ClusterId` | Every interactive and job cluster's underlying EC2 instances | the Databricks `cluster_id` | cluster cost path (`dbspend360_cloud_cost_explorer`) |
| `DatabricksInstancePoolId` | Pool (idle/warm) EC2 capacity | the Databricks `instance_pool_id` | pool cost path (`dbspend360_pool_cloud_cost_explorer`) |

The pool path keeps only the slice of `DatabricksInstancePoolId`-tagged cost
that has **no** `ClusterId` (idle/warm capacity), so pool and cluster cloud cost
stay disjoint and are never double-counted.

> These are standard Databricks-propagated tags. Ensure tag propagation is
> enabled so the EC2 instances inherit them, and that Cost Explorer **cost
> allocation tags** for `ClusterId` and `DatabricksInstancePoolId` are
> **activated** in Billing → Cost allocation tags (an inactive tag will not
> appear in `GetCostAndUsage` group-by results).

---

## 4. Databricks configuration

Set the platform in the environment config so the dashboard reads from the AWS
tables:

```ini
# config/app.<env>.config
[cloud]
platform = AWS
```

---

## 5. Output tables

The ETL writes two Unity Catalog tables under `<catalog>.<schema>`:

| Table | Contents |
| --- | --- |
| `dbspend360_cloud_cost_explorer` | per-cluster, per-day tagged EC2 + EBS cost (`cloud_cost`); segmented compute/storage/network/other columns are intentionally `NULL` on AWS |
| `dbspend360_pool_cloud_cost_explorer` | per-pool, per-day idle/warm EC2 cost, `ClusterId`-netted |

---

## 6. Verifying setup

1. **Confirm Cost Explorer access** from a context that resolves the same role
   (or locally with the role's credentials). The ETL uses `AmortizedCost`:

   ```bash
   aws ce get-cost-and-usage \
     --time-period Start=$(date -u -d '7 days ago' +%F),End=$(date -u +%F) \
     --granularity DAILY \
     --metrics AmortizedCost \
     --region us-east-1
   ```

   A `200` response with `ResultsByTime` confirms `ce:GetCostAndUsage` access.

2. **Confirm the tags are visible to Cost Explorer**:

   ```bash
   aws ce get-tags \
     --time-period Start=$(date -u -d '7 days ago' +%F),End=$(date -u +%F) \
     --tag-key ClusterId \
     --region us-east-1
   ```

   (Requires the optional `ce:GetTags` permission from §2.1.) A non-empty
   `Tags` list confirms the cost allocation tag is activated and populated.

3. **Run the ETL end-to-end**: execute `aws_cloud_cost_explorer_app` and confirm
   rows land in `<catalog>.<schema>.dbspend360_cloud_cost_explorer` (and, for
   pooled workloads, `dbspend360_pool_cloud_cost_explorer`). Check the
   `dbspend360_audit_log` for a `SUCCESS` entry; the post-write monitor logs an
   alarm to `dbspend360_error_log` if window cost collapses to ~0 (suspected
   tagging lapse) or an expected EC2 service is missing from the response.

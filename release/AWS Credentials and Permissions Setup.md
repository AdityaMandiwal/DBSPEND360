# AWS Credentials and Permissions Setup — DBSPEND360

This document is the AWS counterpart to `Azure Credentials and Permissions Setup.docx`.
It describes the IAM policies, credentials, and Databricks workspace configuration
required to run the AWS cloud cost explorer ETL
(`jobs/notebooks/aws_cloud_cost_explorer_app.ipynb`) and to power the DBSPEND360
dashboard when `[cloud] platform = AWS` is set in `config/app.<env>.config`.

> NOTE: Replace this Markdown with a `.docx` once the doc team has formatted it.
> The Markdown source is checked in so the IAM policy JSON snippet stays
> reviewable in pull requests.

## 1. Required AWS APIs

The AWS notebook uses two services to assemble per-cluster cost:

| API | Purpose |
| --- | --- |
| AWS Cost Explorer (`ce`) | Day-level service-grouped cost queries with cluster-tag filters |
| AWS Cost and Usage Reports (`cur`) | Detailed line-item back-fill for unclassified spend |

## 2. IAM Policy

Attach the following inline policy to the IAM user, role, or instance profile
that the notebook authenticates as. Scope is read-only.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DBSpend360CostExplorerRead",
      "Effect": "Allow",
      "Action": [
        "ce:GetCostAndUsage",
        "ce:GetCostAndUsageWithResources",
        "ce:GetDimensionValues",
        "ce:GetTags",
        "ce:DescribeCostCategoryDefinition",
        "ce:ListCostCategoryDefinitions"
      ],
      "Resource": "*"
    },
    {
      "Sid": "DBSpend360CURRead",
      "Effect": "Allow",
      "Action": [
        "cur:DescribeReportDefinitions",
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::<your-cur-bucket>",
        "arn:aws:s3:::<your-cur-bucket>/*"
      ]
    }
  ]
}
```

## 3. Cluster Tags

The notebook joins AWS line items back to Databricks clusters using a tag.
Ensure every Databricks cluster (interactive and job) carries a tag
`ClusterId` (or the value matching `_AZURE_TAG_VALUE_CANDIDATES` in
`utils_common.ipynb` for symmetry across clouds) whose value is the
Databricks `cluster_id`.

## 4. Credentials Delivery to Databricks

Provide the credentials to the notebook job using one of:

1. Databricks Secrets (`databricks secrets put-secret`) — recommended.
2. Instance profile attached to the cluster running the job.
3. Workspace-level service principal with the policy above attached.

## 5. Verifying Setup

After applying the policy, run:

```bash
aws ce get-cost-and-usage \
  --time-period Start=$(date -u -d '7 days ago' +%F),End=$(date -u +%F) \
  --granularity DAILY \
  --metrics UnblendedCost
```

A 200 response confirms Cost Explorer access. Then run the
`aws_cloud_cost_explorer_app` notebook end-to-end and confirm rows land in
`<catalog>.<schema>.dbspend360_cloud_cost_explorer`.

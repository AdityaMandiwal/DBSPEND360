# GCP Credentials and Permissions Setup — DBSPEND360 (Stub)

This is a placeholder companion to `AWS Credentials and Permissions Setup.md`
and `Azure Credentials and Permissions Setup.md`. GCP support is declared
in `server/config/config_loader.py` and `config/app.dev.config`
(`[cloud] platform = GCP`), but the GCP cloud cost explorer ETL is not yet
implemented. See `jobs/notebooks/gcp_cloud_cost_explorer_app.ipynb` for the
notebook stub.

When the implementation lands, this document should describe:

1. Required GCP APIs (Cloud Billing API, BigQuery for billing export tables).
2. The IAM role / role binding required on the Databricks workspace service
   account, e.g. `roles/billing.viewer` and `roles/bigquery.dataViewer`
   on the project hosting the billing export.
3. How to deliver the GCP service-account JSON key to Databricks Secrets.
4. Cluster tag conventions to join GCE line items back to Databricks
   `cluster_id` values.
5. Verification steps (sample `gcloud billing accounts list` and BigQuery
   query against the billing export).

> Replace this stub with a full Markdown guide once the GCP implementation is
> shipped, mirroring `AWS Credentials and Permissions Setup.md`.

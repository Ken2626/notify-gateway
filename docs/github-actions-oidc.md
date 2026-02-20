# GitHub Actions OIDC Setup

This workflow uses Workload Identity Federation (OIDC), no long-lived GCP JSON key.

For full command-by-command bootstrap, see `docs/one-time-bootstrap.md`.

## Required GitHub repository variables

- `GCP_PROJECT_ID`

## Required GitHub repository secrets

- `GCP_WORKLOAD_IDENTITY_PROVIDER`
  - Format example: `projects/123456789/locations/global/workloadIdentityPools/github/providers/github-oidc`
- `GCP_SERVICE_ACCOUNT_EMAIL`
  - Service account used by GitHub Actions deploy job

## Minimum IAM permissions

Grant the service account these roles in the target project:

- `roles/run.admin`
- `roles/iam.serviceAccountUser`
- `roles/artifactregistry.writer`

Grant the workload identity principal permission to impersonate the service account:

- `roles/iam.workloadIdentityUser`

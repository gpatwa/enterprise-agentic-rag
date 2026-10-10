# OpenSearch Infrastructure Contract

This module is intentionally provider-neutral. It records the inputs required
by the API and produces an endpoint/secret contract; it does not create Azure
or AWS resources. A cloud-specific module can implement these variables after
residency, backup, and managed-service selection are approved.

`terraform fmt -check` and `terraform validate` are the local gates when the
Terraform CLI is installed.

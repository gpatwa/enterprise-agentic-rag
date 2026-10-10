# OS-053 Search Hosting Selection

Status: Accepted interface decision, hosting deployment deferred.

The application owns the provider-neutral search contract and can connect to
either a managed OpenSearch-compatible endpoint or an operated OpenSearch
cluster. The production choice must be made per customer residency and
networking requirements. Azure deployment is explicitly out of scope for this
milestone.

The required capability contract is TLS, private networking, IAM or API-key
rotation, snapshot/restore, audit integration, vector support, alias swaps,
and operator-visible health. A managed service reduces patching and backup
work; an operated cluster gives more control over plugins, placement, and
residency but increases operational ownership. The decision record for a
customer must attach measured latency, storage, backup, and egress costs.

Until that evidence exists, local Compose is the validation target and the
Helm/Terraform artifacts expose configuration without provisioning a cluster.

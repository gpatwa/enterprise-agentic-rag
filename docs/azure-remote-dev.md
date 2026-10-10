# Azure Remote Docker Development

This is an isolated, automated development environment for the monorepo. It
does not use the staging AKS Terraform state and does not deploy application
images to Azure Container Registry. Terraform creates one Ubuntu VM, a small
private network, a static public IP, and an SSH-only network rule. Cloud-init
installs Docker Engine and Compose. The lifecycle script syncs the current
checkout and starts the existing Compose profiles.

## Prerequisites

Install and authenticate the local control tools once:

```bash
brew install azure-cli terraform
az login
```

Docker does not need to run on the laptop. The remote VM is the Docker host.
The script generates an SSH key under `.local/azure-dev/`, detects the current
public IP for the SSH rule, and stores Terraform state under the same ignored
directory.

## One-command lifecycle

```bash
# Provision/update, sync this checkout, and start the products.
make azure-dev-up

# Open the same local URLs through SSH tunnels.
make azure-dev-tunnel

# After local edits, sync and rebuild/restart the remote containers.
make azure-dev-sync
make azure-dev-start

# Preserve disks and Docker volumes while stopping compute.
make azure-dev-stop

# Inspect or connect.
make azure-dev-status
make azure-dev-ssh

# Permanently remove the remote-dev resource group and all its data.
make azure-dev-destroy
```

The tunnel also includes the operations surfaces. It prints the actual local
ports and chooses a free port when the standard one is already occupied:

| Surface | Remote port | Preferred local port |
|---|---:|---:|
| Grafana operations | 3000 | 3000 |
| Prometheus | 9090 | 9090 |
| OpenSearch Dashboards | 5601 | 5601 |

Grafana uses the local development credentials `admin` / `admin` unless
`GRAFANA_ADMIN_PASSWORD` is supplied to the remote Compose environment. These
UIs are reachable only through the SSH tunnel.

`azure-dev-destroy` requires `AZURE_DEV_CONFIRM_DESTROY=1` or an explicit
`--yes` argument so an accidental shell command cannot delete the environment.

## Defaults and overrides

The defaults are intentionally usable without a `.tfvars` file:

| Setting | Default |
|---|---|
| Resource name | `compass-dev` |
| Region | `westus2` |
| VM | `Standard_D8as_v5` |
| OS disk | 256 GB Standard SSD |
| SSH source | Detected public IPv4 `/32` |
| Auto-shutdown | 23:00 UTC |

Override through environment variables, for example:

```bash
AZURE_DEV_LOCATION=eastus \
AZURE_DEV_VM_SIZE=Standard_D4as_v5 \
AZURE_DEV_AUTO_SHUTDOWN_TIME_UTC=0200 \
make azure-dev-up
```

The optional `AZURE_DEV_SSH_SOURCE_CIDR` is useful when the detected public IP
is not the address that reaches Azure, such as when using a corporate VPN.
The tunnel command automatically moves a local port up by 10,000 when the
standard port is already occupied. Use `AZURE_DEV_TUNNEL_PORT_OFFSET` to apply
a predictable offset to every tunnel.

## Security and operational boundaries

- Only TCP/22 from the detected source CIDR is exposed publicly.
- App, database, cache, vector, graph, and OpenSearch ports are reachable only
  through SSH tunnels.
- Password SSH login is disabled; the generated RSA 4096 key is the only login
  credential. Azure's current VM provider path requires RSA keys here.
- The remote `.env.azure-dev` contains local demo defaults and is generated on
  the VM. The local `.env` and other secret files are excluded from rsync.
- The default auto-shutdown schedule reduces idle compute charges. `stop`
  explicitly deallocates the VM while preserving its disk and Docker volumes.
- This environment is for development only. It has no TLS, production backup,
  HA, public ingress, managed identity wiring, or staging approval semantics.

The local Docker services remain PostgreSQL, Redis, Qdrant, Neo4j, OpenSearch,
and MinIO. The opt-in observability profile adds Prometheus, Grafana, cAdvisor,
PostgreSQL/Redis/OpenSearch exporters, and OpenSearch Dashboards. Azure-specific
managed-service validation belongs in the separate staging workflow.

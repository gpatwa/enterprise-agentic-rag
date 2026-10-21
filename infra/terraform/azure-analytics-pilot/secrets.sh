#!/usr/bin/env bash
# Prints a secrets.auto.tfvars with fresh random values. Keep the file out of git (it is ignored); store it in your password manager.
set -euo pipefail
cat <<TFVARS
postgres_admin_password    = "$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-28)Aa1!"
postgres_readonly_password = "$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-28)"
run_id_key                 = "$(openssl rand -hex 32)"
api_key                    = "$(openssl rand -hex 24)"
TFVARS

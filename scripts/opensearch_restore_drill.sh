#!/usr/bin/env bash
set -euo pipefail

: "${OPENSEARCH_URL:=http://127.0.0.1:9200}"
: "${OPENSEARCH_INDEX_ALIAS:=compass-support-search}"

curl --fail --silent "${OPENSEARCH_URL}/_cluster/health" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(json.dumps({"status":data.get("status"),"number_of_nodes":data.get("number_of_nodes")}))'
curl --fail --silent "${OPENSEARCH_URL}/${OPENSEARCH_INDEX_ALIAS}/_count" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("count", 0))'
echo "Restore repository and snapshot verification require the selected production provider."

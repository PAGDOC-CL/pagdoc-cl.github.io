#!/usr/bin/env bash
set -euo pipefail
task="${1:-check}"
local_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
runtime_env="${PAGDOC_RUNTIME_ENV:-$HOME/.config/pagdoc-private/runtime.env}"
compose=(sudo docker compose --project-name pagdoc-private --env-file "$runtime_env" -f "$local_dir/compose.local.yml")
case "$task" in
  start)
    python3 "$local_dir/generate_config.py" "$runtime_env"
    sudo service docker start
    "${compose[@]}" up --build --detach --wait --wait-timeout 240
    echo 'Private pilot available at https://localhost:8443/app after trusting its local certificate.'
    ;;
  stop) "${compose[@]}" stop ;;
  status) "${compose[@]}" ps ;;
  provision) "${compose[@]}" exec -e PAGDOC_ALLOW_BETA_PROVISIONING=YES api python provision_beta.py ;;
  certificate) "${compose[@]}" exec -T proxy cat /data/caddy/pki/authorities/local/root.crt ;;
  check)
    command -v python3 >/dev/null
    sudo docker info >/dev/null
    sudo docker compose version
    echo 'Prerequisites available. Documents and SharePoint are not enabled by this command.'
    ;;
  *) echo 'Use start, stop, status, provision, certificate or check.' >&2; exit 2 ;;
esac

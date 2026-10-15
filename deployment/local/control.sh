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
    echo 'Servidor privado disponible en https://localhost:8443/app tras confiar en su certificado local. Revisa los controles pendientes antes de incorporar documentos.'
    ;;
  stop) "${compose[@]}" --profile files stop ;;
  status) "${compose[@]}" --profile files ps ;;
  files-start)
    python3 -c 'from pathlib import Path; values={line.split(":")[0]:int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable:")}; available=values.get("MemAvailable",0); assert available >= 4*1024*1024, "Se requieren al menos 4 GiB de RAM disponible en Ubuntu para iniciar el antivirus junto a PAGDOC; revisa free -h antes de continuar."'
    "${compose[@]}" --profile files up --detach --wait --wait-timeout 600 antimalware
    echo 'Antimalware iniciado. Ejecuta files-check; las cargas HTTP siguen deshabilitadas.'
    ;;
  files-check) "${compose[@]}" exec -T api python private_files.py ;;
  provision) "${compose[@]}" exec -e PAGDOC_ALLOW_ADMIN_PROVISIONING=YES api python provision_admin.py ;;
  provision-beta) "${compose[@]}" exec -e PAGDOC_ALLOW_BETA_PROVISIONING=YES api python provision_beta.py ;;
  certificate) "${compose[@]}" exec -T proxy cat /data/caddy/pki/authorities/local/root.crt ;;
  check)
    command -v python3 >/dev/null
    sudo docker info >/dev/null
    sudo docker compose version
    echo 'Prerequisites available. Documents and SharePoint are not enabled by this command.'
    ;;
  *) echo 'Use start, stop, status, files-start, files-check, provision, provision-beta, certificate or check.' >&2; exit 2 ;;
esac

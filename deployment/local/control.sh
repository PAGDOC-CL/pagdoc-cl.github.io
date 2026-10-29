#!/usr/bin/env bash
set -euo pipefail
task="${1:-check}"
local_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
runtime_env="${PAGDOC_RUNTIME_ENV:-$HOME/.config/pagdoc-private/runtime.env}"
compose=(sudo docker compose --project-name pagdoc-private --env-file "$runtime_env" -f "$local_dir/compose.local.yml")
remote_env="${PAGDOC_REMOTE_ENV:-$(dirname -- "$runtime_env")/remote.env}"
if [[ -f "$remote_env" && "$task" != remote-disable ]]; then
  PAGDOC_NETBIRD_IP="$(python3 "$local_dir/remote_access.py" check-config)"
  export PAGDOC_NETBIRD_IP
  compose+=(--env-file "$remote_env" -f "$local_dir/compose.remote.yml")
fi
case "$task" in
  start)
    python3 "$local_dir/generate_config.py" "$runtime_env"
    if [[ -f "$remote_env" ]]; then python3 "$local_dir/remote_access.py" check-live; fi
    sudo service docker start
    profiles=()
    wait_seconds=240
    if python3 -c 'from pathlib import Path; import sys; raise SystemExit(0 if "PAGDOC_BINARY_HTTP_ENABLED=1" in Path(sys.argv[1]).read_text().splitlines() else 1)' "$runtime_env"; then
      profiles=(--profile files)
      wait_seconds=600
    fi
    if python3 -c 'from pathlib import Path; import sys; raise SystemExit(0 if "PAGDOC_EMAIL_DELIVERY_ENABLED=1" in Path(sys.argv[1]).read_text().splitlines() else 1)' "$runtime_env"; then
      profiles+=(--profile notifications)
    fi
    "${compose[@]}" "${profiles[@]}" up --build --detach --wait --wait-timeout "$wait_seconds"
    echo 'Servidor privado disponible en https://localhost:8443/app tras confiar en su certificado local. Revisa los controles pendientes antes de incorporar documentos.'
    ;;
  remote-install) bash "$local_dir/install-netbird.sh" ;;
  remote-connect)
    command -v netbird >/dev/null || { echo 'Ejecuta primero control.sh remote-install.' >&2; exit 1; }
    sudo netbird service start
    sudo netbird up --hostname pagdoc-server --disable-dns --disable-client-routes --disable-server-routes --disable-ipv6 --allow-server-ssh=false
    ;;
  remote-enable)
    python3 "$local_dir/remote_access.py" enable
    bash "$local_dir/control.sh" start
    python3 "$local_dir/remote_access.py" verify
    ;;
  remote-disable)
    python3 "$local_dir/remote_access.py" disable
    bash "$local_dir/control.sh" start
    ;;
  remote-status) python3 "$local_dir/remote_access.py" status ;;
  remote-check) python3 "$local_dir/remote_access.py" verify ;;
  stop) "${compose[@]}" --profile files --profile notifications stop ;;
  status) "${compose[@]}" --profile files --profile notifications ps ;;
  files-start)
    python3 -c 'from pathlib import Path; values={line.split(":")[0]:int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable:")}; available=values.get("MemAvailable",0); assert available >= 4*1024*1024, "Se requieren al menos 4 GiB de RAM disponible en Ubuntu para iniciar el antivirus junto a PAGDOC; revisa free -h antes de continuar."'
    "${compose[@]}" --profile files up --detach --wait --wait-timeout 600 antimalware
    echo 'Antimalware iniciado. Ejecuta files-check; las cargas HTTP siguen deshabilitadas.'
    ;;
  files-check) "${compose[@]}" exec -T api python private_files.py ;;
  files-enable)
    "${compose[@]}" exec -T api python private_files.py
    python3 "$local_dir/enable_files.py" "$runtime_env"
    "${compose[@]}" --profile files up --build --detach --wait --wait-timeout 240 api proxy analysis
    echo 'Archivos privados habilitados. Cada carga exige sesión, permisos, CSRF y análisis antimalware.'
    ;;
  provision) "${compose[@]}" exec -e PAGDOC_ALLOW_ADMIN_PROVISIONING=YES api python provision_admin.py ;;
  configure-email) python3 "$local_dir/configure_email.py" ;;
  configure-email-oauth) python3 "$local_dir/configure_email_oauth.py" "${@:2}" ;;
  email-oauth-login) "${compose[@]}" exec -T api python smtp_oauth.py "${@:2}" ;;
  provision-members) "${compose[@]}" exec -e PAGDOC_ALLOW_MEMBER_PROVISIONING=YES api python provision_members.py "${@:2}" ;;
  provision-beta) "${compose[@]}" exec -e PAGDOC_ALLOW_BETA_PROVISIONING=YES api python provision_beta.py ;;
  certificate) "${compose[@]}" exec -T proxy cat /data/caddy/pki/authorities/local/root.crt ;;
  check)
    command -v python3 >/dev/null
    sudo docker info >/dev/null
    sudo docker compose version
    echo 'Prerequisites available. Documents and SharePoint are not enabled by this command.'
    ;;
  *) echo 'Use start, stop, status, files-start, files-check, files-enable, provision, provision-members, configure-email, configure-email-oauth, provision-beta, certificate, remote-install, remote-connect, remote-enable, remote-disable, remote-status, remote-check or check.' >&2; exit 2 ;;
esac

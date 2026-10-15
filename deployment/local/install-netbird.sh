#!/usr/bin/env bash
set -euo pipefail
if command -v netbird >/dev/null; then
  echo 'NetBird ya está instalado. Continúa con remote-connect.'
  exit 0
fi
if [[ ! -d /run/systemd/system ]]; then
  echo 'Ubuntu necesita systemd activo para mantener NetBird conectado. Comprueba la configuración de WSL antes de instalar.' >&2
  exit 1
fi
source /etc/os-release
if [[ "$ID" != ubuntu && "$ID" != debian ]]; then
  echo 'Este instalador solo prepara Ubuntu/Debian.' >&2
  exit 1
fi
sudo apt-get update
sudo apt-get install --yes ca-certificates curl gnupg
netbird_key="$(mktemp)"
trap 'rm -f "$netbird_key"' EXIT
curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location https://pkgs.netbird.io/debian/public.key --output "$netbird_key"
sudo gpg --batch --yes --dearmor --output /usr/share/keyrings/netbird-archive-keyring.gpg "$netbird_key"
echo 'deb [signed-by=/usr/share/keyrings/netbird-archive-keyring.gpg] https://pkgs.netbird.io/debian stable main' | sudo tee /etc/apt/sources.list.d/netbird.list >/dev/null
sudo apt-get update
sudo apt-get install --yes netbird
sudo systemctl enable --now netbird
echo 'Cliente instalado desde el repositorio oficial. No se ha contratado ningún plan ni registrado una cuenta.'
echo 'Continúa con control.sh remote-connect e inicia sesión en una cuenta NetBird Free.'

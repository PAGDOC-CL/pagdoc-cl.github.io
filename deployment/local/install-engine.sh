#!/usr/bin/env bash
set -euo pipefail
if [[ "$(id -u)" == 0 ]]; then
  echo 'Run as your Ubuntu user, not root. sudo is requested only for system installation.' >&2
  exit 1
fi
source /etc/os-release
[[ "$ID" == ubuntu ]] || { echo 'This installer requires Ubuntu.' >&2; exit 1; }
if ! command -v docker >/dev/null; then
  # Do not remove or replace a conflicting container runtime automatically.
  for package in docker.io docker-compose docker-compose-v2 podman-docker containerd runc; do
    package_status="$(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || true)"
    if [[ "$package_status" == 'install ok installed' ]]; then
      echo 'Existing container packages require manual compatibility review.' >&2
      exit 1
    fi
  done
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl
  sudo install -m 0755 -d /etc/apt/keyrings
  sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  sudo chmod a+r /etc/apt/keyrings/docker.asc
  printf 'Types: deb\nURIs: https://download.docker.com/linux/ubuntu\nSuites: %s\nComponents: stable\nArchitectures: %s\nSigned-By: /etc/apt/keyrings/docker.asc\n' "${UBUNTU_CODENAME:-$VERSION_CODENAME}" "$(dpkg --print-architecture)" | sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null
  sudo apt-get update
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
sudo service docker start
sudo docker info >/dev/null
sudo docker compose version
echo 'Docker Engine ready. No Docker group membership or public firewall rule was added.'

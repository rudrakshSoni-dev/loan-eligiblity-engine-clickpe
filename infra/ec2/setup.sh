#!/usr/bin/env bash
set -euo pipefail

COMPOSE_VERSION="v2.29.7"
SWAP_FILE="/swapfile"
SWAP_SIZE_MB=2048
RDS_CA_URL="https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem"
RDS_CA_PATH="/opt/clickpe/global-bundle.pem"

add_swap() {
  if swapon --show | grep -q "$SWAP_FILE"; then
    return
  fi
  sudo dd if=/dev/zero of="$SWAP_FILE" bs=1M count="$SWAP_SIZE_MB" status=none
  sudo chmod 600 "$SWAP_FILE"
  sudo mkswap "$SWAP_FILE" >/dev/null
  sudo swapon "$SWAP_FILE"
  echo "$SWAP_FILE none swap sw 0 0" | sudo tee -a /etc/fstab >/dev/null
}

install_docker() {
  sudo dnf install -y docker postgresql16 >/dev/null
  sudo systemctl enable --now docker
  sudo usermod -aG docker ssm-user || true
  sudo mkdir -p /usr/local/lib/docker/cli-plugins
  sudo curl -fsSL \
    "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-aarch64" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
}

fetch_rds_ca() {
  sudo mkdir -p "$(dirname "$RDS_CA_PATH")"
  sudo curl -fsSL "$RDS_CA_URL" -o "$RDS_CA_PATH"
}

add_swap
install_docker
fetch_rds_ca
docker --version
sudo docker compose version
swapon --show

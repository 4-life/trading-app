#!/usr/bin/env bash
# One-time VPS bootstrap (docs/deployment.md#vps-bootstrap-one-time-run-manually). Re-runnable on a
# brand-new or an existing VPS - every step checks before it changes anything.
#
#   sudo ./deploy.sh <domain> <letsencrypt-email>
#
# Ubuntu/Debian, run as root. Installs Docker + Compose, creates a `deploy`
# user in the `docker` group (no sudo), opens only SSH/HTTP/HTTPS,
# puts the dashboard behind Nginx + Let's Encrypt (auto-renewed), and prints
# the values to store as GitHub Actions secrets. The app itself is deployed
# by CI (.github/workflows/deploy.yml), not by this script.
set -euo pipefail

DOMAIN="${1:?usage: sudo ./deploy.sh <domain> <letsencrypt-email>}"
EMAIL="${2:?usage: sudo ./deploy.sh <domain> <letsencrypt-email>}"
DEPLOY_USER="deploy"
APP_DIR="/home/deploy/trading-app" # the workflow's default APP_DIR
DASHBOARD_PORT="3000"

if [ "$(id -u)" -ne 0 ]; then
  echo "run as root (sudo)" >&2
  exit 1
fi

step() { echo; echo "=== $* ==="; }

step "packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q ca-certificates curl ufw nginx certbot python3-certbot-nginx

step "docker + compose"
if ! command -v docker >/dev/null 2>&1; then
  # Docker's official install script (adds its apt repo, installs the engine
  # and the compose plugin).
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker
docker compose version

step "deploy user"
if ! id "$DEPLOY_USER" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "$DEPLOY_USER"
fi
# Docker only, through the docker group - no sudo (the CI deploy runs plain
# `docker`). An earlier version's sudoers rule is removed.
usermod -aG docker "$DEPLOY_USER"
rm -f /etc/sudoers.d/"$DEPLOY_USER"

DEPLOY_HOME="$(getent passwd "$DEPLOY_USER" | cut -d: -f6)"
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$DEPLOY_HOME/.ssh"
CI_KEY="$DEPLOY_HOME/.ssh/ci_deploy"
if [ ! -f "$CI_KEY" ]; then
  sudo -u "$DEPLOY_USER" ssh-keygen -t ed25519 -N "" -C "github-actions-deploy" -f "$CI_KEY"
fi
AUTH_KEYS="$DEPLOY_HOME/.ssh/authorized_keys"
touch "$AUTH_KEYS"
grep -qxF "$(cat "$CI_KEY.pub")" "$AUTH_KEYS" || cat "$CI_KEY.pub" >> "$AUTH_KEYS"
chown "$DEPLOY_USER:$DEPLOY_USER" "$AUTH_KEYS"
chmod 600 "$AUTH_KEYS"

install -d -m 750 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$APP_DIR" "$APP_DIR/docker/production"

step "firewall"
ufw allow OpenSSH
ufw allow "Nginx Full" # 80 (Let's Encrypt challenge + redirect) and 443
ufw --force enable
ufw status

step "nginx"
cat > /etc/nginx/sites-available/trading-app <<NGINX
server {
    listen 80;
    server_name $DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:$DASHBOARD_PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        # The dashboard forwards this to the API for its login rate limit.
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        # HTTPS only from now on (certbot adds the 443 block to this server).
        add_header Strict-Transport-Security "max-age=31536000" always;
    }
}
NGINX
ln -sf /etc/nginx/sites-available/trading-app /etc/nginx/sites-enabled/trading-app
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

step "TLS certificate"
# Adds the 443 server block and the http -> https redirect to the site above.
certbot --nginx -d "$DOMAIN" -m "$EMAIL" --agree-tos --non-interactive --redirect
# The certbot package installs a systemd timer that renews automatically.
systemctl enable --now certbot.timer
certbot renew --dry-run

SSH_PORT="$(sshd -T 2>/dev/null | awk '/^port /{print $2; exit}')"
HOST_IP="$(curl -fsS https://api.ipify.org || hostname -I | awk '{print $1}')"

step "GitHub Actions secrets"
cat <<INFO
Add these in GitHub: Settings -> Secrets and variables -> Actions -> Secrets.

VPS_HOST      = $HOST_IP
VPS_PORT      = ${SSH_PORT:-22}
VPS_USER      = $DEPLOY_USER
VPS_SSH_KEY   = (the private key below, including the BEGIN/END lines)

$(cat "$CI_KEY")

Also set the app secrets (see docs/deployment.md#cicd-github-actions):
POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, APP_PASSWORD, SETTINGS_ENCRYPTION_KEY

Dashboard: https://$DOMAIN  (live after the first successful CI deploy)
INFO

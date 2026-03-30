#!/bin/bash
# OpenRAROC deployment script for Hetzner / any Ubuntu/Debian server
# Run as root: curl -sL https://raw.githubusercontent.com/cpoder/raroc-engine/main/deploy/setup.sh | bash
#
# Prerequisites: a server with Docker installed and ports 80/443 open
# DNS: point openraroc.com and api.openraroc.com to your server IP

set -e

echo "=== OpenRAROC Deployment ==="

# 1. Install Docker if not present
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
fi

if ! command -v docker compose &> /dev/null; then
    echo "Installing Docker Compose..."
    apt-get install -y docker-compose-plugin
fi

# 2. Install Caddy for reverse proxy + auto-HTTPS
if ! command -v caddy &> /dev/null; then
    echo "Installing Caddy..."
    apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
    apt-get update
    apt-get install -y caddy
fi

# 3. Clone repos
DEPLOY_DIR="/opt/openraroc"
mkdir -p $DEPLOY_DIR
cd $DEPLOY_DIR

if [ ! -d "raroc-engine" ]; then
    git clone https://github.com/cpoder/raroc-engine.git
fi

# 4. Premium data (clone from private repo if you have access)
if [ ! -f "raroc-engine/premium_banks.json" ]; then
    echo ""
    echo "NOTE: Premium bank data not found."
    echo "To add it, either:"
    echo "  1. Copy premium_banks.json to $DEPLOY_DIR/raroc-engine/"
    echo "  2. Or clone: git clone git@github.com:cpoder/raroc-premium-data.git"
    echo "     Then: cp raroc-premium-data/premium_banks.json raroc-engine/"
    echo ""
fi

# 5. Generate admin key
ADMIN_KEY=$(openssl rand -hex 16)
echo "RAROC_ADMIN_KEY=$ADMIN_KEY" > raroc-engine/.env
echo "Admin key saved to .env: $ADMIN_KEY"
echo "Keep this safe -- you'll need it to create API keys for customers."

# 6. Start services
cd raroc-engine
docker compose -f deploy/docker-compose.yml up -d --build

# 7. Configure Caddy
cp deploy/caddy/Caddyfile /etc/caddy/Caddyfile
systemctl reload caddy

echo ""
echo "=== Deployment complete ==="
echo ""
echo "Web app:     https://openraroc.com"
echo "Premium API: https://api.openraroc.com"
echo "API status:  https://api.openraroc.com/v1/status"
echo ""
echo "To create an API key for a customer:"
echo "  curl -X POST https://api.openraroc.com/admin/keys"
echo "       -H 'Authorization: Bearer $ADMIN_KEY'"
echo "       -d 'organization=Acme Corp&email=cfo@acme.com&expires_at=2027-03-30'"
echo ""

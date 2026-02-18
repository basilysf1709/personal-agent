#!/bin/bash
set -euo pipefail

SERVER="root@142.93.124.186"
REMOTE_DIR="/root/personal-agent"
REPO="git@github.com:basilysf1709/personal-agent.git"

# Ensure local .env exists
if [ ! -f .env ]; then
    echo "ERROR: No local .env file found. Create one from .env.example"
    exit 1
fi

echo "==> Deploying to ${SERVER}..."

# Ensure Docker and git are installed on the server
ssh "$SERVER" 'command -v docker >/dev/null 2>&1 || {
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
}'

ssh "$SERVER" 'docker compose version >/dev/null 2>&1 || {
    echo "Installing Docker Compose plugin..."
    apt-get update && apt-get install -y docker-compose-plugin
}'

ssh "$SERVER" 'command -v git >/dev/null 2>&1 || {
    echo "Installing git..."
    apt-get update && apt-get install -y git
}'

# Clone or pull latest
echo "==> Pulling latest code..."
ssh "$SERVER" "
    if [ -d $REMOTE_DIR/.git ]; then
        cd $REMOTE_DIR && git pull
    else
        git clone $REPO $REMOTE_DIR
    fi
"

# Push local .env to server
echo "==> Syncing .env..."
scp .env "$SERVER:$REMOTE_DIR/.env"

# Build and start containers
echo "==> Building and starting containers..."
ssh "$SERVER" "cd $REMOTE_DIR && docker compose up -d --build"

echo "==> Deployment complete!"
echo ""
echo "To scan the QR code:"
echo "  ssh $SERVER 'docker logs -f whatsapp-bridge'"
echo ""
echo "To check status:"
echo "  ssh $SERVER 'docker compose -f $REMOTE_DIR/docker-compose.yml ps'"

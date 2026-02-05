#!/bin/bash
# Setup script to run Docker natively in WSL2 (not Docker Desktop)
# This allows direct access to CIFS mounts inside WSL2

set -e

echo "Installing Docker in WSL2 (native, not Docker Desktop)..."

# Install Docker
sudo apt-get update
sudo apt-get install -y apt-transport-https ca-certificates curl software-properties-common
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Add user to docker group
sudo usermod -aG docker $USER

# Start Docker service
sudo service docker start

echo ""
echo "Docker installed in WSL2!"
echo "Next steps:"
echo "1. Logout and login to WSL2 for group membership to take effect"
echo "2. Verify CIFS mount: ls -la /mnt/niu-recordings/TV"
echo "3. Build: docker compose -f docker-compose.local.yml build"
echo "4. Run: docker compose -f docker-compose.local.yml --env-file .env.local up -d"
echo ""
echo "Note: You'll need to start Docker each time WSL2 restarts:"
echo "  sudo service docker start"

#!/bin/bash
# ─── Oracle Cloud VM Setup & Deploy Script ───
# Run this on your Oracle Cloud VM after SSH-ing in
# Usage: bash deploy.sh

set -e

echo "🚀 Clinic Bot — Oracle Cloud Deployment"
echo "========================================="

# Step 1: Install Docker
echo ""
echo "📦 Installing Docker..."
sudo apt-get update -y
sudo apt-get install -y apt-transport-https ca-certificates curl gnupg lsb-release
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
sudo systemctl enable docker
sudo systemctl start docker

# Install Docker Compose
echo "📦 Installing Docker Compose..."
sudo apt-get install -y docker-compose-plugin

echo "✅ Docker installed!"

# Step 2: Clone or copy project
echo ""
echo "📁 Setting up project directory..."
mkdir -p ~/clinic_bot
cd ~/clinic_bot

echo ""
echo "⚠️  IMPORTANT: Copy your project files to ~/clinic_bot/"
echo "    You can use: scp -r -i your-key.key clinic_bot/* ubuntu@YOUR_VM_IP:~/clinic_bot/"
echo ""
echo "    Then run: cd ~/clinic_bot && docker compose -f docker-compose.prod.yml up -d --build"
echo ""

# Step 3: Open firewall ports
echo "🔓 Opening firewall ports (80, 443, 8000)..."
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT
sudo netfilter-persistent save 2>/dev/null || true

echo "✅ Firewall configured!"
echo ""
echo "========================================="
echo "📋 Next steps:"
echo "1. Copy project files to this VM"
echo "2. Create .env file with production values"
echo "3. Run: docker compose -f docker-compose.prod.yml up -d --build"
echo "4. Update MSG91 webhook URL to: http://YOUR_VM_IP/api/webhook/whatsapp/"
echo "5. Also open port 80 in Oracle Cloud Console:"
echo "   → Networking → Virtual Cloud Networks → your VCN → Security Lists → Add Ingress Rule"
echo "   → Source: 0.0.0.0/0, Protocol: TCP, Port: 80"
echo "========================================="

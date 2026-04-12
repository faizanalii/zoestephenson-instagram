#!/bin/bash
# =============================================================================
# Redis Server Setup Script
# Run on a fresh Ubuntu/Debian server to prepare for Redis deployment
# Usage: sudo bash setup-server.sh
# =============================================================================

set -e

echo "=========================================="
echo "  Redis Server Setup Script"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "❌ Please run as root (sudo bash setup-server.sh)"
    exit 1
fi

# Get the non-root user who called sudo
REAL_USER=${SUDO_USER:-$USER}

echo "→ Updating system packages..."
apt update && apt upgrade -y

echo ""
echo "→ Installing Docker..."
if command -v docker &> /dev/null; then
    echo "  Docker already installed"
else
    curl -fsSL https://get.docker.com | sh
    usermod -aG docker $REAL_USER
    echo "  Docker installed successfully"
fi

echo ""
echo "→ Installing Docker Compose..."
apt install docker-compose-plugin -y

echo ""
echo "→ Applying system optimizations..."

# TCP backlog
if ! grep -q "net.core.somaxconn=1024" /etc/sysctl.conf; then
    echo "net.core.somaxconn=1024" >> /etc/sysctl.conf
fi

# VM overcommit for Redis
if ! grep -q "vm.overcommit_memory=1" /etc/sysctl.conf; then
    echo "vm.overcommit_memory=1" >> /etc/sysctl.conf
fi

# Apply sysctl
sysctl -p

# Disable transparent huge pages
echo never > /sys/kernel/mm/transparent_hugepage/enabled 2>/dev/null || true
echo never > /sys/kernel/mm/transparent_hugepage/defrag 2>/dev/null || true

# Make THP disable persistent
if [ ! -f /etc/systemd/system/disable-thp.service ]; then
    cat > /etc/systemd/system/disable-thp.service << 'EOF'
[Unit]
Description=Disable Transparent Huge Pages (THP)
After=sysinit.target local-fs.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'echo never > /sys/kernel/mm/transparent_hugepage/enabled && echo never > /sys/kernel/mm/transparent_hugepage/defrag'

[Install]
WantedBy=basic.target
EOF
    systemctl daemon-reload
    systemctl enable disable-thp
fi

# Increase file limits
if ! grep -q "65535" /etc/security/limits.conf; then
    echo "* soft nofile 65535" >> /etc/security/limits.conf
    echo "* hard nofile 65535" >> /etc/security/limits.conf
fi

echo ""
echo "→ Setting up firewall (UFW)..."
apt install ufw -y
ufw --force enable
ufw allow ssh

echo ""
echo "=========================================="
echo "  ✅ Server setup complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Log out and back in (for Docker group)"
echo "2. Configure firewall for Redis:"
echo "   sudo ufw allow from <WORKER_IP> to any port 6379"
echo ""
echo "3. Upload redis folder and deploy:"
echo "   cd /path/to/redis"
echo "   # Update password in redis.conf and docker-compose.yml"
echo "   docker compose up -d"
echo ""
echo "4. Verify:"
echo "   docker compose ps"
echo "   docker exec redis-coordinator redis-cli -a YOUR_PASSWORD ping"
echo ""

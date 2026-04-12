# Redis Coordinator - Deployment Guide

Central Redis instance for distributed job queue, shared state, and token pool.

---

## 📋 Quick Start

### 1. Generate a Secure Password

```bash
# Generate a strong password
openssl rand -base64 32
```

### 2. Update Configuration

Replace `YOUR_STRONG_PASSWORD_HERE` in both files:
- `redis.conf` (line: `requirepass`)
- `docker-compose.yml` (healthcheck and redis-commander)

```bash
# Quick replace (macOS/Linux)
NEW_PASSWORD=$(openssl rand -base64 32)
sed -i.bak "s/YOUR_STRONG_PASSWORD_HERE/$NEW_PASSWORD/g" redis.conf docker-compose.yml
echo "Password set to: $NEW_PASSWORD"
```

### 3. Deploy Redis

```bash
cd redis
docker-compose up -d
```

### 4. Verify Deployment

```bash
# Check container status
docker-compose ps

# Test connection
docker exec redis-coordinator redis-cli -a YOUR_PASSWORD ping
# Expected: PONG
```

---

## 🖥️ Server Preparation (Fresh Server)

### Ubuntu/Debian

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Install Docker Compose
sudo apt install docker-compose-plugin -y

# Logout and login to apply group changes
exit

# Clone/upload your redis folder, then:
cd /path/to/redis
docker compose up -d
```

### System Tuning (Recommended)

```bash
# Increase max connections
echo "net.core.somaxconn=1024" | sudo tee -a /etc/sysctl.conf

# Disable transparent huge pages (Redis recommendation)
echo never | sudo tee /sys/kernel/mm/transparent_hugepage/enabled

# Increase max open files
echo "* soft nofile 65535" | sudo tee -a /etc/security/limits.conf
echo "* hard nofile 65535" | sudo tee -a /etc/security/limits.conf

# Apply sysctl changes
sudo sysctl -p
```

### Firewall Configuration

```bash
# UFW (Ubuntu)
sudo ufw allow from 10.0.0.0/8 to any port 6379    # Private network only
sudo ufw deny 6379                                   # Block public access

# Or for specific worker IPs:
sudo ufw allow from 10.0.1.10 to any port 6379
sudo ufw allow from 10.0.1.11 to any port 6379
```

---

## 🔌 Worker Connection

### Connection String Format

```
redis://default:YOUR_PASSWORD@SERVER_IP:6379/0
```

### Connection Examples

**Python (redis-py)**
```python
import redis

r = redis.Redis(
    host='10.0.0.5',          # Redis server IP
    port=6379,
    password='YOUR_PASSWORD',
    db=0,
    decode_responses=True,
    socket_timeout=5,
    socket_connect_timeout=5,
    retry_on_timeout=True
)

# Connection pool for high throughput
pool = redis.ConnectionPool(
    host='10.0.0.5',
    port=6379,
    password='YOUR_PASSWORD',
    db=0,
    max_connections=20,
    decode_responses=True
)
r = redis.Redis(connection_pool=pool)
```

**Node.js (ioredis)**
```javascript
const Redis = require('ioredis');

const redis = new Redis({
  host: '10.0.0.5',
  port: 6379,
  password: 'YOUR_PASSWORD',
  db: 0,
  retryStrategy: (times) => Math.min(times * 50, 2000),
  maxRetriesPerRequest: 3
});
```

**Environment Variable**
```bash
export REDIS_URL="redis://default:YOUR_PASSWORD@10.0.0.5:6379/0"
```

---

## 📊 Health Check Commands

### Basic Health

```bash
# From Redis server
docker exec redis-coordinator redis-cli -a YOUR_PASSWORD ping
# → PONG

# Remote check
redis-cli -h 10.0.0.5 -a YOUR_PASSWORD ping
```

### Queue Status

```bash
# Check queue length
docker exec redis-coordinator redis-cli -a YOUR_PASSWORD LLEN jobs:pending

# View queue items (without removing)
docker exec redis-coordinator redis-cli -a YOUR_PASSWORD LRANGE jobs:pending 0 10
```

### Memory & Performance

```bash
# Memory usage
docker exec redis-coordinator redis-cli -a YOUR_PASSWORD INFO memory

# Connected clients
docker exec redis-coordinator redis-cli -a YOUR_PASSWORD CLIENT LIST

# Server stats
docker exec redis-coordinator redis-cli -a YOUR_PASSWORD INFO stats

# Slow queries
docker exec redis-coordinator redis-cli -a YOUR_PASSWORD SLOWLOG GET 10
```

### Full Health Script

```bash
#!/bin/bash
# save as: health-check.sh

REDIS_CLI="docker exec redis-coordinator redis-cli -a YOUR_PASSWORD"

echo "=== Redis Health Check ==="
echo ""

echo "→ Ping: $($REDIS_CLI PING)"
echo "→ Uptime: $($REDIS_CLI INFO server | grep uptime_in_days)"
echo "→ Connected Clients: $($REDIS_CLI INFO clients | grep connected_clients)"
echo "→ Memory Used: $($REDIS_CLI INFO memory | grep used_memory_human)"
echo "→ Memory Peak: $($REDIS_CLI INFO memory | grep used_memory_peak_human)"
echo ""

echo "=== Queue Lengths ==="
for queue in jobs:pending jobs:processing jobs:completed jobs:failed; do
    len=$($REDIS_CLI LLEN $queue 2>/dev/null || echo "0")
    echo "→ $queue: $len"
done
echo ""

echo "=== Persistence Status ==="
echo "→ RDB: $($REDIS_CLI INFO persistence | grep rdb_last_save_time)"
echo "→ AOF: $($REDIS_CLI INFO persistence | grep aof_enabled)"
```

---

## 💾 Persistence & Backup

### Backup Strategy

```bash
# Manual RDB snapshot
docker exec redis-coordinator redis-cli -a YOUR_PASSWORD BGSAVE

# Copy backup file
docker cp redis-coordinator:/data/dump.rdb ./backup-$(date +%Y%m%d).rdb

# Automated daily backup (add to cron)
0 2 * * * docker exec redis-coordinator redis-cli -a YOUR_PASSWORD BGSAVE && \
          sleep 5 && \
          docker cp redis-coordinator:/data/dump.rdb /backups/redis-$(date +\%Y\%m\%d).rdb
```

### Restore from Backup

```bash
# Stop Redis
docker-compose down

# Replace data file
docker run --rm -v redis-coordinator-data:/data -v $(pwd):/backup alpine \
    cp /backup/dump.rdb /data/dump.rdb

# Start Redis
docker-compose up -d
```

---

## 🔧 Non-Docker Deployment (Alternative)

### Install Redis Directly

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install redis-server -y

# Copy configuration
sudo cp redis.conf /etc/redis/redis.conf

# Set permissions
sudo chown redis:redis /etc/redis/redis.conf
sudo chmod 640 /etc/redis/redis.conf

# Create data directory
sudo mkdir -p /var/lib/redis
sudo chown redis:redis /var/lib/redis

# Update data directory in config
sudo sed -i 's|dir /data|dir /var/lib/redis|' /etc/redis/redis.conf

# Enable and start
sudo systemctl enable redis-server
sudo systemctl restart redis-server

# Check status
sudo systemctl status redis-server
```

---

## 📈 Monitoring (Optional)

### Prometheus + Grafana

Add to `docker-compose.yml`:

```yaml
  redis-exporter:
    image: oliver006/redis_exporter:latest
    container_name: redis-exporter
    restart: unless-stopped
    environment:
      - REDIS_ADDR=redis://redis:6379
      - REDIS_PASSWORD=YOUR_PASSWORD
    ports:
      - "9121:9121"
    networks:
      - redis-network
    depends_on:
      - redis
```

---

## 🚨 Troubleshooting

### Connection Refused

```bash
# Check if Redis is running
docker ps | grep redis

# Check logs
docker-compose logs redis

# Verify binding
docker exec redis-coordinator redis-cli -a YOUR_PASSWORD CONFIG GET bind
```

### Memory Issues

```bash
# Check memory
docker exec redis-coordinator redis-cli -a YOUR_PASSWORD INFO memory

# If near limit, check key sizes
docker exec redis-coordinator redis-cli -a YOUR_PASSWORD --bigkeys
```

### Slow Performance

```bash
# Check slow log
docker exec redis-coordinator redis-cli -a YOUR_PASSWORD SLOWLOG GET 25

# Check client connections
docker exec redis-coordinator redis-cli -a YOUR_PASSWORD CLIENT LIST
```

### Data Loss After Restart

Ensure these settings in `redis.conf`:
- `appendonly yes` (AOF enabled)
- `appendfsync everysec` (fsync policy)
- RDB `save` directives are configured

---

## 📁 Key Naming Convention (Recommended)

| Purpose | Key Pattern | Type |
|---------|-------------|------|
| Pending jobs | `jobs:pending` | LIST |
| Processing jobs | `jobs:processing:{worker_id}` | LIST |
| Completed jobs | `jobs:completed` | LIST |
| Failed jobs | `jobs:failed` | LIST |
| Token pool | `tokens:available` | LIST |
| Token in use | `tokens:inuse:{worker_id}` | STRING |
| Shared state | `state:{key}` | STRING/HASH |
| Locks | `lock:{resource}` | STRING |
| Rate limits | `ratelimit:{resource}` | STRING |

---

## 🔐 Security Checklist

- [ ] Changed default password in `redis.conf`
- [ ] Changed password in `docker-compose.yml` healthcheck
- [ ] Firewall configured to allow only worker IPs
- [ ] Dangerous commands disabled (FLUSHDB, FLUSHALL)
- [ ] Redis Commander disabled in production
- [ ] TLS configured (if over public network)
- [ ] Regular backups configured

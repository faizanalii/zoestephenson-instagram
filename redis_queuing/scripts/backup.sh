#!/bin/bash
# =============================================================================
# Redis Backup Script
# Usage: bash backup.sh [password] [backup_dir]
# Add to cron for automated backups:
#   0 */6 * * * /path/to/backup.sh YOUR_PASSWORD /backups >> /var/log/redis-backup.log 2>&1
# =============================================================================

set -e

# Configuration
REDIS_PASSWORD="${1:-YOUR_STRONG_PASSWORD_HERE}"
BACKUP_DIR="${2:-./backups}"
REDIS_CONTAINER="redis-coordinator"
REDIS_CLI="docker exec $REDIS_CONTAINER redis-cli -a $REDIS_PASSWORD --no-auth-warning"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=7

echo "[$(date)] Starting Redis backup..."

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Trigger RDB save
echo "[$(date)] Triggering BGSAVE..."
$REDIS_CLI BGSAVE

# Wait for save to complete
echo "[$(date)] Waiting for BGSAVE to complete..."
while [ "$($REDIS_CLI LASTSAVE)" == "$LAST_SAVE" ]; do
    sleep 1
done
sleep 2  # Extra buffer

# Copy RDB file
echo "[$(date)] Copying dump.rdb..."
docker cp $REDIS_CONTAINER:/data/dump.rdb "$BACKUP_DIR/redis-$TIMESTAMP.rdb"

# Copy AOF if exists
if docker exec $REDIS_CONTAINER test -f /data/appendonly.aof; then
    echo "[$(date)] Copying appendonly.aof..."
    docker cp $REDIS_CONTAINER:/data/appendonly.aof "$BACKUP_DIR/redis-$TIMESTAMP.aof"
fi

# Compress backup
echo "[$(date)] Compressing backup..."
cd "$BACKUP_DIR"
tar -czf "redis-$TIMESTAMP.tar.gz" "redis-$TIMESTAMP.rdb" 2>/dev/null && rm "redis-$TIMESTAMP.rdb"
if [ -f "redis-$TIMESTAMP.aof" ]; then
    tar -czf "redis-$TIMESTAMP-aof.tar.gz" "redis-$TIMESTAMP.aof" && rm "redis-$TIMESTAMP.aof"
fi

# Clean old backups
echo "[$(date)] Cleaning backups older than $RETENTION_DAYS days..."
find "$BACKUP_DIR" -name "redis-*.tar.gz" -mtime +$RETENTION_DAYS -delete

# List current backups
echo "[$(date)] Current backups:"
ls -lh "$BACKUP_DIR"/redis-*.tar.gz 2>/dev/null || echo "  No backups found"

echo "[$(date)] Backup complete: redis-$TIMESTAMP.tar.gz"

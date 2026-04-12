#!/bin/bash
# =============================================================================
# Redis Health Check Script
# Usage: bash health-check.sh [password]
# =============================================================================

# Configuration
REDIS_PASSWORD="${1:-YOUR_STRONG_PASSWORD_HERE}"
REDIS_CONTAINER="redis-coordinator"
REDIS_CLI="docker exec $REDIS_CONTAINER redis-cli -a $REDIS_PASSWORD --no-auth-warning"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo ""
echo "=========================================="
echo "  Redis Health Check"
echo "=========================================="
echo ""

# Check if container is running
if ! docker ps | grep -q $REDIS_CONTAINER; then
    echo -e "${RED}❌ Redis container is not running!${NC}"
    echo "   Run: docker-compose up -d"
    exit 1
fi

# Ping test
PING=$($REDIS_CLI PING 2>/dev/null)
if [ "$PING" == "PONG" ]; then
    echo -e "${GREEN}✓ Connection: OK${NC}"
else
    echo -e "${RED}✗ Connection: FAILED${NC}"
    echo "  Check password and container status"
    exit 1
fi

echo ""
echo "=== Server Info ==="
UPTIME=$($REDIS_CLI INFO server | grep uptime_in_seconds | cut -d: -f2 | tr -d '\r')
UPTIME_DAYS=$((UPTIME / 86400))
UPTIME_HOURS=$(((UPTIME % 86400) / 3600))
echo "→ Uptime: ${UPTIME_DAYS}d ${UPTIME_HOURS}h"

VERSION=$($REDIS_CLI INFO server | grep redis_version | cut -d: -f2 | tr -d '\r')
echo "→ Version: $VERSION"

echo ""
echo "=== Memory ==="
USED=$($REDIS_CLI INFO memory | grep used_memory_human | cut -d: -f2 | tr -d '\r')
PEAK=$($REDIS_CLI INFO memory | grep used_memory_peak_human | cut -d: -f2 | tr -d '\r')
MAXMEM=$($REDIS_CLI CONFIG GET maxmemory | tail -1)
if [ "$MAXMEM" == "0" ]; then
    MAXMEM="unlimited"
else
    MAXMEM=$(echo "scale=2; $MAXMEM / 1024 / 1024 / 1024" | bc)GB
fi
echo "→ Used: $USED"
echo "→ Peak: $PEAK"
echo "→ Limit: $MAXMEM"

echo ""
echo "=== Clients ==="
CLIENTS=$($REDIS_CLI INFO clients | grep connected_clients | cut -d: -f2 | tr -d '\r')
BLOCKED=$($REDIS_CLI INFO clients | grep blocked_clients | cut -d: -f2 | tr -d '\r')
echo "→ Connected: $CLIENTS"
echo "→ Blocked (BRPOP): $BLOCKED"

echo ""
echo "=== Persistence ==="
AOF=$($REDIS_CLI INFO persistence | grep aof_enabled | cut -d: -f2 | tr -d '\r')
if [ "$AOF" == "1" ]; then
    echo -e "→ AOF: ${GREEN}enabled${NC}"
else
    echo -e "→ AOF: ${YELLOW}disabled${NC}"
fi

RDB_STATUS=$($REDIS_CLI INFO persistence | grep rdb_last_bgsave_status | cut -d: -f2 | tr -d '\r')
if [ "$RDB_STATUS" == "ok" ]; then
    echo -e "→ RDB Last Save: ${GREEN}OK${NC}"
else
    echo -e "→ RDB Last Save: ${RED}$RDB_STATUS${NC}"
fi

LAST_SAVE=$($REDIS_CLI LASTSAVE)
LAST_SAVE_DATE=$(date -d @$LAST_SAVE 2>/dev/null || date -r $LAST_SAVE 2>/dev/null || echo "N/A")
echo "→ Last Snapshot: $LAST_SAVE_DATE"

echo ""
echo "=== Queue Lengths ==="
for queue in jobs:pending jobs:processing jobs:completed jobs:failed tokens:available; do
    LEN=$($REDIS_CLI LLEN $queue 2>/dev/null)
    if [ -n "$LEN" ] && [ "$LEN" != "(integer) 0" ]; then
        echo "→ $queue: $LEN"
    else
        echo "→ $queue: 0"
    fi
done

echo ""
echo "=== Performance ==="
OPS=$($REDIS_CLI INFO stats | grep instantaneous_ops_per_sec | cut -d: -f2 | tr -d '\r')
echo "→ Ops/sec: $OPS"

SLOW=$($REDIS_CLI SLOWLOG LEN)
echo "→ Slow queries logged: $SLOW"

echo ""
echo "=== Key Stats ==="
KEYS=$($REDIS_CLI DBSIZE | grep -oE '[0-9]+')
echo "→ Total keys: $KEYS"

echo ""
echo "=========================================="
echo -e "  ${GREEN}Health check complete${NC}"
echo "=========================================="
echo ""

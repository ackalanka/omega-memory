#!/usr/bin/env bash
set -euo pipefail

# OMEGA Database Sync -- push/pull omega.db to/from remote host
#
# Usage:
#   ./scripts/sync-db.sh push          # local -> remote
#   ./scripts/sync-db.sh pull          # remote -> local backup
#
# Configuration (environment variables):
#   OMEGA_REMOTE_HOST  -- SSH host (e.g., user@host or fly machine name)
#   OMEGA_REMOTE_PATH  -- Remote DB path (default: /data/omega/omega.db)
#   OMEGA_LOCAL_DB     -- Local DB path (default: ~/.omega/omega.db)

REMOTE_HOST="${OMEGA_REMOTE_HOST:?Set OMEGA_REMOTE_HOST (e.g., user@myhost)}"
REMOTE_PATH="${OMEGA_REMOTE_PATH:-/data/omega/omega.db}"
LOCAL_DB="${OMEGA_LOCAL_DB:-$HOME/.omega/omega.db}"
BACKUP_DIR="$HOME/.omega/backups"

case "${1:-}" in
    push)
        echo "Pushing local DB to remote..."
        if [ ! -f "$LOCAL_DB" ]; then
            echo "Error: Local DB not found at $LOCAL_DB"
            exit 1
        fi
        # WAL checkpoint before copying to ensure consistency
        python3.11 -c "
import sqlite3
conn = sqlite3.connect('$LOCAL_DB')
conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
conn.close()
print('WAL checkpoint done')
"
        rsync -avz --progress "$LOCAL_DB" "$REMOTE_HOST:$REMOTE_PATH"
        echo "Done. Pushed $(du -h "$LOCAL_DB" | cut -f1) to $REMOTE_HOST:$REMOTE_PATH"
        ;;
    pull)
        echo "Pulling remote DB to local backup..."
        mkdir -p "$BACKUP_DIR"
        TIMESTAMP=$(date +%Y%m%d-%H%M%S)
        DEST="$BACKUP_DIR/omega-remote-$TIMESTAMP.db"
        rsync -avz --progress "$REMOTE_HOST:$REMOTE_PATH" "$DEST"
        echo "Done. Saved to $DEST ($(du -h "$DEST" | cut -f1))"
        ;;
    *)
        echo "Usage: $0 {push|pull}"
        echo ""
        echo "  push  -- Upload local omega.db to remote host"
        echo "  pull  -- Download remote omega.db to local backup"
        exit 1
        ;;
esac

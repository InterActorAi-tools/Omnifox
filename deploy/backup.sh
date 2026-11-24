#!/bin/sh
# Daily backup of the database and uploaded files. Keeps the last 14 days.
# Cron: 0 3 * * * ~/omnifox/deploy/backup.sh
set -e
cd "$(dirname "$0")"
DIR=~/omnifox-backups
mkdir -p "$DIR" && chmod 700 "$DIR"
DAY=$(date +%F)
docker compose -f docker-compose.server.yml exec -T db pg_dump -U omnifox -Fc omnifox > "$DIR/db-$DAY.dump"
docker compose -f docker-compose.server.yml exec -T backend tar -cz -C /app uploads > "$DIR/uploads-$DAY.tar.gz"
find "$DIR" -type f -mtime +14 -delete

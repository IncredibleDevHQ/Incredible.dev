#!/bin/sh
set -eu

: "${MINIO_ROOT_USER:?Set MINIO_ROOT_USER}"
: "${MINIO_ROOT_PASSWORD:?Set MINIO_ROOT_PASSWORD}"
: "${DESIGN_AGENT_S3_ACCESS_KEY:?Set DESIGN_AGENT_S3_ACCESS_KEY}"
: "${DESIGN_AGENT_S3_SECRET_KEY:?Set DESIGN_AGENT_S3_SECRET_KEY}"
if [ "$MINIO_ROOT_USER" = "$DESIGN_AGENT_S3_ACCESS_KEY" ] || [ "$MINIO_ROOT_PASSWORD" = "$DESIGN_AGENT_S3_SECRET_KEY" ]; then
    echo "Use distinct MinIO admin and application credentials" >&2
    exit 1
fi
if [ "${RAILWAY_VOLUME_MOUNT_PATH:-}" != /data ] || ! mountpoint -q /data; then
    echo "Mount the MinIO data volume at /data" >&2
    exit 1
fi
if [ "$(id -u)" -eq 0 ]; then
    chown minio:minio /data
    export HOME=/home/minio
    exec setpriv --reuid=minio --regid=minio --clear-groups /bin/sh "$0"
fi

# Provision on loopback before opening the service's private network port.
export MINIO_BROWSER=off
export MINIO_INIT_ENDPOINT=http://127.0.0.1:19000
MC_CONFIG_DIR=$(mktemp -d)
export MC_CONFIG_DIR
minio server /data --address 127.0.0.1:19000 &
server=$!
stop_bootstrap() {
    kill "$server" 2>/dev/null || true
    wait "$server" || true
    rm -rf "$MC_CONFIG_DIR"
}
trap stop_bootstrap EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
curl --fail --silent --show-error --retry 30 --retry-connrefused --retry-delay 1 \
    --max-time 2 --retry-max-time 60 "$MINIO_INIT_ENDPOINT/minio/health/ready" >/dev/null
/bin/sh /opt/minio/init.sh
stop_bootstrap
trap - EXIT TERM INT
unset MC_CONFIG_DIR MINIO_INIT_ENDPOINT DESIGN_AGENT_S3_ACCESS_KEY DESIGN_AGENT_S3_SECRET_KEY
exec minio server /data --address :9000

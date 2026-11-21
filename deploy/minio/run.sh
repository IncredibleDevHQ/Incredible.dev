#!/bin/sh
set -eu
: "${MINIO_ROOT_USER:?Set MINIO_ROOT_USER in .env.minio}"
: "${MINIO_ROOT_PASSWORD:?Set MINIO_ROOT_PASSWORD in .env.minio}"
exec minio "$@"

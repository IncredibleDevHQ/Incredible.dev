#!/bin/sh
set -eu
mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
mc mb --ignore-existing local/incredible-files >/dev/null
mc anonymous set none local/incredible-files >/dev/null
mc version enable local/incredible-files >/dev/null
mc admin user add local "$DESIGN_AGENT_S3_ACCESS_KEY" "$DESIGN_AGENT_S3_SECRET_KEY" >/dev/null
mc admin policy create local incredible-files /opt/minio/app-policy.json >/dev/null
mc admin policy attach local incredible-files --user "$DESIGN_AGENT_S3_ACCESS_KEY" >/dev/null
echo 'Private object storage is ready.'

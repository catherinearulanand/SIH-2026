#!/bin/sh
set -eu
if [ ! -f "$SETU_DB" ]; then
  python -m setu_backend.cli init
  python -m setu_backend.cli demo-users --output /data/demo-secrets.env
fi
exec python -m setu_backend.cli serve --host 0.0.0.0 --port 8000

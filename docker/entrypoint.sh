#!/bin/sh
set -eu

mkdir -p \
  /data \
  /data/chat \
  /data/notebook \
  /data/custom_tools \
  /uploads \
  /uploads/icons

exec "$@"

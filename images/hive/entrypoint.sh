#!/bin/bash
set -euo pipefail
case "${1:-}" in
    metastore|server) ;;
    *) echo 'Expected metastore or server' >&2; exit 2 ;;
esac
# shellcheck source=images/common/config-functions.sh
source "$(dirname "$0")/config-functions.sh"
prepare_hadoop_config
prepare_hive_config "${HIVE_CONF_DIR:-/opt/hive/conf}/hive-site.xml"
wait_for_dependencies
exec "$(dirname "$0")/start.sh" "$1"

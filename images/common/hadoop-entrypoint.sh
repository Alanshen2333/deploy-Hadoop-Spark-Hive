#!/bin/bash
set -euo pipefail
# shellcheck source=images/common/config-functions.sh
source "$(dirname "$0")/config-functions.sh"
prepare_hadoop_config
wait_for_dependencies
role=${1:?Missing Hadoop role}
shift

case "$role" in
    namenode)
        : "${CLUSTER_NAME:?Missing cluster name}"
        # The native getconf command reads the supplied XML, including paths.
        namedir=$(hdfs getconf -confKey dfs.namenode.name.dir)
        namedir=${namedir#file://}
        [[ $namedir == /* && $namedir != *,* ]] || {
            echo 'This deployment requires one absolute NameNode directory' >&2; exit 1;
        }
        [[ -d $namedir ]] || { echo "NameNode directory not found: $namedir" >&2; exit 1; }
        if [[ ! -f $namedir/current/VERSION ]]; then
            # Preserve existing data: only a fresh directory may be formatted.
            if [[ -d $namedir/lost+found ]]; then
                rmdir "$namedir/lost+found" || {
                    echo 'Refusing to remove a nonempty lost+found directory' >&2; exit 1;
                }
            fi
            entries=$(find "$namedir" -mindepth 1 -maxdepth 1 -print -quit)
            [[ -z $entries ]] || {
                echo 'Refusing to format a nonempty NameNode directory without current/VERSION' >&2; exit 1;
            }
            hdfs namenode -format "$CLUSTER_NAME" -nonInteractive
        fi
        exec hdfs namenode "$@"
        ;;
    datanode) exec hdfs datanode "$@" ;;
    resourcemanager|nodemanager|historyserver) exec yarn "$role" "$@" ;;
    jobhistory) exec mapred historyserver "$@" ;;
    *) echo "Unknown Hadoop role: $role" >&2; exit 2 ;;
esac

#!/bin/bash
# Shared by mounted entrypoints and derived images. Source files remain read-only.

prepare_hadoop_config() {
    local filename
    export HADOOP_CONF_DIR=${HADOOP_CONF_DIR:-/etc/hadoop}
    mkdir -p "$HADOOP_CONF_DIR"
    for filename in core-site.xml hdfs-site.xml yarn-site.xml mapred-site.xml; do
        [[ -s ${CLUSTER_CONFIG_DIR:-/etc/cluster}/$filename ]] || {
            echo "Missing XML configuration: $filename" >&2; return 1;
        }
        install -m 0644 "${CLUSTER_CONFIG_DIR:-/etc/cluster}/$filename" "$HADOOP_CONF_DIR/$filename"
    done
}

xml_escape() {
    local value=$1
    value=${value//&/\&amp;}
    value=${value//</\&lt;}
    value=${value//>/\&gt;}
    value=${value//\"/\&quot;}
    value=${value//\'/\&apos;}
    printf '%s' "$value"
}

prepare_hive_config() {
    local target=$1 template password prefix suffix
    template=$(cat "${HIVE_CONFIG_FILE:-${CLUSTER_CONFIG_DIR:-/etc/cluster}/hive-site.xml}")
    mkdir -p "$(dirname "$target")"
    if [[ $template == *'@@POSTGRES_PASSWORD@@'* ]]; then
        password=$(cat "${POSTGRES_PASSWORD_FILE:-/run/secrets/postgres_password}")
        [[ -n $password ]] || { echo 'Empty PostgreSQL password' >&2; return 1; }
        prefix=${template%%@@POSTGRES_PASSWORD@@*}
        suffix=${template#*@@POSTGRES_PASSWORD@@}
        [[ $suffix != *'@@POSTGRES_PASSWORD@@'* ]] || {
            echo 'Expected exactly one password placeholder' >&2; return 1;
        }
        # Never eval the template, export the password, or run it through sed.
        install -m 0600 /dev/null "$target"
        (umask 077; printf '%s%s%s\n' "$prefix" "$(xml_escape "$password")" "$suffix" > "$target")
    else
        install -m 0644 "${HIVE_CONFIG_FILE:-${CLUSTER_CONFIG_DIR:-/etc/cluster}/hive-site.xml}" "$target"
    fi
}

wait_for_dependencies() {
    local endpoint host port attempt ready
    for endpoint in ${SERVICE_PRECONDITION:-}; do
        host=${endpoint%:*}
        port=${endpoint##*:}
        [[ -n $host && $host != "$endpoint" && $port =~ ^[0-9]+$ ]] || {
            echo "Invalid dependency: $endpoint" >&2; return 1;
        }
        ready=false
        for ((attempt=1; attempt<=${DEPENDENCY_WAIT_ATTEMPTS:-100}; attempt++)); do
            if timeout "${DEPENDENCY_CONNECT_TIMEOUT:-5}" bash -c \
                'exec 3<>"/dev/tcp/$1/$2"' bash "$host" "$port" 2>/dev/null; then
                ready=true
                break
            fi
            echo "Waiting for $endpoint ($attempt/${DEPENDENCY_WAIT_ATTEMPTS:-100})" >&2
            sleep "${DEPENDENCY_WAIT_INTERVAL:-5}"
        done
        $ready || { echo "Dependency timed out: $endpoint" >&2; return 1; }
    done
}

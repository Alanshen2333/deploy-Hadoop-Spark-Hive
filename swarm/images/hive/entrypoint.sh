#!/bin/bash
set -euo pipefail

case "${1:-}" in
    metastore|server) ;;
    *) echo 'Expected metastore or server' >&2; exit 2 ;;
esac

# Do not feed credentials to the upstream environment renderer: it logs values.
xml_escape() {
    local value=$1
    value=${value//&/\&amp;}
    value=${value//</\&lt;}
    value=${value//>/\&gt;}
    value=${value//\"/\&quot;}
    value=${value//\'/\&apos;}
    printf '%s' "$value"
}
umask 077
if [[ $1 == metastore ]]; then
    password=$(cat /run/secrets/postgres_password)
    [[ -n "$password" ]] || { echo 'Empty PostgreSQL password' >&2; exit 1; }
    cat > /opt/hive/conf/hive-site.xml <<EOF
<configuration>
<property><name>javax.jdo.option.ConnectionURL</name><value>jdbc:postgresql://postgres:5432/hive_metastore</value></property>
<property><name>javax.jdo.option.ConnectionDriverName</name><value>org.postgresql.Driver</value></property>
<property><name>javax.jdo.option.ConnectionUserName</name><value>hive</value></property>
<property><name>javax.jdo.option.ConnectionPassword</name><value>$(xml_escape "$password")</value></property>
<property><name>hive.metastore.warehouse.dir</name><value>/user/hive/warehouse</value></property>
<property><name>hive.metastore.schema.verification</name><value>true</value></property>
<property><name>datanucleus.autoCreateSchema</name><value>false</value></property>
</configuration>
EOF
    unset password
else
    cat > /opt/hive/conf/hive-site.xml <<'EOF'
<configuration>
<property><name>hive.metastore.uris</name><value>thrift://hive-metastore:9083</value></property>
<property><name>hive.metastore.warehouse.dir</name><value>/user/hive/warehouse</value></property>
<property><name>hive.server2.thrift.bind.host</name><value>0.0.0.0</value></property>
<property><name>hive.server2.enable.doAs</name><value>false</value></property>
</configuration>
EOF
fi
# Retain upstream Hadoop configuration and dependency waits.
exec /usr/local/bin/entrypoint.sh /opt/cluster/start.sh "$1"

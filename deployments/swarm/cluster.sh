#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
inventory=${CLUSTER_CONFIG:-./cluster.json}
action=${1:-help}
[[ $# -eq 0 ]] || shift
if [[ $action == help ]]; then
    echo 'Usage: ./deployments/swarm/cluster.sh {render|build|push|deploy|status|hdfs|yarn|hadoop|spark-shell|hive|stop}'
    echo 'CLUSTER_CONFIG selects the JSON inventory (default: deployments/swarm/cluster.json).'
    exit 0
fi
python3 ./render.py "$inventory" >/dev/null
readarray -t settings < <(python3 - "$inventory" <<'PY'
import json, sys
c = json.load(open(sys.argv[1]))
for key in ('stack', 'image_prefix', 'image_tag', 'postgres_password_secret'):
    print(c[key])
PY
)
stack=${settings[0]}
prefix=${settings[1]}
tag=${settings[2]}
secret=${settings[3]}
network=${stack}_cluster
configs=$(pwd)/build

require_manager() {
    [[ $(docker info --format '{{.Swarm.ControlAvailable}}') == true ]] || {
        echo 'Run this command on a Swarm manager.' >&2; exit 1;
    }
}
client_mounts=()
for filename in core-site.xml hdfs-site.xml yarn-site.xml mapred-site.xml hive-site.xml; do
    client_mounts+=(--mount "type=bind,source=$configs/$filename,target=/etc/cluster/$filename,readonly")
done
tty=()
if [[ -t 0 && -t 1 ]]; then tty=(-t); fi
case "$action" in
    render) echo "$configs/stack.json" ;;
    build|push)
        for role in hive spark; do
            if [[ $action == build ]]; then
                docker build --pull --platform linux/amd64 -t "$prefix/$role:$tag" -f "../../images/$role/Dockerfile" ../..
            else
                docker push "$prefix/$role:$tag"
            fi
        done
        ;;
    deploy)
        require_manager
        docker secret inspect "$secret" >/dev/null
        # Validate exact host placement before creating services with local volumes.
        python3 - "$inventory" <<'PY'
import json, subprocess, sys
c = json.load(open(sys.argv[1]))
ids = subprocess.check_output(['docker', 'node', 'ls', '-q'], text=True).split()
nodes = json.loads(subprocess.check_output(['docker', 'node', 'inspect', *ids], text=True))
for host in {c['master_node'], *(w['node'] for w in c['workers'])}:
    matches = [n for n in nodes if n['Description']['Hostname'] == host]
    if len(matches) != 1:
        sys.exit(f'Need exactly one Swarm node with hostname {host}')
    n = matches[0]
    if n['Status']['State'] != 'ready' or n['Spec']['Availability'] != 'active':
        sys.exit(f'Node {host} must be ready and active')
    platform = n['Description']['Platform']
    if platform['OS'] != 'linux' or platform['Architecture'] not in ('x86_64', 'amd64'):
        sys.exit(f'Node {host} must run Linux x86_64 (upstream images are amd64)')
PY
        docker stack config -c "$configs/stack.json" >/dev/null
        docker stack deploy --with-registry-auth -c "$configs/stack.json" "$stack"
        echo 'Deployment submitted. Check status and run ./deployments/swarm/smoke-test.sh after initialization.'
        ;;
    status)
        require_manager
        docker stack services "$stack"
        docker stack ps --no-trunc "$stack"
        ;;
    hdfs|yarn|hadoop)
        docker run --rm -i "${tty[@]}" --network "$network" \
            "${client_mounts[@]}" -e HADOOP_CONF_DIR=/etc/cluster \
            --entrypoint "/opt/hadoop-3.2.1/bin/$action" \
            "bde2020/hadoop-base:2.0.0-hadoop3.2.1-java8" "$@"
        ;;
    spark-shell)
        client="${stack}-spark-client-$$"
        docker run --rm -i "${tty[@]}" --name "$client" --hostname "$client" \
            --network "$network" "${client_mounts[@]}" "$prefix/spark:$tag" \
            /spark/bin/spark-shell --master spark://spark-master:7077 \
            --conf spark.driver.host="$client" --conf spark.driver.bindAddress=0.0.0.0 "$@"
        ;;
    hive)
        # The server role renders hive-site.xml; beeline only needs its JDBC URL.
        docker run --rm -i "${tty[@]}" --network "$network" \
            --entrypoint /opt/hive/bin/beeline "$prefix/hive:$tag" \
            -u jdbc:hive2://hive-server:10000 -n hive "$@"
        ;;
    stop)
        require_manager
        docker stack rm "$stack"
        echo 'Services removed; persistent volumes and the external password secret are retained.'
        ;;
    *) echo "Unknown action: $action" >&2; exit 2 ;;
esac

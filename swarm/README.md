# Docker Swarm 分布式部署

保留根目录的单机 Compose 环境，新增独立的多机部署入口。
版本沿用 Hadoop 3.2.1、Spark 3.3.0、Hive 2.3.2、PostgreSQL 15。
这是一套可信内网中的学习/实验集群，组件未配置 Kerberos、TLS 或用户隔离。
不要把这些服务的端口直接开放到公网。

## 拓扑与持久化

| 节点 | 服务 | 持久化内容 |
| --- | --- | --- |
| `master_node` 指定的主机 | NameNode、ResourceManager、Timeline Server、MapReduce JobHistory、Spark Master、PostgreSQL、Hive Metastore、HiveServer2 | NameNode 元数据、PostgreSQL 数据、Timeline 数据 |
| 每台工作机 | 独立 DataNode、NodeManager、Spark Worker | HDFS 数据块、YARN 本地目录、Spark 工作目录 |

服务在可 attach 的 overlay 网络中通信，不依赖宿主机上的项目目录。
每个服务使用 DNSRR、一个副本和固定 `node.hostname` 放置约束。
HDFS 使用工作节点的独立服务名称访问 DataNode，Spark 和 YARN 同样注册可解析的名称。
发布端口使用 `mode: host`，因此 Web UI/JDBC 访问对应服务实际所在的主机。

本地卷不跨主机复制：主机离线后服务保持待调度，不会在另一台主机自动启动空卷。
NameNode、PostgreSQL、RM、Spark Master 均为单实例，**这不是 HA 集群**。
HDFS 副本保护数据块，但不代替 NameNode / PostgreSQL 备份。
不要修改已有 worker 的 `id`、`node`、stack 名称或主机 hostname 来“迁移”数据。

## 1. 准备 Swarm

要求：Linux x86_64 主机、Docker Engine（建议 24+）、部署主机安装 Bash 和 Python 3.9+。
现有上游大数据镜像主要面向 amd64。部署命令在 Swarm manager 上运行；
主服务所在的 `master_node` 可以是另一台普通 worker，但建议明确规划持久盘。

在 manager 初始化，在其余主机执行输出的 join 命令：

```bash
docker swarm init --advertise-addr <manager内网IP>
docker swarm join-token worker
docker node ls
```

Swarm 节点之间允许 TCP 2377、TCP/UDP 7946、UDP 4789。
多网卡环境明确设置 `--advertise-addr`，必要时同时设置 `--data-path-addr`。
overlay 使用默认地址池；如与你的 LAN/VPN 冲突，在初始化 Swarm 时选择合适地址池。

## 2. 配置节点与资源

以下操作从仓库根目录执行：

```bash
cp swarm/cluster.example.json swarm/cluster.json
# 修改 cluster.json 中的 master_node、workers[*].node 为 docker node ls 显示的 HOSTNAME
# 修改 image_prefix 为各节点都能拉取的镜像仓库路径
./swarm/cluster.sh render
```

默认两台工作机、HDFS 两副本；允许主服务与一台工作服务共用主机。
每台物理机只允许一个 worker 条目，避免持久卷身份和 host 端口冲突。
只有一台工作机时将 `hdfs_replication` 改为 1。
`workers[*].id` 是持久服务/数据卷身份，`node` 是 Swarm 中的主机 hostname。

每台工作机默认向 YARN 提供 4096 MB / 2 vcores，向 Spark 提供 2G / 2 cores。
YARN 与 Spark Standalone 是两个独立调度器，这些配额会叠加。
还要为 DataNode、NodeManager、操作系统和 JVM 预留内存；默认建议工作机至少 8 GB，
主服务所在主机建议 16 GB，主服务与工作服务同机时需更多。
这里配置的是调度器配额，未设置容器硬内存上限。
MapReduce 示例默认 map/reduce 各申请 1024 MB。

## 3. 创建 PostgreSQL 密码 Secret

在 manager 创建一个随机密码，不写入 inventory 或 Git：

```bash
openssl rand -hex 32 | docker secret create bigdata_postgres_password -
```

`postgres_password_secret` 必须与创建的 Secret 名一致。
Secret 仅挂载给 PostgreSQL 和 Hive Metastore；Spark / HiveServer2 通过 Thrift
访问 Metastore，不直接持有数据库密码。不要手动给容器启用 shell tracing。
已有 PostgreSQL 数据卷的密码不会因为替换 Secret 自动改变；密码轮换需同时修改数据库用户。

## 4. 构建并推送派生镜像

Swarm 不执行 `build:`，因此先构建并推到所有节点可访问的 registry。
两个派生镜像沿用 BDE 镜像：

- Hive：内置启动脚本和经 SHA256 校验的 PostgreSQL JDBC 42.7.4，启动独立 Metastore / HiveServer2。
- Spark：共用一个镜像启动 Master / Worker，读取 Swarm configs，并将日志写到标准输出。

```bash
docker login ghcr.io  # 或你配置的 registry
./swarm/cluster.sh build
./swarm/cluster.sh push
```

示例 `image_prefix` 是建议路径，**仓库并不预先提供这些已发布镜像**。
`image_tag` 建议使用不可变的版本号或 commit SHA；改了镜像后使用新 tag 并重新部署。
构建需要访问 Docker Hub 和 jdbc.postgresql.org。
Hadoop 各角色沿用现有镜像，部署时各节点还需能访问 Docker Hub。
私有 registry 使用 manager 的 `docker login` 和部署脚本的 `--with-registry-auth`。

## 5. 部署和验收

```bash
./swarm/cluster.sh deploy
./swarm/cluster.sh status
./swarm/smoke-test.sh
```

部署前检查节点 hostname 唯一、ready/active、Linux x86_64 及 Secret 存在。
部署是异步的：`deploy` 成功只表示任务已提交。
Hadoop / Hive 通过依赖端口等待和 HDFS 写入重试初始化，首次拉取镜像需要几分钟。
Metastore 单副本以 stop-first 更新，先检查/初始化并验证 schema；初始化失败会报错并重启。
没有数据库版本自动升级或自动格式化已有 HDFS 卷的流程。

验收脚本检查所有 DataNode / NodeManager / Spark Worker 注册，执行真实 HDFS 写入和读取、
YARN MapReduce Pi 作业、HiveServer2 元数据查询，以及 Spark 计算和共享 Metastore 查询。
脚本是一次性检查；服务未就绪时会失败，可在排查/等待后重跑。
成功 marker 用于防止 Spark REPL 吞掉 Scala 错误。

```bash
./swarm/cluster.sh hdfs dfsadmin -report
./swarm/cluster.sh yarn node -list -all
./swarm/cluster.sh hive
./swarm/cluster.sh spark-shell
```

客户端通过临时容器加入 overlay；Spark driver 使用客户端容器的 DNS 名称供 executor 回连。
因此不需要原项目中固定的 `spark-driver.local:172.18.0.1` 映射。
从外部裸机直接连接 NameNode 或 Spark Master 并不足以完成分布式作业：还需能访问
所有 DataNode / executor 的 overlay 地址。本方案优先使用上述集群内客户端，
只向外发布 Web UI 和 HiveServer2 JDBC。

| 服务 | 所在主机 | 宿主机端口 |
| --- | --- | --- |
| NameNode Web | 主服务主机 | 19870 |
| ResourceManager Web | 主服务主机 | 18088 |
| Timeline Web | 主服务主机 | 18188 |
| MapReduce JobHistory Web | 主服务主机 | 19888 |
| Spark Master Web | 主服务主机 | 18080 |
| HiveServer2 JDBC / Web | 主服务主机 | 20000 / 20002 |
| DataNode Web | 每台工作机 | 19864 |
| NodeManager Web | 每台工作机 | 18042 |
| Spark Worker Web | 每台工作机 | 18081 |

部分 UI 中的内部服务链接仍使用 overlay DNS 名称和容器端口。
从宿主机浏览器访问时可按上表直接打开对应主机和端口。

## 扩容、停止与故障排查

加入新 Swarm 节点，在 `workers` 增加新的 `id` / `node` 条目，再运行 `deploy`。
原有服务和数据卷名称保持不变，新节点只新增自己的工作服务。
需要提高新文件的副本数时修改 `hdfs_replication` 并重新部署；
既有文件通过 `hdfs dfs -setrep` 单独调整，必要时运行 HDFS balancer。

**缩容不能直接删 worker 条目**：先按 Hadoop 流程退役 DataNode、迁移数据并确认目标副本数，
停止向该 NodeManager / Spark Worker 调度，完成作业后再手动删除对应 Swarm 服务。
脚本刻意不加 `--prune`，避免 inventory 误删条目导致工作节点被自动移除。

```bash
./swarm/cluster.sh stop
# docker stack rm 异步停止服务；卷和外部 Secret 保留
```

诊断命令（stack 名按 inventory 修改）：

```bash
docker stack ps --no-trunc bigdata
docker service logs --tail 100 bigdata_hive-metastore
docker service logs --tail 100 bigdata_datanode-worker-1
docker service logs --tail 100 bigdata_spark-worker-1
```

Pending 通常是节点约束/状态问题；Rejected 常见原因是镜像拉取失败或端口冲突。
旧单机 Compose 也占用部分相同端口，同机部署前停止旧环境。
本方案使用单独命名的数据卷，**不会自动迁移单机 Compose 的已有数据**。
不要直接复制正在运行的 PostgreSQL 或 NameNode 数据目录作为备份。

## 验证和 CI

```bash
python3 -m unittest discover -s swarm/tests -v
python3 swarm/render.py swarm/cluster.example.json
docker stack config -c swarm/build/stack.json >/dev/null
```

push/PR CI 验证拓扑、扩容身份保持、Secret 隔离、XML、ShellCheck 和 Docker stack 语法。
可手动触发 `Swarm deployment` workflow 并启用 `smoke`，构建镜像并在单机 Swarm
跑真实服务和验收。该测试验证服务协作；真实多机的防火墙、MTU、存储和网络仍需
在目标 Swarm 上跑同一验收脚本。生成配置只依赖 Python 标准库，不需要 PyYAML。

实现依据：[Docker Swarm 网络](https://docs.docker.com/engine/swarm/networking/)、
[DNSRR 与 host 发布端口](https://docs.docker.com/engine/swarm/ingress/)、
[Spark 配置](https://spark.apache.org/docs/3.3.0/configuration.html)。

# Docker Compose 单机部署

在一台主机上启动 Hadoop、Spark、Hive 和 PostgreSQL 学习环境。
与 [Swarm 多机部署](../swarm/README.md) 共用仓库中的 `config/hadoop/*.xml`，
Compose 编排、客户端脚本和挂载文件均在本目录维护。

## 环境要求

- Docker Engine 20.10 或更高版本。
- Docker Compose 1.29 或更高版本，提供 `docker-compose` 命令。
- Bash。

## 启动与常用操作

以下命令从仓库根目录执行；脚本会自动切换到本目录。

```bash
./deployments/compose/start-cluster.sh
./deployments/compose/status-cluster.sh
./deployments/compose/hive-cli.sh
./deployments/compose/spark-shell.sh
./deployments/compose/stop-cluster.sh
```

启动脚本拉取镜像并启动容器，等待 30 秒后尝试创建 HDFS 基础目录并设置权限。
固定等待时间不保证所有服务已就绪，可使用状态脚本和服务日志确认。
停止脚本保留 Docker 命名卷。

## 项目名与持久化

脚本通过 `config.sh` 将默认项目名固定为 `deploy-hadoop-spark-hive`，
与原仓库根目录部署的默认名称一致，避免目录搬迁后创建另一组空数据卷。
如果原仓库目录名称不同，或以前通过 `-p` / 环境变量设置过项目名，请沿用原值：

```bash
COMPOSE_PROJECT_NAME=my-existing-project ./deployments/compose/start-cluster.sh
COMPOSE_PROJECT_NAME=my-existing-project ./deployments/compose/status-cluster.sh
COMPOSE_PROJECT_NAME=my-existing-project ./deployments/compose/stop-cluster.sh
```

客户端脚本也应使用同一个 `COMPOSE_PROJECT_NAME`。可在终端会话中提前设置该环境变量。
直接运行 Compose 命令时显式指定相同项目名和配置文件：

```bash
docker-compose -p deploy-hadoop-spark-hive -f deployments/compose/docker-compose.yml ps
docker-compose -p deploy-hadoop-spark-hive -f deployments/compose/docker-compose.yml logs --tail 100 hive-server
```

HDFS、Timeline 和 PostgreSQL 数据保存在 Docker 命名卷中。
`data/` 与 `logs/` 是本地文件预留目录，当前编排未挂载它们。
目录调整保留服务名称、卷名称和网络配置；Compose 与 Swarm 使用不同的持久化身份。

## PostgreSQL 密码

PostgreSQL、Hive 和 Spark 共用 Compose 的 `postgres_password` 文件 Secret。
默认读取 `secrets/postgres_password.example`，内容为原学习环境密码 `hive`，便于已有默认数据库继续使用。
Hive XML 中的 `@@POSTGRES_PASSWORD@@` 在启动时替换；配置源文件保持只读，生成文件权限为 0600。
Spark 沿用单机模式的直接 JDBC Metastore 连接，因此也需要此 Secret。

使用自定义密码时，将密码写入本目录下未跟踪的 `secrets/postgres_password`，
并将宿主机环境变量 `POSTGRES_PASSWORD_FILE` 设置为该文件的绝对路径，启动集群。
状态、停止等 Compose 命令也应沿用该路径。容器内的读取路径固定为 `/run/secrets/postgres_password`。
已有 PostgreSQL 卷不会因为修改文件自动更新数据库密码，必须沿用原密码或先完成数据库密码轮换。

## 配置与访问地址

- `docker-compose.yml`：服务、实际端口映射、命名卷及网络。
- `config.sh`：项目名、脚本展示的宿主机端口及容器内客户端端口。修改端口时需同步编排配置。
- `../../config/hadoop/*.xml`：共享 Hadoop 原生配置，只读挂载，启动时复制到组件配置目录。
- `../../config/hive/compose/hive-site.xml`：Hive 与 Spark 共享的单机 Metastore 配置模板。
- `../../images/common/`：XML 复制和依赖等待入口，跳过 BDE 的环境变量转 XML 脚本。
- `hive-entrypoint.sh`、`jars/`：Compose 容器挂载文件。

| 服务 | 容器端口 | 默认宿主机端口 |
| --- | --- | --- |
| HDFS NameNode Web / RPC | 9870 / 9000 | 19870 / 19000 |
| YARN ResourceManager Web | 8088 | 18088 |
| YARN NodeManager Web | 8042 | 18042 |
| MapReduce History | 8188 | 18188 |
| Spark Master Web / RPC | 8080 / 7077 | 18080 / 17077 |
| Spark Worker Web | 8081 | 18081 |
| HiveServer2 JDBC / Web | 10000 / 10002 | 20000 / 20002 |
| PostgreSQL | 5432 | 25432 |

Web UI 使用 `http://localhost:<宿主机端口>` 访问。
Spark 客户端沿用单机编排的 `spark-driver.local:172.18.0.1` 映射。

## 配置验证

```bash
docker-compose -p deploy-hadoop-spark-hive -f deployments/compose/docker-compose.yml config
```

该命令只检查和展开编排配置，实际启动与服务状态需在运行 Docker 的主机上确认。

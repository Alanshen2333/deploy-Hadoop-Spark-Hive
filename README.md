# Dockerized Hadoop + Spark + Hive

使用 Docker 部署 Hadoop、Spark 和 Hive 学习/实验集群，提供单机 Compose 和多机 Swarm 两种部署方式。

| 部署方式 | 适用场景 | 操作指南 |
| --- | --- | --- |
| Docker Compose | 单机学习、开发与组件联调 | [Compose 部署指南](deployments/compose/README.md) |
| Docker Swarm | 多台 Linux 主机、可扩展的 HDFS / YARN / Spark 工作节点 | [Swarm 部署指南](deployments/swarm/README.md) |

组件版本：Hadoop 3.2.1、Spark 3.3.0、Hive 2.3.2、PostgreSQL 15。
Compose 使用 PostgreSQL 元数据库；Swarm 使用独立 Hive Metastore + PostgreSQL。

## 项目结构

```text
.
├── deployments/               # 按部署方式组织入口与专用配置
│   ├── compose/
│   │   ├── README.md
│   │   ├── docker-compose.yml
│   │   ├── config.sh           # Compose 项目名、端口提示及客户端端口
│   │   ├── *-cluster.sh        # 启动、状态、停止
│   │   ├── hive-cli.sh / spark-shell.sh
│   │   ├── hive-entrypoint.sh
│   │   ├── secrets/            # Compose 密码文件及学习环境示例
│   │   ├── jars/               # Compose 挂载的 JDBC 驱动
│   │   └── data/ / logs/       # 本地文件预留目录；服务持久化使用 Docker 卷
│   └── swarm/
│       ├── README.md
│       ├── cluster.example.json
│       ├── cluster.sh          # 构建、推送、部署、状态与客户端
│       ├── render.py           # 根据节点配置生成 stack 与 XML
│       └── smoke-test.sh       # 真实服务和作业验收
├── config/
│   ├── hadoop/                # 原生 Hadoop XML 基础配置
│   └── hive/                  # Compose、Metastore、Server、Client 的 XML
├── images/                    # 镜像构建文件与公共启动脚本
│   ├── common/                # XML 配置复制、依赖等待与启动入口
│   ├── hive/
│   └── spark/
├── tests/
│   ├── config/                # XML、启动和持久化保护测试
│   └── swarm/                 # 拓扑渲染与镜像启动回归测试
├── .github/workflows/          # 自动验证及可选服务验收
└── LICENSE
```

部署专用配置放在对应的 `deployments/<方式>/` 下；共享配置、镜像构建和测试在仓库级目录维护。
本地 Swarm 节点配置 `deployments/swarm/cluster.json`、生成目录 `deployments/swarm/build/` 不纳入版本控制。

## 快速开始

以下命令从仓库根目录执行，详细准备步骤见对应部署指南。

单机 Compose：

```bash
./deployments/compose/start-cluster.sh
./deployments/compose/status-cluster.sh
./deployments/compose/hive-cli.sh
./deployments/compose/spark-shell.sh
./deployments/compose/stop-cluster.sh
```

多机 Swarm：

```bash
cp deployments/swarm/cluster.example.json deployments/swarm/cluster.json
# 按 Swarm 部署指南配置节点、镜像仓库并创建 PostgreSQL Secret
./deployments/swarm/cluster.sh render
./deployments/swarm/cluster.sh build
./deployments/swarm/cluster.sh push
./deployments/swarm/cluster.sh deploy
./deployments/swarm/cluster.sh status
./deployments/swarm/smoke-test.sh
```

## XML 配置

Hadoop 与 Hive 的配置以 XML 文件为主要来源，Compose 与 Swarm 共用 `config/hadoop/`。
Swarm 将基础 XML、`deployments/swarm/overrides/` 和节点清单合并，按服务生成完整配置，
通过 configs 分发；Compose 只读挂载基础 XML。启动入口将文件复制到服务的配置目录，
直接启动组件，不再调用 BDE 的环境变量转 XML 入口。

环境变量保留给服务角色、依赖等待和 Spark 启动参数。数据库密码通过 Secret 文件读取，
仅在启动时替换 Hive XML 中的密码占位符。配置来源、优先级与迁移细节见 [配置指南](config/README.md)。
修改 Swarm 派生镜像入口后，需要使用新 `image_tag` 重新构建并推送镜像。

## 从旧目录结构迁移

原根目录 Compose 文件和脚本已移至 `deployments/compose/`，原 `swarm/` 入口已移至 `deployments/swarm/`。
请更新本地命令、自动化和外部脚本中的路径。原 `hadoop.env` 已迁移为 `config/hadoop/*.xml`，配置属性直接使用 Hadoop 原生名称。
本地 Swarm 的 `cluster.json` 与 `build/` 也应位于新的部署目录。

Compose 脚本默认沿用 `deploy-hadoop-spark-hive` 项目名，保留原默认部署的数据卷和网络身份。
如果原部署使用了自定义项目名，通过 `COMPOSE_PROJECT_NAME` 指定原值；
直接运行 Compose 命令时也要显式指定项目名，详见 [Compose 部署指南](deployments/compose/README.md)。
Swarm 的 stack、服务及数据卷名称继续由节点配置决定。目录调整不会迁移 Compose 与 Swarm 之间的数据。

## 验证

待测场景、验收标准与结果记录见 [XML 改造测试清单](docs/XML-MIGRATION-TESTS.md)。

```bash
python3 -m unittest discover -s tests -v
python3 deployments/swarm/render.py deployments/swarm/cluster.example.json
docker stack config -c deployments/swarm/build/stack.json
docker-compose -p deploy-hadoop-spark-hive -f deployments/compose/docker-compose.yml config
```

以上命令验证本地配置和启动逻辑；实际服务协作及作业执行使用 Swarm 的 `smoke-test.sh` 验收。

## License

[MIT](LICENSE)

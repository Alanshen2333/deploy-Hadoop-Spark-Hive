# Hadoop 与 Hive XML 配置

配置属性使用 Hadoop / Hive 原生名称，以 XML 作为主要配置源。
原来的 `hadoop.env` 和 Compose 的 `spark-hive-site.xml` 已移除；`CORE_CONF_*`、
`HDFS_CONF_*`、`YARN_CONF_*`、`MAPRED_CONF_*`、`HIVE_SITE_CONF_*` 不再作为部署配置接口。

## 文件职责

| 路径 | 内容 | 使用者 |
| --- | --- | --- |
| `hadoop/core-site.xml` | 文件系统入口、代理用户、压缩等 | 所有 Hadoop / Hive / Spark 服务 |
| `hadoop/hdfs-site.xml` | HDFS 行为、数据目录、绑定地址 | 所有 Hadoop / Hive / Spark 服务 |
| `hadoop/yarn-site.xml` | YARN 调度、资源、Timeline 持久化 | 所有 Hadoop / Hive / Spark 服务 |
| `hadoop/mapred-site.xml` | MapReduce 运行与作业参数 | 所有 Hadoop / Hive / Spark 服务 |
| `hive/compose/hive-site.xml` | 单机 JDBC Metastore | Compose 的 Hive 和 Spark |
| `hive/metastore/hive-site.xml` | 独立 Metastore 与 PostgreSQL 连接 | Swarm Hive Metastore |
| `hive/server/hive-site.xml` | Thrift Metastore、HiveServer2 参数 | Swarm HiveServer2 |
| `hive/client/hive-site.xml` | Thrift Metastore 客户端 | Swarm Spark 及临时客户端 |

基础 Hadoop XML 保留原 Compose 的资源默认值，并显式维护之前由 BDE 入口或镜像环境变量补充的
NameNode / DataNode 数据目录、服务绑定地址、DataNode hostname 解析及 Timeline 持久化目录。

## 配置优先级与交付

Compose 直接使用基础 Hadoop XML。Swarm 按以下顺序合并同名属性，后者覆盖前者：

1. `config/hadoop/*.xml`。
2. `deployments/swarm/overrides/*.xml`：Swarm 的 MapReduce 默认资源、YARN 本地目录等。
3. `cluster.json`：HDFS 副本数、YARN 内存/CPU 与调度上限。
4. 每个工作服务的稳定 hostname：DataNode / NodeManager 使用各自的完整 XML。

合并时拒绝单个源文件内的重复属性。每个最终 XML 中的属性只出现一次，保留注释及 `description` / `final` 等元信息。
部署覆盖在交付 XML 前完成；`final` 控制交付后 Hadoop 再加载资源时的覆盖行为。
Swarm 生成文件位于 `deployments/swarm/build/`，不要直接修改生成文件。

Compose 只读挂载仓库配置；Swarm 用内容版本化的 configs 分发 XML 和 Hadoop 公共入口。
服务启动时将只读文件复制到 `/etc/hadoop`、`/opt/hive/conf` 或 `/spark/conf`，
随后直接执行 Hadoop / Hive / Spark 命令，跳过 BDE 的环境变量转 XML 入口。
临时 Hadoop 客户端直接读取挂载目录，使用 `HADOOP_CONF_DIR` 指定路径。

环境变量仍用于容器层的项目名、服务角色、依赖等待、配置路径和 Spark 启动参数。
BDE 镜像可能保留自身的 `*_CONF_*` 默认环境变量，但项目入口不读取它们。

## 密码

Hive 的 JDBC 模板使用 `@@POSTGRES_PASSWORD@@` 占位符，启动时从 Secret 文件读取密码，
进行 XML 转义后生成权限 0600 的配置。模板不执行 shell 替换，密码不通过环境变量或日志传递。
Swarm 仅 Metastore 接收数据库密码；Compose 的 Hive 和 Spark 保持直接 JDBC 连接，使用同一个文件 Secret。

Compose 默认密码文件是学习环境示例 `deployments/compose/secrets/postgres_password.example`，
内容沿用原来的 `hive`。自定义文件应放在未跟踪的 `deployments/compose/secrets/` 下，
通过宿主机 `POSTGRES_PASSWORD_FILE` 指定。已有数据库卷应继续使用原密码，替换 Secret 不会轮换数据库密码。

## 持久化与迁移

保留现有服务、Docker 卷、Swarm stack 和 Compose 默认项目名。
NameNode 数据目录从 XML 读取，只支持本方案当前使用的一个绝对本地目录。
目录含 `current/VERSION` 时直接启动；新建空目录可初始化；非空但无标记的目录拒绝自动格式化。
修改 XML 中的数据目录时还需同步 Docker 卷挂载，不能通过只修改 XML 来迁移持久数据。

Compose 配置修改后应重新创建受影响容器，使启动入口复制新的配置。
Swarm 修改 XML 后重新部署；修改 Hive / Spark 镜像入口后需用新 `image_tag` 构建并推送派生镜像。
已有环境变量配置应先迁移到对应 XML，原 `*_CONF_*` 设置不再生效。

## 验证

从仓库根目录运行：

```bash
python3 -m unittest discover -s tests -v
python3 deployments/swarm/render.py deployments/swarm/cluster.example.json
docker stack config -c deployments/swarm/build/stack.json
docker-compose -p deploy-hadoop-spark-hive -f deployments/compose/docker-compose.yml config
```

测试检查配置交付、节点身份、持久化保护、依赖失败、密码转义、XML 完整性及配置版本更新。
真实服务协作、网络连通性与作业执行仍需在目标集群运行 `deployments/swarm/smoke-test.sh`。

完整的真实服务、迁移、配置更新与失败保护测试见 [XML 改造测试清单](../docs/XML-MIGRATION-TESTS.md)。

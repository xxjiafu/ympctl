# ympctl 技术白皮书

**YMP 迁移平台命令行控制工具 —— 设计与实现**

版本：V1.0 ｜ 适用工具版本：v1.2.1 ｜ 2026 年 11 月

---

## 1 摘要

ympctl 是 YashanDB 迁移平台（YashanDB Migration Platform，下称 YMP）的命令行控制工具，基于 YMP OpenAPI（`yashan/*` REST 接口）实现迁移任务的全生命周期管理：任务触发、进度监控、日志跟踪、配置导入导出、数据校验差异对比（表级/行级/列级）与报告下载，并覆盖数据源管理、对象评估等辅助能力。

工具采用 Go 语言实现，纯标准库、零第三方依赖，交叉编译为单二进制文件分发（Windows / Linux x64 / Linux ARM64 / Linux ARMv7）。本文档阐述其设计目标、系统架构、关键技术决策、接口映射、质量保障体系与发布工程，供数据库迁移实施工程师、运维自动化工程师及后续维护者参考。

## 2 背景与问题陈述

YMP 平台通过 Web 向导完成 Oracle、MySQL、达梦等异构数据库到 YashanDB 的迁移评估、离线迁移与数据校验。向导模式适合一次性手工操作，但在以下场景存在明显瓶颈：

| 场景 | Web 向导的局限 |
| --- | --- |
| 重复性迁移（开发/测试多轮数据重置） | 每轮需手工走完向导流程，耗时且易漏步骤 |
| 无人值守迁移 | 无法在夜间窗口自动触发与等待完成 |
| 迁移流水线（迁移→校验→报告→放行） | 各环节割裂，无法用脚本串接与判废 |
| 差异排查 | 校验结果需逐层点击查看，缺少可直接归档的文本报告 |
| 多环境批量操作 | 无法批量遍历任务/数据源 |

ympctl 将上述能力收敛为一组可脚本化的命令，以**退出码契约**保证流水线可编程，以**人机双格式输出**（表格/键值 + `--json`）兼顾交互与机器消费。

## 3 设计目标与原则

1. **单二进制、零依赖**：纯 Go 标准库，无 cobra/viper 等框架，编译产物 8~9 MB，目标机无需安装运行时。
2. **与平台协议严格对齐**：所有行为以 YMP OpenAPI 实测为准（请求方法、必填参数、错误码语义），而非猜测 REST 惯例。
3. **可编程优先**：每个命令的退出码均有明确契约（成功/失败/中断），机器可判废；输出可选 `--json` 原始透传。
4. **安全默认**：密码不进入命令行历史（`--password-stdin`）、Token 文件最小权限、加密算法与平台前端逐字节一致且经标准向量校验。
5. **回归可重复**：集成回归不触发真实迁移、不修改业务数据、不修改账号凭证，可在生产环境随时执行。

## 4 系统架构

### 4.1 分层结构

```
┌───────────────────────────────────────────────────┐
│                运维工程师 / CI 流水线 / 定时任务        │
└────────────────────────┬──────────────────────────┘
                         │ 命令行参数
┌────────────────────────▼──────────────────────────┐
│  main.go            命令分发 / 参数重排 / 帮助       │
│  cmd_task.go        迁移任务（17 个子命令）          │
│  cmd_check.go       数据校验（15 个子命令）          │
│  cmd_ds.go          数据源（8 个子命令）            │  命令编排层
│  cmd_assess.go      对象评估（6 个子命令）          │
│  cmd_account.go     登录/状态/改密/加密             │
│  cmd_report.go      报告下载 / api 原始透传         │
├───────────────────────────────────────────────────┤
│  client.go          HTTP 客户端                    │
│   · 认证注入（Access-Token / Authorization 双头）    │  API 客户端层
│   · 统一错误模型（业务码优先于 HTTP 状态码）           │
│   · 下载类接口 JSON 错误体检测                      │
│   · 加密原语（SHA256 / AES-128-CBC）               │
│   · migrationTaskId / checkTaskId 解析             │
├───────────────────────────────────────────────────┤
│  output.go          展示层                         │
│   · 表格（CJK 宽度对齐）/ 键值树 / --json 透传       │  展示层
│   · 迁移量 KB→MB 换算、差异类型中文化                │
└────────────────────────┬──────────────────────────┘
                         │ HTTP REST
┌────────────────────────▼──────────────────────────┐
│              YMP 平台 OpenAPI（yashan/*）           │
│   认证 / 任务 / 数据源 / 评估 / 校验 / 报告 / 平台     │
└───────────────────────────────────────────────────┘
```

### 4.2 数据流示例（迁移触发）

```
task start 1
  → GET  yashan/task/getTaskBaseInfo/1            解析 migrationTask.id
  → GET  yashan/migration/offlineTask/config      取已保存的迁移配置
  → 合并 {taskId, migrationTaskId, needAssessment, forceCreate}
  → POST yashan/migration/startTask               提交完整配置
  → GET  yashan/task/getTaskList（watch 轮询）     状态机驱动直至终态
```

## 5 关键技术设计

### 5.1 认证与会话管理

- 登录请求 `POST yashan/user/login`，请求体 `{userName, password}`，其中 `password` 为**SHA-256 十六进制摘要**（平台前端约定，明文不出网）。
- 登录成功返回 JWT（`YMP-00000` / `result.token`），后续请求同时携带 `Access-Token` 与 `Authorization` 双头。
- Token 以 JSON 配置存储于 `~/.ympctl.json`（文件权限 0600），Python 历史版本与 Go 版**配置互通**，可无缝切换。
- 未授权请求返回 HTTP 401；客户端检测到 401 统一给出可操作的提示（执行 `login`）。配置了 `YMP_USER`/`YMP_PASSWORD` 环境变量（或 `--save-password`）时自动重新登录，适配无人值守场景。

### 5.2 参数解析与重排算法

Go 标准库 `flag` 在遇到首个位置参数后即停止解析，而运维习惯是 `ympctl task start 1 --json`（选项后置）。ympctl 实现了**基于白名单的参数重排**：

1. 维护「需取值选项」白名单（`--data/--lines/--output/-o/-m/--blacklist/...`）；
2. 线性扫描参数：遇到白名单选项则将其后一个 token 归为选项值；`--k=v` 形式自包含；其余 `-` 开头 token 归为布尔选项；非选项 token 归为位置参数；
3. 输出「选项序列 + 位置参数序列」交由 `flag` 解析。

该机制使**选项位置无关**，同时保留了标准 flag 的语义（`--k=v`、布尔选项）。工程实践中的两个教训已固化为测试用例：

- 白名单遗漏导致选项值被误判为位置参数（`--blacklist` 曾踩坑，实际请求了错误的资源 ID）；
- flag 指针**不得绑定到命名返回值**——`Parse` 发生在构造函数返回之后，写入的是失效栈帧，导致 `--json/--url/--timeout` 静默失效。现统一改用选项结构体（`envOpts`）取址。

### 5.3 HTTP 客户端与统一错误模型

| 层级 | 行为 |
| --- | --- |
| 成功 | 响应体 `code == "YMP-00000"`，剥离 `result` 返回调用方 |
| 业务错误 | `code != YMP-00000`（如 `YMP-01001` 凭证错误、`YMP-03000` 任务不存在、`YMP-02000` 数据源不可达），直接透出错误码与 message |
| HTTP 401 | 统一提示重新登录 |
| HTTP 4xx/5xx | **优先解析响应体中的 YMP 业务码**（部分接口以 HTTP 404 返回业务错误 `YMP-00005`），无业务码时回退 HTTP 状态码 |
| 空响应 | 视为成功（部分写操作返回空体） |

**下载类接口防护**：报告/日志下载出错时，服务端可能返回 JSON 错误体（HTTP 200）。客户端在写盘前嗅探响应首字节，若为 `{` 且携带非成功业务码，则中止落盘并报错，避免产生损坏的 zip 文件。

### 5.4 数据加密体系

| 用途 | 算法 | 说明 |
| --- | --- | --- |
| 登录口令 | SHA-256 → Hex | 平台前端约定，服务端比对摘要 |
| 数据源密码 | AES-128-CBC + ZeroPadding + Base64 | key 与 IV 均为 16 字节约定值；与 YMP 前端 crypto-js 行为**逐字节一致** |

ZeroPadding 的实现细节：crypto-js 在数据长度恰为块大小整数倍时**仍追加整块零**，与常见「仅补齐」实现不同；ympctl 按前端行为实现并经两类向量验证：

- NIST FIPS-197 AES-128 ECB 标准向量；
- NIST SP 800-38A CBC 标准向量；
- 与 Python 参考实现的密文逐字节对照（回归测试固化）。

### 5.5 迁移任务触发机制

直接以最小参数调用 `startTask` 会触发服务端空指针（`MigrationTaskConfig.targetDataSourceId is null`）：服务端以请求体为依据处理启动，缺配置即无法执行。ympctl 的触发流程因此设计为**配置合并**：

1. 解析 `migrationTaskId`（显式 `-m` 或从 `getTaskBaseInfo.migrationTask` 推断）；
2. `GET yashan/migration/offlineTask/config` 取回该任务已保存的完整迁移配置；
3. 合并 `{taskId, migrationTaskId, needAssessment, forceCreate}` 后整体提交 `startTask`。

该设计使「向导中保存过的任务」均可从命令行一键重跑，`--data` 亦支持完全自定义请求体。

**任务操作统一使用 POST**：实测服务端对 `stopTaskById` 等端点不支持 `DELETE` 方法（连接直接重置），ympctl 以 POST + JSON 数字请求体实现，并对该协议事实在文档中显式说明。

### 5.6 校验差异的三级模型

YMP 校验结果呈三级组织，ympctl 一一映射为命令：

| 级别 | OpenAPI | 命令 | 关键字段 |
| --- | --- | --- | --- |
| 任务级 | `check/status/statistics/{checkTaskId}` | `check statistics` | status、result（0=一致/1=不一致）、rowProgressInfo（行进度） |
| 表级 | `check/status/detail?checkTaskId=` | `check tables` | tableDetail[].id（即 checkObjId）、checkResult、diffTypes、源/目标行数 |
| 单表汇总 | `check/status/result/{checkObjId}` | `check result` | **diffColNames（不一致列名）**、same、diffRows、五类差异计数、主键名 |
| 行级 | `check/status/resultDetail?checkObjId=` | `check rows` | resultType、sourcePk/targetPk、sourceData/targetData、diffColName |

注意表级与行级使用**两套差异枚举**（易混淆点）：

- 表级 `diffTypes`：1=数据不一致，2=目标表不存在，3=结构不一致，9=源表不存在；
- 行级 `resultType`：0=冗余（目标端多出），1=缺失（目标端缺少），2=差异，4=非法值，5=校验键为NULL（来源：YMP 校验报告的官方映射）。

### 5.7 SHOW DIFF 对比报告

`check showdiff` 以运维人员熟悉的对比报告格式输出，可直接归档或被既有运维工具以文本方式消费：

```
====SHOW DIFF=====
数据校验对比结果
[NO] APPUSER.EMPLOYEE == APPUSER.EMPLOYEE
    行数: 源=2 目标=3 差异行=1
    分类: 冗余(目标多出)=1
    不一致列: -
    [冗余] 源=- / 目标=ccc 差异列=-
====CHECK_COMPARE_END=====
```

`[NO]` 标记不一致表（`--all` 时一致表以 `[OK]` 输出）；`--detail` 追加行数、五类差异计数、不一致列名；`--rows N` 附行级差异样例。**存在差异时退出码为 1**，流水线可直接据此判废。

### 5.8 watch 机制与退出码契约

| 命令 | 轮询对象 | 终态集合 | 退出码 |
| --- | --- | --- | --- |
| `task watch` | getTaskList（状态机）+ offlineTask/progress | 8 停止 / 9 完成 / 22 校验完成 / 23 失败 / 24 停止 / 42 修复完成 / 43 修复失败 / 45 修复取消 / 48 复验完成 / 49 复验失败 / 51 复验取消 / 1804 增量停止 | 成功终态=0，失败/停止=1，中断=130 |
| `check watch` | check/status/statistics | 22 / 23 / 24 / 42 / 43 / 45 / 48 / 49 / 51 | result∈{0,4} 且状态成功=0，否则=1 |
| `task log --follow` | task/log | — | 按 `logOffset` 差量拉取新行并续写输出 |

`logLine` 参数语义为「读取尾部 N 行」，响应携带 `logOffset`（总行数）；follow 模式据此做增量拉取，避免重复输出。**过渡态（等待/运行中/取消中）不视为终态**——该判定规则曾在早期版本误将「运行中」当终态导致提前退出，现已在回归测试中固化。

### 5.9 迁移量单位语义

YMP 的 `dataTotalSize/dataMigrationSize` 及进度接口的 total/success 计数单位为 **KB**（对应 Oracle 源端段大小），**不是行数**——一张 2 行的表亦会报告 64KB（最小初始 extent）。ympctl 在展示层统一换算为 MB 并附原始 KB，消除运维误读。

## 6 命令与 OpenAPI 映射

| 命令 | 方法与端点 |
| --- | --- |
| login / logout | POST `yashan/user/login` / `yashan/user/logout` |
| status | GET `yashan/platform/getInfo`、`yashan/user/info` |
| task list / show | GET `yashan/task/getTaskList`、`yashan/task/getTaskBaseInfo/{id}` |
| task start | GET `yashan/migration/offlineTask/config` + POST `yashan/migration/startTask` |
| task stop/pause/resume | POST `yashan/task/{stopTaskById,suspendTaskById,recoverTaskById}`（body 为 JSON 数字） |
| task delete | POST `yashan/task/deleteTaskById/{id}` |
| task progress / metrics / objects | GET `yashan/migration/offlineTask/{progress,metrics,objects}`（metrics 需 `lastHours`） |
| task log / log-dl | GET `yashan/migration/task/{log,log/download}` |
| task save / precheck | POST `yashan/migration/{saveTask,preCheck}` |
| task export/import-config | POST `yashan/migration/config/{export,import}`（export 需 `moduleTypes`） |
| task watch | GET `yashan/task/getTaskList` + `yashan/migration/offlineTask/progress`（轮询） |
| ds list / show | GET `yashan/dataSource/getDatasourceList` |
| ds add / refresh / test | POST `yashan/dataSource/{addDatasource,refreshDatasource,testConnection}`（password 自动加密） |
| ds delete / schemas / types | POST `…/deleteDatasource/{id}`；GET `…/getSchemas[WithBlackList]/{id}`；GET `…/getConvertDBType/` |
| assess * | GET/POST `yashan/objAssessmentTask/*` |
| check start / stop | POST `yashan/check/task/{start,cancel}/{checkTaskId}` |
| check statistics / result / tables / rows | GET `yashan/check/status/{statistics,result,detail,resultDetail}` |
| check showdiff | GET `yashan/check/status/detail` + `result/{id}` + `resultDetail`（组合渲染） |
| check log / log-dl | GET `yashan/check/status/log/{view,download}`（`logLine` 必填） |
| check save / repair / revalidate | POST `yashan/check/task/{save,repair,revalidate}` |
| report migration / check | GET `yashan/reportDownload/{migrationReport,getCheckTaskReport/{id}}` |
| api（透传） | 任意 `yashan/*` 端点，GET/POST/PUT/DELETE |

## 7 质量保障体系

### 7.1 单元测试（`go test ./...`）

- 加密正确性：NIST FIPS-197（ECB）、SP 800-38A（CBC）标准向量；与 Python 参考实现的密文对照；
- 参数重排算法：选项后置、取值选项、`--k=v`、stdin 标记等典型形态；
- 展示层：KB→MB 换算、行级差异 JSON 数组解析、状态标签映射；
- ID/数字解析的容错语义。

### 7.2 集成回归（`regression.sh`，88 项）

对真实 YMP 实例执行，覆盖 7 大模块：离线基础（5）、登录与状态（4）、任务模块（27）、数据源（10）、评估（3）、校验（25）、报告与透传（9）、登出恢复（3）。断言维度包括退出码、输出子串、JSON 结构、下载产物大小与格式（ELF/ZIP）。

**动态自洽断言**：校验差异数据会随业务侧重新同步而变化，回归对差异类断言不做硬编码，而是「断言时刻重新探测状态 → 校验输出与状态自洽」（如 `showdiff` 退出码必须等于当时是否存在差异），使回归可在数据频繁变动的环境中稳定重复。

**安全约束**：回归不触发真实迁移（`task start` 仅验证错误路径）、不修改账号凭证、不改动业务数据，可在生产实例随时执行。

### 7.3 缺陷收敛记录

| 版本 | 缺陷 | 根因 |
| --- | --- | --- |
| v1.2.0 | check/ds/assess 组 `--json/--url/--timeout` 全部失效 | flag 指针绑定到命名返回值，Parse 写入失效栈帧 |
| v1.2.0 | `--blacklist` 取值错误 | 值选项未登记白名单，重排后选项值被误判为位置参数 |
| v1.2.0 | `check watch` 提前退出 | 过渡态（等待/运行中）被误判为终态 |
| v1.2.1 | `check log` 报 YMP-99999 | `logLine` 为必填参数，缺省未携带 |
| v0.x→v1.2.1 | HTTP 4xx 未透出业务码 | 已改为优先解析响应体 YMP 错误码 |

## 8 安全性设计

- **凭证最小暴露**：`--password-stdin` 支持管道输入，避免口令进入 shell 历史；`--save-password` 明文落盘仅限自动化场景并在输出中显式告警。
- **Token 存储**：`~/.ympctl.json` 以 0600 权限写入；`logout` 即清除。
- **加密材料**：数据源密码加密的 key/IV 为 YMP 前端公开协议约定，ympctl 不做额外二次发明；登录摘要化传输，明文口令不出本机。
- **错误信息**：不回显请求体中的口令字段；业务错误透传服务端 message 便于定位。
- **破坏性操作防呆**：`task delete`/`ds delete` 默认交互确认（`--yes` 跳过）；回归脚本自身不执行任何破坏性写操作。

## 9 发布工程

### 9.1 交叉编译矩阵

| 目标 | GOOS / GOARCH | 产物大小（约） |
| --- | --- | --- |
| Windows x64 | windows / amd64 | 9.3 MB |
| Linux x64 | linux / amd64 | 9.2 MB |
| Linux ARM64（飞腾/鲲鹏等） | linux / arm64 | 8.5 MB |
| Linux ARMv7 | linux / arm + GOARM=7 | 8.9 MB |

统一使用 `-trimpath` 消除构建路径信息；产物以 ELF/PE 头校验架构正确性。

### 9.2 发布流程

本地 tag（annotated）→ 推送分支与 tag → GitHub Release 附四平台二进制；网络受限时可通过 GitHub Git Data API（blob/tree/commit/refs 序列）完成等价推送，提交 SHA 与本地完全一致。版本语义：功能对齐期 v0.x → Go 版本 v1.1.0 → 仓库 Go 专用化 v1.2.0 → 缺陷修复 v1.2.1。

### 9.3 版本历史

| 版本 | 里程碑 |
| --- | --- |
| v0.1~v1.0（Python 时期） | 基础版 → 监控增强（MB 换算）→ 密码加密 → 校验差异明细；Python 实现已下架，代码见 git 历史 |
| v1.1.0 | 新增 Go 实现，与 Python 版功能对齐 |
| v1.2.0 | 仓库重构为 Go 专用（Go 提升至仓库根，模块 `github.com/xxjiafu/ympctl`） |
| v1.2.1 | 修复 `check log` 必填参数缺省报错 |

## 10 典型应用场景

### 10.1 迁移—校验—报告流水线

```bash
#!/usr/bin/env bash
set -e
ympctl task start 1                       # 触发迁移（合并已保存配置）
ympctl task watch 1                       # 等待迁移完成（退出码 0=成功）
ympctl check start 2                      # 触发数据校验
ympctl check watch 2 || { echo "校验未通过"; exit 1; }
ympctl check showdiff 2 --detail > diff_report_$(date +%F).txt
[ $? -ne 0 ] && echo "存在差异，详情见报告"
ympctl report check 1 -o check_report.zip # 归档校验报告
```

### 10.2 迁移进度巡检

```bash
ympctl task list                          # 全局概览（状态中文化）
ympctl task progress 1                    # 迁移量（MB）
ympctl task log 1 --follow                # 实时日志跟踪
ympctl task metrics 1 --hours 2           # 吞吐指标
```

### 10.3 环境巡检与批量操作

```bash
ympctl status                             # 平台版本与登录状态
ympctl ds list                            # 数据源清单
ympctl check list --all                   # 校验任务全景
ympctl api GET yashan/task/getTaskList --query pageNum=1,pageSize=50   # 任意接口透传
```

## 11 附录

### 附录 A：迁移任务状态（taskStatus）常用值

| 值 | 含义 | 值 | 含义 |
| --- | --- | --- | --- |
| 0/1/2/3 | 评估初始化/运行中/已停止/完成 | 14/15/16 | 迁移取消中/暂停中/已暂停 |
| 4 | 迁移待配置 | 20~25 | 校验等待/运行中/完成/失败/已停止/停止中 |
| 5/6/7 | 元数据迁移一/数据迁移/元数据迁移二 | 26 | 任务创建成功 |
| 8/9 | 迁移已停止/迁移完成 | 40~51 | 修复与复验各状态 |
| 11/12 | 迁移运行中/获取迁移对象中 | 53/54 | 哈希比对中/哈希确认中 |
| 13/10 | 评估刷新已取消/评估刷新中 | 1800~1804 | 增量迁移族状态 |

### 附录 B：环境变量

| 变量 | 作用 |
| --- | --- |
| `YMP_URL` | YMP 地址（优先级：命令行 > 环境变量 > 配置文件 > 默认） |
| `YMP_USER` / `YMP_PASSWORD` | 自动重登凭证（Token 失效时使用） |
| `YMP_TOKEN` | 直接指定 Token（覆盖配置文件） |

### 附录 C：退出码

| 退出码 | 含义 |
| --- | --- |
| 0 | 成功；`task watch`/`check watch`/`check showdiff` 表示成功终态/校验通过/无差异 |
| 1 | 业务失败、存在差异、参数缺失、连接失败、校验未通过 |
| 2 | 用法错误（未知命令/非法参数） |
| 130 | 用户中断（Ctrl+C） |

### 附录 D：已知平台限制

- 个别前端引用的接口在部分 YMP 版本后端不存在（返回 `YMP-00005`，如 `getHistoryLog`、`getConvertDBType`），ympctl 如实透出错误；
- 迁移量字段单位为 KB（Oracle 段大小），非行数——工具层已换算并在输出中标注原始值；
- `stopTaskById` 等写操作对不存在的任务 ID 可能静默成功，属服务端行为。

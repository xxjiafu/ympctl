# ympctl 技术白皮书

**YMP 迁移平台命令行控制工具 —— 核心能力说明**

版本：V1.1 ｜ 适用工具版本：v1.2.1 ｜ 2026 年 11 月

---

## 1 概述

ympctl 是 YashanDB 迁移平台（YashanDB Migration Platform，下称 YMP）的命令行控制工具。它基于 YMP OpenAPI，将平台 Web 向导中的迁移任务操作收敛为一组可脚本化的命令，覆盖迁移任务的**触发、监控、日志跟踪、配置复用、数据校验差异对比与报告归档**，并支持数据源管理与对象评估。

工具以单个可执行文件交付（Windows / Linux x64 / Linux ARM64 / Linux ARMv7），目标环境无需安装任何运行时依赖，可直接嵌入迁移作业脚本、定时巡检任务与自动化流水线。

## 2 解决的问题

| 迁移场景 | ympctl 能力 |
| --- | --- |
| 多轮数据重置的重复迁移 | 一条命令触发已配置任务重跑 |
| 夜间窗口无人值守迁移 | 触发后自动等待至终态，退出码标识成败 |
| 迁移 → 校验 → 报告流水线 | 全环节命令化，退出码判废，脚本可直接串接 |
| 校验差异排查与归档 | 表级/行级/列级差异明细，生成可归档的对比报告 |
| 多环境批量巡检 | 任务/数据源批量查询，任意平台接口透传 |

## 3 总体架构

```
┌───────────────────────────────────────────────┐
│        运维工程师 / CI 流水线 / 定时巡检任务      │
└──────────────────────┬────────────────────────┘
                       │ 命令行
┌──────────────────────▼────────────────────────┐
│  命令层（按迁移生命周期组织）                     │
│   账号    login / logout / status / passwd     │
│   任务    task …（触发/监控/日志/配置/等待）      │
│   数据源  ds …（增删改查/连通性测试）             │
│   评估    assess …                             │
│   校验    check …（含差异明细与对比报告）         │
│   报告    report …（迁移/校验报告下载）          │
├───────────────────────────────────────────────┤
│  API 客户端层                                   │
│   · Token 认证与会话保持                         │
│   · 统一错误解析（业务错误码优先）                 │
│   · 凭证加密（登录摘要 / 数据源密码密文）          │
│   · 任务 ID 解析、配置合并                       │
├───────────────────────────────────────────────┤
│  展示层                                        │
│   · 交互模式：中文表格 / 键值树                   │
│   · 脚本模式：--json 原始输出                    │
└──────────────────────┬────────────────────────┘
                       │ HTTPS REST
┌──────────────────────▼────────────────────────┐
│        YMP 平台 OpenAPI（yashan/*）             │
└───────────────────────────────────────────────┘
```

## 4 核心能力

### 4.1 迁移任务触发

向导中保存过的迁移任务，可从命令行一键重跑：

```bash
ympctl task start 1
```

工具自动完成三步：解析任务对应的迁移子任务 ID → 读取该任务已保存的完整迁移配置 → 携带配置提交启动请求。因此无需人工重新填写向导参数；亦支持 `--data` 传入自定义启动请求，实现完全受控的触发。

### 4.2 迁移监控与等待

| 命令 | 能力 |
| --- | --- |
| `task list` | 任务全景，状态中文化（含源库类型、进度、时间） |
| `task show` | 单任务详情：源/目标数据源、迁移子任务、校验任务 |
| `task progress` | 迁移进度与迁移量（自动换算为 MB 展示） |
| `task objects` | 迁移对象清单：每张表的迁移量、进度、起止时间 |
| `task metrics` | 吞吐指标（BPS/RPS，可指定统计时段） |
| `task log --follow` | 实时日志跟踪（增量拉取，不重复输出） |
| `task log-dl` | 日志打包下载，便于归档与远程分析 |
| `task watch` | **轮询等待至终态**：迁移成功退出码 0，失败/停止为 1，供脚本判废 |

### 4.3 迁移配置复用

```bash
ympctl task export-config 1 -o template.json    # 导出已验证的迁移配置
ympctl task import-config -m 2 -f template.json # 导入到新任务
ympctl task save --data @config.json            # 保存/更新配置
ympctl task precheck --data @config.json        # 迁移前检查
```

已验证的迁移配置可以导出为 JSON 模板，在新环境中导入复用，避免重复配置；配置亦可作为备份归档。

### 4.4 数据校验差异对比（三级明细）

YMP 校验结果按「任务 → 表 → 行」三级组织，ympctl 提供逐级下钻命令：

| 命令 | 内容 |
| --- | --- |
| `check statistics` | 总体结论（一致/不一致）、行进度、吞吐 |
| `check tables` | 表级结果：哪些表不一致、差异类型、源/目标行数 |
| `check result` | 单表汇总：**不一致列名**、五类差异计数（冗余/缺失/差异/非法值/校验键为NULL） |
| `check rows` | 行级明细：差异类型、源/目标主键与数据 |
| `check showdiff` | **对比报告**：对老运维工具格式的兼容输出（见下） |
| `check start / watch / stop` | 触发重跑 / 等待至终态 / 取消 |

`check showdiff` 输出可直接归档或被既有运维工具消费：

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

存在差异时退出码为 1，流水线可直接据此放行或判废。

### 4.5 校验任务 ID 互通

校验相关命令的 ID 参数**同时接受主任务 ID 与校验子任务 ID**，工具自动解析，避免两类 ID 混用导致的误操作；`check list` 同时展示两者。

### 4.6 报告归档

```bash
ympctl report migration 1 -o migration_report.zip   # 迁移报告
ympctl report check 1 -o check_report.zip           # 校验报告
```

一键下载平台生成的正式报告包，用于交付归档。下载失败时工具会识别平台错误并明确报错，不会产生损坏文件。

### 4.7 数据源管理

增删改查、连通性测试、Schema 枚举、目标库类型查询一应俱全。新增/测试时**密码自动按平台算法加密后提交**，命令行中的明文不出本机。

### 4.8 平台接口透传

```bash
ympctl api GET yashan/task/getTaskList --query pageNum=1,pageSize=50
```

对未封装的平台接口，`api` 命令提供原始透传（GET/POST/PUT/DELETE），保证工具能力可随平台接口扩展而即时可用，无需等待版本更新。

## 5 使用契约

### 5.1 退出码

| 退出码 | 含义 |
| --- | --- |
| 0 | 成功；`task watch` 表示迁移成功终态，`check watch`/`showdiff` 表示校验通过/无差异 |
| 1 | 业务失败、存在差异、连接失败等可判废情形 |
| 2 | 用法错误（未知命令/非法参数） |
| 130 | 用户中断（Ctrl+C） |

流水线示例：

```bash
#!/usr/bin/env bash
set -e
ympctl task start 1
ympctl task watch 1                       # 迁移成功才继续
ympctl check start 2
ympctl check watch 2                      # 校验通过才继续
ympctl check showdiff 2 --detail > diff_$(date +%F).txt
ympctl report check 1 -o check_report.zip # 归档报告
```

### 5.2 输出格式

- 交互模式：中文表格与键值树，直接可读；
- 脚本模式：几乎所有查询命令支持 `--json`，输出平台原始 JSON，便于程序消费。

### 5.3 配置与凭证

| 项 | 说明 |
| --- | --- |
| 配置文件 | `~/.ympctl.json`，保存地址、用户名与 Token |
| 环境变量 | `YMP_URL` / `YMP_USER` / `YMP_PASSWORD` / `YMP_TOKEN`（适配无人值守，Token 失效自动重登） |
| 密码输入 | `--password-stdin` 管道输入，避免口令进入命令历史 |
| 破坏性操作 | `task delete` / `ds delete` 默认二次确认，`--yes` 跳过 |

## 6 安装与部署

### 6.1 平台支持

| 产物 | 适用环境 |
| --- | --- |
| windows-amd64.exe | Windows Server / 桌面系统 |
| linux-amd64 | 主流 x86_64 Linux |
| linux-arm64 | ARM64 服务器（飞腾、鲲鹏等） |
| linux-armv7 | ARMv7 32 位边缘设备 |

各产物均可在 GitHub Releases 页面直接下载，Linux 下 `chmod +x` 后即用；亦可自行构建：`go build .`（Go 1.21+）。

### 6.2 上手三步

```bash
./ympctl login --url http://<ymp-host>:8090 --user admin   # 1. 登录
./ympctl task list                                         # 2. 查看任务
./ympctl task watch 1                                      # 3. 触发并等待
```

## 7 与 YMP 平台的适配说明

| 事项 | 说明 |
| --- | --- |
| 迁移量单位 | 平台的迁移量字段单位为 KB（对应源端 Oracle 段大小），非行数；工具已统一换算为 MB 并附原始值，避免误读 |
| 任务状态 | 支持平台全量状态枚举（评估、迁移、校验、修复、复验、增量迁移各阶段）并中文化展示 |
| 数据校验差异枚举 | 表级与行级采用两套枚举体系，工具已分别按平台官方映射翻译（表级：数据不一致/目标表不存在/结构不一致/源表不存在；行级：冗余/缺失/差异/非法值/校验键为NULL） |
| 接口版本差异 | 个别平台接口在特定版本不存在时，工具如实透出平台错误码 |
| 凭证互通 | 配置文件格式稳定，多版本工具间可无缝沿用既有登录态 |

## 8 常见问题

**Q：任务触发后命令就返回了吗？**
是。触发命令仅提交请求；如需等待迁移结束，请使用 `task watch`，脚本可按退出码判断成败。

**Q：为什么迁移量显示的数值和表行数对不上？**
迁移量按源端存储段大小（KB）统计，与行数无关；工具已换算为 MB 显示。行数请以 `check statistics` 的行进度为准。

**Q：校验发现不一致后如何定位具体数据？**
依次使用 `check tables`（定位表）→ `check result`（定位列）→ `check rows`（查看行数据），或直接 `check showdiff --detail --rows N` 一步生成完整差异报告。

**Q：如何让定时任务在 Token 过期后仍能工作？**
设置 `YMP_USER` / `YMP_PASSWORD` 环境变量，工具检测到登录失效会自动重新获取 Token。

**Q：平台新增了接口，工具未封装怎么办？**
使用 `api` 透传命令直接调用；透传能力保证工具不会因平台接口演进而不可用。

## 附录 A：命令速查

```
账号   login  logout  status  passwd  encrypt
任务   task list|show|start|stop|pause|resume|delete|progress|
            metrics|objects|log|log-dl|watch|save|precheck|
            export-config|import-config
数据源 ds list|show|add|refresh|test|delete|schemas|types
评估   assess history|situation|abstract|objects|execute|save
校验   check list|info|statistics|result|tables|showdiff|rows|
            start|stop|watch|log|log-dl|save|repair|revalidate
报告   report migration|check
透传   api GET|POST|DELETE|PUT <path> [--query k=v,..] [--data @f]
```

## 附录 B：迁移任务状态常用值

| 值 | 含义 | 值 | 含义 |
| --- | --- | --- | --- |
| 0~3 | 评估初始化/运行中/已停止/完成 | 20~25 | 校验等待/运行中/完成/失败/已停止/停止中 |
| 4 | 迁移待配置 | 26 | 任务创建成功 |
| 5~7 | 元数据迁移一/数据迁移/元数据迁移二 | 40~51 | 修复与复验各状态 |
| 8/9 | 迁移已停止/迁移完成 | 53/54 | 哈希比对中/哈希确认中 |
| 11/12 | 迁移运行中/获取迁移对象中 | 1800~1804 | 增量迁移族状态 |
| 14~16 | 迁移取消中/暂停中/已暂停 | | |

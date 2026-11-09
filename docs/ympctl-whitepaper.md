# ympctl 技术白皮书

**YMP 迁移平台命令行控制工具 —— 核心能力与运维实践**

版本：V1.2 ｜ 适用工具版本：v1.2.1 ｜ 2026 年 11 月

---

## 1 概述

ympctl 是 YashanDB 迁移平台（YMP）的命令行控制工具。它将迁移任务运维的日常动作——**触发、等待、看日志、查进度、比对差异、归档报告**——收敛为可脚本化的命令，覆盖迁移窗口值班、定时巡检、批量环境操作三类核心运维场景。

工具以单个可执行文件交付（Windows / Linux x64 / ARM64 / ARMv7），目标机**无需安装任何运行时**，放到跳板机即可使用，适合纳入堡垒机授权、Ansible 分发或 CI 流水线。

**运维定位一句话**：Web 向导负责"首次配置与复杂调整"，ympctl 负责"之后的一切重复操作"。

## 2 运维场景与命令对照

### 2.1 迁移窗口值班（最常用）

```bash
# ---- 割接窗口的完整操作序列 ----
ympctl task list                          # ① 确认任务清单与当前状态
ympctl task start 1                       # ② 触发迁移（自动带已保存配置）
ympctl task watch 1                       # ③ 等待结束：退出码 0=成功
ympctl task log 1 --follow                # ④ (另开终端)实时看日志排障
ympctl check start 2                      # ⑤ 触发数据校验
ympctl check watch 2                      # ⑥ 等待校验：退出码 0=数据一致
ympctl check showdiff 2 --detail > diff_$(date +%F).txt   # ⑦ 差异报告落盘
ympctl report check 1 -o check_report.zip # ⑧ 归档校验报告
```

③~⑥ 每步的退出码都是明确的成败信号，可直接写进割接操作单的检查框，无需人工盯屏幕判断。

### 2.2 定时巡检

```bash
# crontab 示例：每日 8 点巡检任务状态并落盘
0 8 * * * /opt/ympctl/ympctl task list --json >> /var/log/ymp/daily.json 2>&1
# Token 过期自动重登(需配置环境变量)，巡检不会因会话失效而中断
```

### 2.3 批量与多环境操作

```bash
ympctl status                             # 各环境平台版本一览
ympctl ds list                            # 数据源清单核对
ympctl check list --all                   # 校验任务全景
ympctl api GET yashan/task/getTaskList --query pageNum=1,pageSize=100
```

## 3 核心能力

### 3.1 任务触发与等待（自动化基石）

- `task start`：自动完成"解析迁移子任务 → 取已保存配置 → 提交启动"三步，向导保存过的任务可直接重跑；`--data` 亦可完全自定义请求体。
- `task watch`：轮询至终态自动退出。**成功终态（迁移完成/校验通过）=0，失败/停止 =1，Ctrl+C =130**——脚本判废的唯一依据，无需解析输出文本。
- `check watch`：校验终态判定在工具内完成（含修复/复验各状态），通过 =0、不一致 =1。

### 3.2 差异排查三级下钻（排障主路径）

校验不一致时按"表 → 列 → 行"逐级定位，每级一条命令：

```bash
ympctl check tables 2        # ① 哪些表不一致(含差异类型、源/目标行数)
ympctl check result 1        # ② 该表哪些列不一致(diffColNames)、五类差异计数
ympctl check rows 1          # ③ 具体哪些行、源/目标数据对照
# 或一步到位：
ympctl check showdiff 2 --detail --rows 20
```

`showdiff` 输出为固定格式的对比报告（`====SHOW DIFF=====` / `[NO] 源表==目标表` / `====CHECK_COMPARE_END=====`），可直接归档、diff 历史版本、或被既有运维平台按文本解析。

**易错提醒**：表级差异类型（数据不一致/目标表不存在/结构不一致/源表不存在）与行级（冗余/缺失/差异/非法值/校验键为NULL）是**两套枚举**，工具已按平台官方映射分别翻译，读报告时注意区分"表不存在"与"行冗余"不是一回事。

### 3.3 迁移量与进度（口径澄清）

- `task progress` / `task objects` 的迁移量已换算为 **MB** 并附原始 KB。
- **口径**：平台的迁移量按源端 Oracle 段大小（KB）统计，**与行数无关**——2 行的表也显示 64KB（最小初始区）。核对行数请用 `check statistics` 的行进度字段，两个口径不要混用。
- `task metrics` 提供 BPS/RPS 吞吐，可评估迁移窗口是否够用（`--hours` 指定统计时段）。

### 3.4 日志（排障第一现场）

```bash
ympctl task log 1 --lines 200     # 尾部 200 行（默认 100）
ympctl task log 1 --follow        # 实时跟踪，增量输出不重复
ympctl task log-dl 1 -o mlog.zip  # 全量日志打包（供远程分析/工单附件）
```

### 3.5 配置复用（新环境快速复制）

```bash
ympctl task export-config 1 -o tpl.json    # 导出已验证的迁移配置
ympctl task import-config -m 2 -f tpl.json # 新任务导入
ympctl task save --data @tpl.json          # 保存/调整配置
ympctl task precheck --data @tpl.json      # 迁移前检查
```

在向导里配置跑通一次后，配置即成为可版本化的 JSON 资产，新环境导入即用，避免重复配置引入人为差异。

### 3.6 校验任务配置

`check save --data @config.json` 保存校验任务配置（载荷 JSON 需自备，可从现有任务的配置导出参考）。**注意**：纯命令行"从零创建"校验任务与主任务的能力不在当前版本范围内——推荐做法是在 Web 向导完成一次创建，之后用命令行触发与重跑（校验配置在各环境通常同构，重跑频率远高于新建）。

### 3.7 数据源与接口透传

- `ds add/test/refresh` 增改数据源，**密码自动加密后提交**，明文不出本机；`ds test` 适合接入前连通性预检。
- `api` 透传任意平台接口（GET/POST/PUT/DELETE + `--query` + `--data @file`），平台新接口无需等工具更新即可调用——运维侧的"逃生舱口"。

### 3.8 报告归档

```bash
ympctl report migration 1 -o migration_report.zip
ympctl report check 1 -o check_report.zip
```

交付物一键落盘；平台侧出错时工具会明确报错而不是存下损坏文件，归档目录里不会混入坏包。

## 4 使用契约（写进值班手册的部分）

### 4.1 退出码（脚本判废唯一依据）

| 退出码 | 含义 | 值班动作 |
| --- | --- | --- |
| 0 | 成功；watch 类=成功终态/校验通过 | 打勾，进入下一步 |
| 1 | 业务失败、**校验存在差异**、连接失败 | 按差异报告排障，勿放行 |
| 2 | 用法错误 | 检查命令拼写 |
| 130 | 人工中断 | 确认是否需回滚窗口 |

### 4.2 认证与会话

| 项 | 说明 |
| --- | --- |
| Token 位置 | `~/.ympctl.json`（权限 0600），`logout` 即清除 |
| 密码输入 | `--password-stdin` 管道输入（**不要**直接写 `--password`，避免进 shell 历史） |
| 无人值守 | 环境变量 `YMP_USER`/`YMP_PASSWORD`，Token 失效自动重登 |
| 多环境 | 每环境独立执行 login；或用 `YMP_URL` 切换 |

### 4.3 输出格式

交互看表格（中文、对齐）；脚本消费一律加 `--json`（平台原始 JSON，字段稳定）。**不要**解析表格文本做判断——用退出码和 `--json`。

### 4.4 防呆

`task delete` / `ds delete` 默认交互确认；无人值守脚本中如确需跳过，用 `--yes` 并在脚本中自行保证 ID 正确性。

## 5 排障速查（FAQ）

**Q：`task start` 报 "Migration task does not exist / targetDataSourceId is null"？**
任务尚未在向导中保存过迁移配置。先在 Web 向导配置一次（或用 import-config 导入模板），再从命令行触发。

**Q：迁移量 64KB 但表只有 2 行，是不是没迁全？**
迁移量口径是源端段大小，非行数。核对行数用 `check statistics` 的 totalRows/completeRows。

**Q：校验不一致如何快速出结论？**
`check showdiff 2 --detail --rows 20 > diff.txt`，退出码即结论；报告里 `[NO]` 行即问题表，缩进行即差异明细。

**Q：Token 隔多久失效？定时任务半夜失败怎么办？**
配置 `YMP_USER`/`YMP_PASSWORD` 环境变量，失效自动重登；仍失败则检查账号是否被锁（`ympctl status` 看用户状态）。

**Q：平台升级后某命令突然报 YMP-00005？**
该接口在新版本不存在（前端引用与后端实现的版本差）。用 `api` 透传确认接口是否仍在，并在工具升级前临时以 `api` 替代该命令。

**Q：stop 之后任务还在跑？**
停止为异步指令，`stopTaskById` 受理即返回。用 `task watch` 观察状态流转至"已停止(8)"再执行后续操作。

## 6 安装与部署

| 产物 | 适用环境 | 备注 |
| --- | --- | --- |
| windows-amd64.exe | Windows Server / 桌面 | 免安装 |
| linux-amd64 | 主流 x86_64 | `chmod +x` 即用 |
| linux-arm64 | 飞腾/鲲鹏等 ARM64 服务器 | |
| linux-armv7 | ARM 32 位边缘设备 | |

部署建议：统一放置如 `/opt/ympctl/ympctl`，纳入配置管理；版本固定后勿随意替换（退出码契约跨版本稳定）。

**上手三步**：

```bash
./ympctl login --url http://<ymp-host>:8090 --user admin   # 密码走 stdin
./ympctl task list
./ympctl task watch <任务ID>
```

## 7 与平台的适配说明（口径与边界）

| 事项 | 运维须知 |
| --- | --- |
| 迁移量单位 | 源端段大小（KB），工具已换算 MB；与行数口径互不换算 |
| 状态枚举 | 评估/迁移/校验/修复/复验/增量全量状态已中文化（见附录 B） |
| 差异枚举 | 表级与行级两套枚举，报告解读时注意区分 |
| 接口版本差异 | 个别接口在特定平台版本缺失时，工具如实透出平台错误码 |
| 写操作幂等性 | 对不存在的任务 ID 执行 stop/delete，平台可能静默成功——脚本中先 `task list` 校验 ID |
| 会话 | Token 有效期由平台侧策略决定，无人值守务必配置环境变量凭证 |

## 8 能力边界

明确不在当前版本范围内（避免误用）：

- **纯命令行从零创建**主任务与校验任务（含选数据源、勾对象范围）——首次创建建议走 Web 向导；
- 平台侧的迁移执行与调度本身（ympctl 是控制面，不参与数据面）；
- 增量迁移的深度控制（当前为状态查询与基础操作）。

需要调用未封装接口时，一律以 `api` 透传作为标准替代路径。

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

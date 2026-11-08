# ympctl — YMP 迁移平台命令行工具

通过 [YMP (YashanDB Migration Platform)] 的 OpenAPI (`yashan/*` REST 接口) 管理
迁移任务：触发、监控、日志、报告下载，以及数据源/评估/校验等全套操作。

单文件、零第三方依赖（Python 3.7+ 标准库），Windows / Linux 均可运行。

## 快速上手

```bash
# 1. 登录（Token 保存到 ~/.ympctl.json，后续命令免登录）
python ympctl.py login --url http://192.168.72.149:8090 --user admin
# 或管道输入密码，避免进入命令历史
echo "你的密码" | python ympctl.py login --password-stdin

# 2. 确认平台状态
python ympctl.py status

# 3. 查看迁移任务
python ympctl.py task list

# 4. 触发迁移（自动合并已保存的迁移配置后提交）
python ympctl.py task start 1

# 5. 轮询等待迁移结束（脚本可按退出码判断成败）
python ympctl.py task watch 1
python ympctl.py task progress 1     # 迁移量已换算为 MB
python ympctl.py task log 1 --lines 200
python ympctl.py task log 1 --follow  # 或实时跟随新日志
```

## 命令总览

| 分组 | 命令 | 说明 |
|---|---|---|
| 系统 | `login` / `logout` / `status` / `passwd` | 登录、登出、平台版本、改密 |
| 迁移任务 | `task list` | 任务列表（状态含中文释义） |
| | `task show <id>` | 任务详情（源/目标数据源、迁移子任务等） |
| | `task start <id>` | **触发迁移**。自动拉取 `offlineTask/config` 合并后提交 `startTask`；`--force` 置 forceCreate；`--data JSON` 可完全自定义请求体 |
| | `task stop / pause / resume <id>` | 停止 / 暂停 / 恢复（POST，含 JSON 数字 body） |
| | `task delete <id>` | 删除任务（默认二次确认，`--yes` 跳过） |
| | `task progress <id>` | 迁移进度；**迁移量单位 KB→MB 换算显示** |
| | `task objects <id>` | 迁移对象清单（含 MB 换算的迁移量列） |
| | `task metrics <id> --hours 24` | 吞吐指标（BPS/RPS） |
| | `task log <id> [--follow]` | 查看迁移日志（`--follow` 持续轮询新行） |
| | `task log-dl <id> -o x.zip` | 下载迁移日志 zip |
| | `task export-config <id>` | 导出迁移配置 JSON（可作新任务模板；`--modules config,objects`） |
| | `task import-config -m <mid> -f x.json` | 导入迁移配置 |
| | `task save --data @x.json` | 保存迁移配置（创建/更新向导配置） |
| | `task precheck --data @x.json` | 迁移前检查 |
| 数据源 | `ds list / show / add / refresh / test / delete / schemas / types` | 数据源管理；`--data` 里的 `password` **自动按 YMP 算法 AES 加密**（`--plain-password` 可关闭） |
| 评估 | `assess history / situation / abstract / objects / execute / save` | 对象评估 |
| 校验 | `check list` | 校验任务列表（**同时给出主任务ID与checkTaskId**） |
| | `check start <id>` | **触发/重跑校验**；ID 接受主任务ID或checkTaskId，自动解析 |
| | `check info / statistics <id>` | 状态(中文)、行数统计、结果(一致/不一致) |
| | `check tables <id>` | **表级结果**：哪些表不一致、行数对比（差异类型：数据不一致/目标表不存在/结构不一致/源表不存在） |
| | `check showdiff <id>` | **对比报告格式**：`====SHOW DIFF=====` + `[NO] 源表 == 目标表`；`--detail` 附行数/差异分类/不一致列，`--rows N` 附行级示例；发现差异退出码=1 |
| | `check rows <objId>` | **行级差异明细**（冗余/缺失/差异/非法值/校验键为NULL，含源/目标数据） |
| | `check result <objId>` | 单表汇总：不一致列名(diffColNames)、差异分类计数、主键 |
| | `check watch <id>` | 轮询至终态，退出码 0=校验通过 |
| | `check stop / log / log-dl / save / repair / revalidate` | 其余校验操作 |
| 报告 | `report migration <mid>` / `report check <cid>` | 下载迁移 / 校验报告 zip |
| 工具 | `encrypt <text>` | 数据源密码加密（AES-128-CBC/ZeroPadding/Base64，key=iv=`1234567890123456`） |
| 透传 | `api GET/POST/DELETE <path> [--query k=v,..] [--data @f]` | 任意未封装接口 |

全局参数：`--url`（默认读配置/环境变量）、`--timeout`；大多数列表/详情命令支持 `--json` 输出原始 JSON。

## 配置与自动化

- Token 位置：`~/.ympctl.json`（`login` 后自动保存；`logout` 清除）。
- 环境变量覆盖：`YMP_URL` / `YMP_USER` / `YMP_PASSWORD` / `YMP_TOKEN`。
- 定时/脚本场景：设置 `YMP_USER`+`YMP_PASSWORD` 环境变量后，Token 失效会自动重登；
  或使用 `login --save-password` 明文保存密码（有安全风险，仅限受控环境）。
- `task watch`：终态=完成(9)等退出码 0；失败/停止等退出码 1；Ctrl+C 退出码 130。

## 关键实现说明（踩坑记录）

- **登录**：`POST yashan/user/login`，body `{userName, password: SHA256-Hex(明文)}`，
  成功码 `YMP-00000`，响应含 `token`；后续请求带 `Access-Token`/`Authorization` 头。
- **触发迁移**：直接 `startTask {taskId}` 会报 `targetDataSourceId is null`——必须先
  `GET yashan/migration/offlineTask/config?migrationTaskId=x&taskId=y` 取回已保存配置，
  合并 `{taskId, migrationTaskId, needAssessment, forceCreate}` 后再提交。
- **任务操作方法**：`stopTaskById`/`suspendTaskById`/`recoverTaskById`/`deleteTaskById/{id}`
  均为 **POST**（body 为 JSON 数字），用 DELETE 会被服务端拒绝并重置连接。
- **迁移量单位**：`dataTotalSize`/`dataMigrationSize`/progress 的 total/success 等
  单位是 **KB**（对应 Oracle 段大小，非行数！），工具内已换算 MB 显示。
- **校验任务 ID**：`task list` 显示的是主任务 ID（headTaskId），触发校验用
  `check/task/start/{checkTaskId}`——两者不同！用 `check list` 查看，或直接传主任务 ID，
  工具会经 `getTaskBaseInfo.checkTask` 自动解析。校验状态在 `getTaskBaseInfo.checkTask`
  与 `check/status/statistics` 里，`check/status/info` 仅含基础信息。
- **校验差异明细接口**：`check/status/detail?checkTaskId=X` 为表级列表（其 `id` 列即
  checkObjId）；`check/status/result/{checkObjId}` 为单表汇总（`diffColNames` 即不一致
  **列名**）；`check/status/resultDetail?checkObjId=X` 为行级差异（sourceData/targetData）。
  注意表级 `diffTypes`（1=数据不一致/2=目标表不存在/3=结构不一致/9=源表不存在）与行级
  `resultType`（0=冗余/1=缺失/2=差异/4=非法值/5=校验键为NULL）是**两套枚举**。
- **数据源密码**：前端用 crypto-js AES-CBC/ZeroPadding 加密后提交，key=iv=`1234567890123456`；
  工具内置纯 Python AES-128（通过 FIPS-197 与 SP800-38A 标准向量校验）。
- **下载类接口**出错时服务端返回 JSON 错误体，工具会识别并报错而不是存下坏文件。
- 未登录访问返回 HTTP 401；`getHistoryLog`/`getConvertDBType` 等个别前端引用的接口
  在 YMP 23.5.24.102 后端上不存在（YMP-00005），属版本差异。

## 已验证项（2026-11-08，YMP 23.5.24.102）

login / status / task list / show / **start(真实触发并完成迁移)** / progress / objects /
metrics / log / log-dl / watch / export-config / stop / pause / resume / delete（错误路径）/
ds list / show / schemas / test（含密码加密） / add（服务端连通性校验拒绝路径） /
**check list / start(真实触发三轮校验) / info / statistics / watch / tables / showdiff /
rows / result（真实差异：目标端插入第3行后全部命中）** / report migration /
report check（错误路径）/ api 透传 / encrypt。

# ympctl — YMP 迁移平台命令行工具（v0.1 基础版）

通过 YMP (YashanDB Migration Platform) 的 OpenAPI（`yashan/*` REST 接口）管理迁移任务：
触发、监控、日志、报告下载，以及数据源/评估/校验等操作。

单文件、零第三方依赖（Python 3.7+ 标准库），Windows / Linux 均可运行。

## 快速上手

```bash
python ympctl.py login --url http://192.168.72.149:8090 --user admin
python ympctl.py status
python ympctl.py task list
python ympctl.py task start 1          # 触发迁移（自动合并已保存配置）
python ympctl.py task progress 1
python ympctl.py task log 1 --lines 200
python ympctl.py task watch 1          # 轮询等待迁移结束
python ympctl.py ds list
python ympctl.py check info 1
python ympctl.py report migration 1 -o report.zip
python ympctl.py api GET yashan/platform/getInfo   # 任意接口透传
```

## 关键实现说明

- **登录**：`POST yashan/user/login`，密码 SHA256-Hex；Token 保存于 `~/.ympctl.json`，
  后续请求带 `Access-Token`/`Authorization` 头。
- **触发迁移**：先 `GET yashan/migration/offlineTask/config` 取回已保存配置，
  合并 `{taskId, migrationTaskId, needAssessment, forceCreate}` 后提交 `startTask`。
- **任务操作**：`stopTaskById`/`suspendTaskById`/`recoverTaskById`/`deleteTaskById/{id}`
  均为 **POST**（body 为 JSON 数字），服务端不支持 DELETE。
- **下载类接口**出错时服务端返回 JSON 错误体，工具识别并报错而非存下坏文件。
- 环境变量：`YMP_URL` / `YMP_USER` / `YMP_PASSWORD` / `YMP_TOKEN`。

## 已验证（YMP 23.5.24.102）

login / status / task list / show / start（真实触发并完成迁移）/ stop / pause / resume /
delete（错误路径）/ progress / objects / metrics / log / log-dl / watch / export-config /
ds list / show / schemas / add（连通性拒绝路径）/ check list / info / statistics /
report migration / report check（错误路径）/ api 透传。

## 已知限制

- 迁移量字段（`dataTotalSize` 等）原始单位为 KB，暂未换算显示。
- 校验模块为基础封装（无差异明细）。

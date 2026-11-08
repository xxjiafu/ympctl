# ympctl — YMP 迁移平台命令行工具（v0.3 数据源加密）

通过 YMP (YashanDB Migration Platform) 的 OpenAPI（`yashan/*` REST 接口）管理迁移任务：
触发、监控、日志、报告下载，以及数据源/评估/校验等操作。

单文件、零第三方依赖（Python 3.7+ 标准库），Windows / Linux 均可运行。

## 快速上手

```bash
python ympctl.py login --url http://192.168.72.149:8090 --user admin
python ympctl.py status
python ympctl.py task list
python ympctl.py task start 1          # 触发迁移（自动合并已保存配置）
python ympctl.py task progress 1       # 迁移量已换算为 MB
python ympctl.py task watch 1          # 轮询等待迁移结束（退出码 0=成功）
python ympctl.py ds test --data '{"name":"t","type":1,"connectType":0,
    "host":"192.168.72.169","port":1521,"userName":"system",
    "password":"明文将自动加密","databaseName":"orcl"}'
python ympctl.py encrypt "任意明文"     # 数据源密码加密工具
python ympctl.py api GET yashan/platform/getInfo
```

## v0.3 数据源密码加密

- `ds add/refresh/test` 的 `--data` 中 `password` **自动按 YMP 前端算法加密**：
  AES-128-CBC + ZeroPadding，key=iv=`1234567890123456`，输出 Base64
  （已实测服务端接受）。
- 内置**纯 Python AES-128 实现**（通过 FIPS-197 与 SP800-38A 标准测试向量校验），
  保持零第三方依赖。
- `ympctl encrypt <text>` 独立加密命令；`--plain-password` 可关闭自动加密。

## 关键实现说明

- **登录**：`POST yashan/user/login`，密码 SHA256-Hex；Token 保存于 `~/.ympctl.json`。
- **触发迁移**：先 `GET yashan/migration/offlineTask/config` 取回已保存配置，
  合并后提交 `startTask`；任务操作统一 **POST**。
- **下载类接口**出错时服务端返回 JSON 错误体，工具识别并报错而非存下坏文件。
- 环境变量：`YMP_URL` / `YMP_USER` / `YMP_PASSWORD` / `YMP_TOKEN`。

## 已验证（YMP 23.5.24.102）

login / status / task list / show / start（真实触发并完成迁移）/ stop / pause / resume /
delete（错误路径）/ progress / objects / metrics / log / log-dl / watch / export-config /
ds list / show / schemas / **test（含密码加密）** / add（连通性拒绝路径）/
check list / info / statistics / report migration / report check（错误路径）/ api 透传 / encrypt。

## 已知限制

- 校验模块为基础封装（无差异明细、无任务 ID 自动解析）。

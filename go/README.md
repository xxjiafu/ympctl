# ympctl-go — YMP 迁移平台命令行工具（Go 实现）

`ympctl` 的 Go 语言实现，与仓库根目录的 Python 版（`ympctl.py`）**功能对齐**：
通过 YMP (YashanDB Migration Platform) 的 OpenAPI（`yashan/*` REST 接口）管理迁移任务。

- 纯 Go 标准库，无第三方依赖，编译为单个可执行文件
- **共用 `~/.ympctl.json` 配置与 Token**，可与 Python 版互换使用
- 数据源密码 AES-128-CBC/ZeroPadding 加密与 Python 版**逐字节一致**

## 构建

```bash
cd go
go build -o ympctl.exe .          # Windows
GOOS=linux GOARCH=amd64 go build -o ympctl .   # Linux
```

## 快速上手

```bash
./ympctl login --url http://192.168.72.149:8090 --user admin
./ympctl task list
./ympctl task start 1            # 触发迁移(自动合并已保存配置)
./ympctl task watch 1            # 等待迁移结束(0=成功)
./ympctl task progress 1         # 迁移量已换算 MB
./ympctl check showdiff 2 --detail --rows 3   # 差异对比报告
./ympctl encrypt "明文"           # 数据源密码加密
./ympctl api GET yashan/platform/getInfo      # 原始 API 透传
```

## 命令一览

| 分组 | 命令 |
|---|---|
| 账号 | login / logout / status / passwd / encrypt |
| 迁移任务 | task list / show / start / stop / pause / resume / delete / progress / metrics / objects / log / log-dl / watch / save / precheck / export-config / import-config |
| 数据源 | ds list / show / add / refresh / test / delete / schemas / types |
| 评估 | assess history / situation / abstract / objects / execute / save |
| 校验 | check list / info / statistics / result / tables / showdiff / rows / start / stop / watch / log / log-dl / save / repair / revalidate |
| 报告 | report migration / check |
| 透传 | api GET\|POST\|DELETE\|PUT <path> |

退出码约定：`task watch` 0=迁移成功终态；`check watch`/`check showdiff` 0=校验通过/无差异，
1=存在差异或失败；130=手动中断（Ctrl+C）。

环境变量：`YMP_URL` / `YMP_USER` / `YMP_PASSWORD` / `YMP_TOKEN`。

# ympctl — YMP 迁移平台命令行工具

通过 YMP (YashanDB Migration Platform) 的 OpenAPI（`yashan/*` REST 接口）管理迁移任务：
触发、监控、日志、配置导入导出、数据校验差异对比、报告下载，以及数据源/评估等全套操作。

- **Go 语言实现**：纯标准库、零第三方依赖、编译为单个可执行文件（Windows / Linux）
- 配置与 Token 保存于 `~/.ympctl.json`
- 数据源密码采用 YMP 前端同款 AES-128-CBC/ZeroPadding 加密（NIST 向量校验）

## 构建

```bash
go build -o ympctl.exe .            # Windows
GOOS=linux GOARCH=amd64 go build -o ympctl .   # Linux
```

## 快速上手

```bash
./ympctl login --url http://192.168.72.149:8090 --user admin
./ympctl task list
./ympctl task start 1               # 触发迁移(自动合并已保存配置)
./ympctl task watch 1               # 等待迁移结束(退出码 0=成功)
./ympctl task progress 1            # 迁移量已换算 MB
./ympctl task log 1 --follow        # 实时日志
./ympctl check showdiff 2 --detail --rows 3   # 校验差异对比报告
./ympctl report migration 1 -o report.zip
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

## 测试

```bash
go test ./...        # 单元测试: 加密向量/辅助函数/参数重排
bash regression.sh   # 集成回归(需可访问的 YMP 实例): 88 项全命令验证
```

回归脚本对差异类断言采用动态校验(输出与当时数据状态自洽)，
不触发真实迁移、不改密码、不动数据。

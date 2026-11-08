package main

// ympctl-go — YMP (YashanDB Migration Platform) 命令行工具 Go 实现
// 与 Python 版(ympctl.py)功能对齐，纯标准库，共用 ~/.ympctl.json 配置。

import (
	"fmt"
	"os"
	"sort"
	"strings"
)

const version = "ympctl go 1.0.0 (功能对齐 python v1.0)"

const mainHelp = `ympctl — YMP (YashanDB Migration Platform) 命令行控制工具

用法: ympctl <group> <action> [参数]

命令组:
  login/logout/status/passwd/encrypt   登录、登出、平台状态、改密、密码加密
  task      迁移任务：list/show/start/stop/pause/resume/delete/progress/
            metrics/objects/log/log-dl/watch/save/precheck/export-config/import-config
  ds        数据源：list/show/add/refresh/test/delete/schemas/types
  assess    对象评估：history/situation/abstract/objects/execute/save
  check     数据校验：list/info/statistics/result/tables/showdiff/rows/
            start/stop/watch/log/log-dl/save/repair/revalidate
  report    报告下载：migration/check
  api       原始 API 透传: api GET|POST|DELETE|PUT <path> [--query k=v,..] [--data @f]

示例:
  ympctl login --url http://192.168.72.149:8090 --user admin
  ympctl task list
  ympctl task start 1
  ympctl task watch 1
  ympctl check showdiff 2 --detail
  ympctl api GET yashan/dataSource/getDatasourceList

说明: Token 保存于 ~/.ympctl.json (与 Python 版互通)。
      环境变量: YMP_URL / YMP_USER / YMP_PASSWORD / YMP_TOKEN。
      大多数命令支持 --json 输出原始 JSON、--url/--timeout 覆盖默认。
`

func printMainHelp() { fmt.Print(mainHelp) }

func run(args []string) int {
	if len(args) == 0 {
		printMainHelp()
		return 0
	}
	switch args[0] {
	case "login", "logout", "status", "passwd", "encrypt":
		return cmdAccount(args)
	case "task":
		return cmdTask(args[1:])
	case "ds":
		return cmdDS(args[1:])
	case "assess":
		return cmdAssess(args[1:])
	case "check":
		return cmdCheck(args[1:])
	case "report":
		return cmdReport(args[1:])
	case "api":
		return cmdAPI(args[1:])
	case "--version", "version":
		fmt.Println(version)
		return 0
	case "-h", "--help", "help":
		printMainHelp()
		return 0
	default:
		fmt.Fprintf(os.Stderr, "ympctl: 未知命令 %q\n\n", args[0])
		printMainHelp()
		return 2
	}
}

// valueFlags: 需要取值的选项名(重排参数用)
var valueFlags = map[string]bool{
	"url": true, "timeout": true, "user": true, "password": true,
	"data": true, "query": true, "name": true, "page": true, "size": true,
	"lines": true, "interval": true, "output": true, "o": true,
	"migration-id": true, "m": true, "modules": true, "hours": true,
	"cascade": true, "rows": true, "file": true, "f": true,
}

// reorderArgs 把出现在位置参数之后的选项挪到前面，兼容 `task start 1 --json` 写法。
func reorderArgs(args []string) []string {
	var flags, pos []string
	expectValue := false
	for _, t := range args {
		if expectValue {
			flags = append(flags, t)
			expectValue = false
			continue
		}
		if strings.HasPrefix(t, "-") && t != "-" {
			flags = append(flags, t)
			name := strings.TrimLeft(t, "-")
			if strings.Contains(name, "=") {
				continue
			}
			if valueFlags[name] {
				expectValue = true
			}
			continue
		}
		pos = append(pos, t)
	}
	return append(flags, pos...)
}

func sortedKeys(m map[string]string) []string {
	ks := make([]string, 0, len(m))
	for k := range m {
		ks = append(ks, k)
	}
	sort.Strings(ks)
	return ks
}

func main() { os.Exit(run(os.Args[1:])) }

package main

import (
	"flag"
	"fmt"
	"net/url"
	"os"
	"strings"
)

func cmdReport(args []string) int {
	if len(args) > 0 {
		args = append([]string{args[0]}, reorderArgs(args[1:])...)
	}
	if len(args) == 0 {
		fmt.Println("report 子命令: migration <migration_id> / check <check_id> (配 -o)")
		return 0
	}
	switch args[0] {
	case "migration":
		return reportMigration(args[1:])
	case "check":
		return reportCheck(args[1:])
	}
	fmt.Fprintf(os.Stderr, "未知 report 子命令 %q\n", args[0])
	return 2
}

func reportMigration(args []string) int {
	fs := flag.NewFlagSet("report migration", flag.ExitOnError)
	var urlF, output string
	var timeout int
	fs.StringVar(&urlF, "url", "", "")
	fs.IntVar(&timeout, "timeout", 0, "")
	fs.StringVar(&output, "output", "", "输出文件名")
	fs.StringVar(&output, "o", "", "输出文件名")
	fs.Parse(args)
	pos := fs.Args()
	if len(pos) < 1 {
		fail("需要 migrationTaskId")
	}
	mid := numInt(pos[0])
	c := dsClient(urlF, timeout)
	if output == "" {
		output = fmt.Sprintf("migration-report-%d.zip", mid)
	}
	c.GetOut("yashan/reportDownload/migrationReport",
		paramsOf("migrationTaskId", fmt.Sprintf("%d", mid)),
		map[string]string{"Content-Type": "application/zip"}, output)
	fmt.Printf("已下载: %s\n", output)
	return 0
}

func reportCheck(args []string) int {
	fs := flag.NewFlagSet("report check", flag.ExitOnError)
	var urlF, output string
	var timeout int
	fs.StringVar(&urlF, "url", "", "")
	fs.IntVar(&timeout, "timeout", 0, "")
	fs.StringVar(&output, "output", "", "输出文件名")
	fs.StringVar(&output, "o", "", "输出文件名")
	fs.Parse(args)
	pos := fs.Args()
	if len(pos) < 1 {
		fail("需要 checkTaskId")
	}
	cid := numInt(pos[0])
	c := dsClient(urlF, timeout)
	if output == "" {
		output = fmt.Sprintf("check-report-%d.zip", cid)
	}
	c.GetOut(fmt.Sprintf("yashan/reportDownload/getCheckTaskReport/%d", cid),
		nil, map[string]string{"Content-Type": "application/zip"}, output)
	fmt.Printf("已下载: %s\n", output)
	return 0
}

func cmdAPI(args []string) int {
	fs := flag.NewFlagSet("api", flag.ExitOnError)
	var query, data, urlF string
	var raw bool
	var timeout int
	fs.StringVar(&query, "query", "", "查询参数: k1=v1,k2=v2")
	fs.StringVar(&data, "data", "", "请求体: JSON 字符串 / @file / - (stdin)")
	fs.BoolVar(&raw, "raw", false, "原样输出响应字节")
	fs.StringVar(&urlF, "url", "", "")
	fs.IntVar(&timeout, "timeout", 0, "")
	fs.Parse(reorderArgs(args))
	pos := fs.Args()
	if len(pos) < 2 {
		fail("用法: ympctl api GET|POST|DELETE|PUT <path> [--query k=v,..] [--data @f]")
	}
	method := strings.ToUpper(pos[0])
	if method != "GET" && method != "POST" && method != "DELETE" && method != "PUT" {
		fail("不支持的 HTTP 方法: %s", method)
	}
	path := pos[1]
	c := newClient(urlF, timeout, false)
	ensureToken(c)

	params := url.Values{}
	if query != "" {
		for _, kv := range strings.Split(query, ",") {
			if i := strings.Index(kv, "="); i >= 0 {
				params.Add(kv[:i], kv[i+1:])
			}
		}
	}
	var body []byte
	if data != "" {
		body = parseDataArg(data)
	}
	res, err := c.Request(method, path, params, body, nil, "")
	if err != nil {
		fail("%v", err)
	}
	if raw {
		os.Stdout.Write(res)
		return 0
	}
	emit(mustAny(res), true)
	return 0
}

package main

import (
	"flag"
	"fmt"
	"net/url"
	"os"
	"strings"
)

const dsHelp = `ds 子命令:
  list                     数据源列表
  show <ds_id>             数据源详情
  add --data <json>        新增数据源(password 自动加密)
  refresh --data <json>    刷新/更新数据源
  test --data <json>       测试连通性(password 自动加密)
  delete <ds_id> [--yes]   删除数据源
  schemas <ds_id>          列出 schema(--blacklist a,b)
  types                    支持的目标库类型`

func cmdDS(args []string) int {
	if len(args) > 0 {
		args = append([]string{args[0]}, reorderArgs(args[1:])...)
	}
	if len(args) == 0 {
		fmt.Println(dsHelp)
		return 0
	}
	switch args[0] {
	case "list":
		return dsList(args[1:])
	case "show":
		return dsShow(args[1:])
	case "add":
		return dsAction(args[1:], "yashan/dataSource/addDatasource")
	case "refresh":
		return dsAction(args[1:], "yashan/dataSource/refreshDatasource")
	case "test":
		return dsAction(args[1:], "yashan/dataSource/testConnection")
	case "delete":
		return dsDelete(args[1:])
	case "schemas":
		return dsSchemas(args[1:])
	case "types":
		return dsTypes(args[1:])
	}
	fmt.Fprintf(os.Stderr, "未知 ds 子命令 %q\n", args[0])
	return 2
}

func dsClient(urlF string, timeout int) *Client {
	c := newClient(urlF, timeout, false)
	ensureToken(c)
	return c
}

func dsList(args []string) int {
	fs := flag.NewFlagSet("ds list", flag.ExitOnError)
	var jsonMode bool
	var urlF string
	var timeout int
	fs.BoolVar(&jsonMode, "json", false, "输出原始 JSON")
	fs.StringVar(&urlF, "url", "", "")
	fs.IntVar(&timeout, "timeout", 0, "")
	fs.Parse(args)

	c := dsClient(urlF, timeout)
	result := getMap(c.Get("yashan/dataSource/getDatasourceList", nil))
	records := getList(result["records"])
	if jsonMode {
		emit(result, true)
		return 0
	}
	shown := make([]map[string]any, 0, len(records))
	for _, r := range records {
		rm := getMap(r)
		row := map[string]any{}
		for k, v := range rm {
			row[k] = v
		}
		row["type"] = fmt.Sprintf("%s(%s)", label(dbType, rm["type"]), fmtCell(rm["type"]))
		shown = append(shown, row)
	}
	printTable(shown, []col{
		{"id", "ID"}, {"name", "名称"}, {"type", "类型"},
		{"version", "版本"}, {"connectStr", "连接串"},
		{"userName", "用户"}, {"createTime", "创建时间"},
	})
	return 0
}

func dsShow(args []string) int {
	fs := flag.NewFlagSet("ds show", flag.ExitOnError)
	var jsonMode bool
	var urlF string
	var timeout int
	fs.BoolVar(&jsonMode, "json", false, "")
	fs.StringVar(&urlF, "url", "", "")
	fs.IntVar(&timeout, "timeout", 0, "")
	fs.Parse(args)
	pos := fs.Args()
	if len(pos) < 1 {
		fail("需要数据源 ID")
	}
	dsID := numInt(pos[0])
	c := dsClient(urlF, timeout)
	result := getMap(c.Get("yashan/dataSource/getDatasourceList", nil))
	var match map[string]any
	for _, r := range getList(result["records"]) {
		rm := getMap(r)
		if numInt(rm["id"]) == dsID {
			match = rm
			break
		}
	}
	emit(match, jsonMode)
	return 0
}

func dsAction(args []string, path string) int {
	fs := flag.NewFlagSet("ds action", flag.ExitOnError)
	var data, urlF string
	var plain, jsonMode bool
	var timeout int
	fs.StringVar(&data, "data", "", "数据源 JSON 或 @file")
	fs.BoolVar(&plain, "plain-password", false, "不加密 password 字段")
	fs.BoolVar(&jsonMode, "json", false, "")
	fs.StringVar(&urlF, "url", "", "")
	fs.IntVar(&timeout, "timeout", 0, "")
	fs.Parse(args)
	c := dsClient(urlF, timeout)
	raw := parseDataArg(data)
	if raw == nil {
		fail("需要 --data JSON（数据源参数）")
	}
	m, err := decodeAny(raw)
	if err != nil {
		fail("--data 不是合法 JSON: %v", err)
	}
	payload := getMap(m)
	if pw, ok := payload["password"].(string); ok && pw != "" && !plain {
		// YMP 前端对数据源密码做 AES 加密后再提交
		payload["password"] = EncryptPassword(pw)
	}
	emit(c.PostJSON(path, payload), jsonMode)
	return 0
}

func dsDelete(args []string) int {
	fs := flag.NewFlagSet("ds delete", flag.ExitOnError)
	var urlF string
	var timeout int
	var yes bool
	fs.StringVar(&urlF, "url", "", "")
	fs.IntVar(&timeout, "timeout", 0, "")
	fs.BoolVar(&yes, "yes", false, "跳过确认")
	fs.Parse(args)
	pos := fs.Args()
	if len(pos) < 1 {
		fail("需要数据源 ID")
	}
	dsID := numInt(pos[0])
	if !yes {
		ans := strings.ToLower(readLine(fmt.Sprintf("确认删除数据源 %d？(y/N): ", dsID)))
		if ans != "y" && ans != "yes" {
			fmt.Println("已取消")
			return 0
		}
	}
	c := dsClient(urlF, timeout)
	c.PostRaw(fmt.Sprintf("yashan/dataSource/deleteDatasource/%d", dsID), nil)
	fmt.Printf("数据源 %d 已删除\n", dsID)
	return 0
}

func dsSchemas(args []string) int {
	fs := flag.NewFlagSet("ds schemas", flag.ExitOnError)
	var blacklist, urlF string
	var jsonMode bool
	var timeout int
	fs.StringVar(&blacklist, "blacklist", "", "逗号分隔的黑名单(传空串=全部)")
	fs.BoolVar(&jsonMode, "json", false, "")
	fs.StringVar(&urlF, "url", "", "")
	fs.IntVar(&timeout, "timeout", 0, "")
	// 记录 --blacklist 是否显式给出(区分未传与传空串)
	hasBlack := false
	for _, a := range args {
		if a == "--blacklist" || strings.HasPrefix(a, "--blacklist=") {
			hasBlack = true
		}
	}
	fs.Parse(args)
	pos := fs.Args()
	if len(pos) < 1 {
		fail("需要数据源 ID")
	}
	dsID := numInt(pos[0])
	c := dsClient(urlF, timeout)
	var result any
	if hasBlack {
		bl := []string{}
		for _, s := range strings.Split(blacklist, ",") {
			if s = strings.TrimSpace(s); s != "" {
				bl = append(bl, s)
			}
		}
		if len(bl) == 0 {
			bl = []string{"__all__"}
		}
		params := url.Values{}
		for _, s := range bl {
			params.Add("blackList", s)
		}
		result = c.Get(fmt.Sprintf("yashan/dataSource/getSchemasWithBlackList/%d", dsID), params)
	} else {
		result = c.Get(fmt.Sprintf("yashan/dataSource/getSchemas/%d", dsID), nil)
	}
	emit(result, jsonMode)
	return 0
}

func dsTypes(args []string) int {
	fs := flag.NewFlagSet("ds types", flag.ExitOnError)
	var jsonMode bool
	var urlF string
	var timeout int
	fs.BoolVar(&jsonMode, "json", false, "")
	fs.StringVar(&urlF, "url", "", "")
	fs.IntVar(&timeout, "timeout", 0, "")
	fs.Parse(args)
	c := dsClient(urlF, timeout)
	emit(c.Get("yashan/dataSource/getConvertDBType/", nil), jsonMode)
	return 0
}

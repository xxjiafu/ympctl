package main

import (
	"flag"
	"fmt"
	"net/url"
	"os"
)

const assessHelp = `assess 子命令:
  history                  评估历史记录(--page/--size)
  situation <id>           评估对象总体情况
  abstract <id>            评估摘要情况
  objects --data <json>    评估对象明细(JSON 作为查询参数)
  execute --data <json>    执行对象评估
  save --data <json>       保存评估任务`

func cmdAssess(args []string) int {
	if len(args) > 0 {
		args = append([]string{args[0]}, reorderArgs(args[1:])...)
	}
	if len(args) == 0 {
		fmt.Println(assessHelp)
		return 0
	}
	switch args[0] {
	case "history":
		return assessHistory(args[1:])
	case "situation":
		return assessByID(args[1:], "getAllObjSituation", "评估对象总体情况")
	case "abstract":
		return assessByID(args[1:], "getTaskAbstractSituation", "评估摘要情况")
	case "objects":
		return assessObjects(args[1:])
	case "execute":
		return assessPost(args[1:], "executeObjAssessmentTask")
	case "save":
		return assessPost(args[1:], "saveObjAssessmentTask")
	}
	fmt.Fprintf(os.Stderr, "未知 assess 子命令 %q\n", args[0])
	return 2
}

func assessEnv(fs *flag.FlagSet) (urlF string, timeout int, jsonMode bool) {
	fs.StringVar(&urlF, "url", "", "")
	fs.IntVar(&timeout, "timeout", 0, "")
	fs.BoolVar(&jsonMode, "json", false, "")
	return
}

func assessHistory(args []string) int {
	fs := flag.NewFlagSet("assess history", flag.ExitOnError)
	urlF, timeout, jsonMode := assessEnv(fs)
	page := fs.Int("page", 1, "页码")
	size := fs.Int("size", 20, "每页条数")
	fs.Parse(args)
	c := dsClient(urlF, timeout)
	result := getMap(c.Get("yashan/objAssessmentTask/getHistoryLog",
		paramsOf("pageNum", fmt.Sprintf("%d", *page),
			"pageSize", fmt.Sprintf("%d", *size))))
	records := getList(result["records"])
	if jsonMode {
		emit(result, true)
		return 0
	}
	rows := make([]map[string]any, 0, len(records))
	for _, r := range records {
		rows = append(rows, getMap(r))
	}
	printTable(rows, []col{
		{"id", "评估ID"}, {"taskName", "名称"}, {"taskStatus", "状态"},
		{"sourceDbType", "源库"}, {"startTime", "开始时间"},
		{"updateTime", "更新时间"},
	})
	return 0
}

func assessByID(args []string, endpoint, help string) int {
	fs := flag.NewFlagSet("assess "+endpoint, flag.ExitOnError)
	urlF, timeout, jsonMode := assessEnv(fs)
	fs.Parse(args)
	pos := fs.Args()
	if len(pos) < 1 {
		fail("需要评估任务 ID: %s", help)
	}
	id := numInt(pos[0])
	c := dsClient(urlF, timeout)
	emit(c.Get(fmt.Sprintf("yashan/objAssessmentTask/%s/%d", endpoint, id), nil), jsonMode)
	return 0
}

func assessObjects(args []string) int {
	fs := flag.NewFlagSet("assess objects", flag.ExitOnError)
	urlF, timeout, jsonMode := assessEnv(fs)
	var data string
	fs.StringVar(&data, "data", "", "查询参数 JSON(转为查询串)")
	fs.Parse(args)
	c := dsClient(urlF, timeout)
	params := url.Values{}
	if raw := parseDataArg(data); raw != nil {
		m, err := decodeAny(raw)
		if err != nil {
			fail("--data 不是合法 JSON: %v", err)
		}
		for k, v := range getMap(m) {
			switch x := v.(type) {
			case []any:
				for _, it := range x {
					params.Add(k, fmtCell(it))
				}
			default:
				params.Add(k, fmtCell(v))
			}
		}
	}
	emit(c.Get("yashan/objAssessmentTask/getObjAssessmentSituation", params), jsonMode)
	return 0
}

func assessPost(args []string, endpoint string) int {
	fs := flag.NewFlagSet("assess "+endpoint, flag.ExitOnError)
	urlF, timeout, jsonMode := assessEnv(fs)
	var data string
	fs.StringVar(&data, "data", "", "请求 JSON 或 @file")
	fs.Parse(args)
	raw := parseDataArg(data)
	if raw == nil {
		fail("需要 --data JSON")
	}
	c := dsClient(urlF, timeout)
	emit(c.PostRaw("yashan/objAssessmentTask/"+endpoint, raw), jsonMode)
	return 0
}

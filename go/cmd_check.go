package main

import (
	"flag"
	"fmt"
	"os"
	"os/signal"
	"strings"
	"time"
)

const checkHelp = `check 子命令:
  list                     校验任务列表(含 checkTaskId, --all 显示全部)
  info <id>                校验任务状态(--brief; ID 自动解析)
  statistics <id>          校验统计
  result <objId>           单表校验结果汇总(含不一致列名)
  tables <id>              表级校验结果(哪些表不一致)
  showdiff <id>            对比报告格式输出([NO] 源表==目标表, --detail/--rows)
  rows <objId>             行级差异明细
  start <id>               触发/重跑校验
  stop <id>                取消校验
  watch <id>               轮询校验直至终态(0=通过)
  log <id>                 校验日志
  log-dl <id> -o x.zip     下载校验日志
  save --data <json>       创建校验任务
  repair --data <json>     校验修复
  revalidate --data <json> 校验复验

说明: <id> 可为主任务ID或checkTaskId, 自动解析; <objId> 来自 tables 列表的 id 列。`

func cmdCheck(args []string) int {
	if len(args) > 0 {
		args = append([]string{args[0]}, reorderArgs(args[1:])...)
	}
	if len(args) == 0 {
		fmt.Println(checkHelp)
		return 0
	}
	switch args[0] {
	case "list":
		return checkList(args[1:])
	case "info":
		return checkInfo(args[1:])
	case "statistics":
		return checkStatistics(args[1:])
	case "result":
		return checkResultCmd(args[1:])
	case "tables":
		return checkTables(args[1:])
	case "showdiff":
		return checkShowdiff(args[1:])
	case "rows":
		return checkRows(args[1:])
	case "start":
		return checkAction(args[1:], "start", "启动")
	case "stop":
		return checkAction(args[1:], "cancel", "取消")
	case "watch":
		return checkWatch(args[1:])
	case "log":
		return checkLog(args[1:])
	case "log-dl":
		return checkLogDL(args[1:])
	case "save":
		return checkPost(args[1:], "yashan/check/task/save")
	case "repair":
		return checkPost(args[1:], "yashan/check/task/repair")
	case "revalidate":
		return checkPost(args[1:], "yashan/check/task/revalidate")
	}
	fmt.Fprintf(os.Stderr, "未知 check 子命令 %q\n", args[0])
	return 2
}

func checkEnv(fs *flag.FlagSet) (urlF string, timeout int, jsonMode bool) {
	fs.StringVar(&urlF, "url", "", "")
	fs.IntVar(&timeout, "timeout", 0, "")
	fs.BoolVar(&jsonMode, "json", false, "")
	return
}

func checkList(args []string) int {
	fs := flag.NewFlagSet("check list", flag.ExitOnError)
	urlF, timeout, jsonMode := checkEnv(fs)
	page := fs.Int("page", 1, "页码")
	all := fs.Bool("all", false, "也显示无校验子任务的主任务")
	fs.Parse(args)
	c := dsClient(urlF, timeout)
	result := getMap(c.Get("yashan/task/getTaskList",
		paramsOf("pageNum", fmt.Sprintf("%d", *page), "pageSize", "100")))
	records := getList(result["records"])
	if jsonMode {
		emit(result, true)
		return 0
	}
	shown := make([]map[string]any, 0, len(records))
	for _, r := range records {
		rm := getMap(r)
		b, err := c.Request("GET", fmt.Sprintf("yashan/task/getTaskBaseInfo/%d",
			int(numInt(rm["id"]))), nil, nil, nil, "")
		if err != nil {
			continue // 单个任务详情失败不阻塞列表
		}
		ct := getMap(getMap(mustAny(b))["checkTask"])
		if ct == nil {
			if !*all {
				continue
			}
			shown = append(shown, map[string]any{
				"headTaskId": rm["id"], "headTaskName": rm["taskName"],
				"checkTaskId": "-", "checkStatus": "(无校验子任务)"})
			continue
		}
		cs := numInt(ct["checkStatus"])
		shown = append(shown, map[string]any{
			"headTaskId":    rm["id"],
			"headTaskName":  rm["taskName"],
			"checkTaskId":   ct["id"],
			"checkTaskName": ct["checkTaskName"],
			"checkStatus":   fmt.Sprintf("%s(%d)", label(checkStatus, ct["checkStatus"]), cs),
			"checkProcess":  ct["checkProcess"],
			"checkResult": func() any {
				if v, ok := checkResult[int(numInt(ct["checkResult"]))]; ok {
					return v
				}
				return ct["checkResult"]
			}(),
			"startTime": ct["startTime"],
		})
	}
	printTable(shown, []col{
		{"headTaskId", "主任务ID"}, {"headTaskName", "主任务名"},
		{"checkTaskId", "校验ID"}, {"checkTaskName", "校验名"},
		{"checkStatus", "校验状态"}, {"checkProcess", "进度%"},
		{"checkResult", "结果"}, {"startTime", "开始时间"},
	})
	fmt.Println("提示: check start/stop/info 等命令的 ID 接受上面任一 ID，会自动解析")
	return 0
}

func checkInfo(args []string) int {
	fs := flag.NewFlagSet("check info", flag.ExitOnError)
	urlF, timeout, jsonMode := checkEnv(fs)
	brief := fs.Bool("brief", false, "只显示概要")
	fs.Parse(args)
	pos := fs.Args()
	if len(pos) < 1 {
		fail("需要校验任务 ID")
	}
	c := dsClient(urlF, timeout)
	cid, ct := resolveCheckID(c, int(numInt(pos[0])))
	info := getMap(c.Get(fmt.Sprintf("yashan/check/status/info/%d", cid), nil))
	merged := map[string]any{}
	for k, v := range ct {
		merged[k] = v
	}
	for k, v := range info {
		merged[k] = v
	}
	if jsonMode {
		emit(merged, true)
		return 0
	}
	st := numInt(merged["checkStatus"])
	fmt.Printf("== 校验任务 %s (checkTaskId=%d) ==\n",
		fmtCell(merged["checkTaskName"]), cid)
	printKV(map[string]any{
		"状态":     fmt.Sprintf("%s(%d)", label(checkStatus, merged["checkStatus"]), st),
		"结果":     label(checkResult, merged["checkResult"]),
		"进度":     merged["checkProcess"],
		"开始时间":   merged["startTime"],
		"结束时间":   merged["endTime"],
		"校验类型":   merged["checkType"],
		"schema": merged["schemaList"],
	}, 0)
	if !*brief {
		exclude := map[string]bool{"checkTaskName": true, "checkStatus": true,
			"checkResult": true, "checkProcess": true, "startTime": true,
			"endTime": true, "source": true, "target": true,
			"checkTaskConfig": true}
		extra := map[string]any{}
		for k, v := range merged {
			if !exclude[k] && v != nil {
				extra[k] = v
			}
		}
		if len(extra) > 0 {
			fmt.Println("-- 其他 --")
			printKV(extra, 0)
		}
	}
	return 0
}

func checkStatistics(args []string) int {
	fs := flag.NewFlagSet("check statistics", flag.ExitOnError)
	urlF, timeout, jsonMode := checkEnv(fs)
	fs.Parse(args)
	pos := fs.Args()
	if len(pos) < 1 {
		fail("需要校验任务 ID")
	}
	c := dsClient(urlF, timeout)
	cid, _ := resolveCheckID(c, int(numInt(pos[0])))
	result := getMap(c.Get(fmt.Sprintf("yashan/check/status/statistics/%d", cid), nil))
	if jsonMode {
		emit(result, true)
		return 0
	}
	disp := map[string]any{}
	for k, v := range result {
		disp[k] = v
	}
	disp["status"] = fmt.Sprintf("%s(%d)",
		label(checkStatus, result["status"]), int(numInt(result["status"])))
	if _, ok := checkResult[int(numInt(result["result"]))]; ok {
		disp["result"] = label(checkResult, result["result"])
	}
	if rpi := getMap(result["rowProgressInfo"]); rpi != nil {
		r2 := map[string]any{}
		for k, v := range rpi {
			r2[k] = v
		}
		r2["progress"] = fmt.Sprintf("%s%%", pfloat(rpi["progress"]))
		disp["rowProgressInfo"] = r2
	}
	fmt.Printf("== 校验统计 (checkTaskId=%d) ==\n", cid)
	printKV(disp, 0)
	return 0
}
func checkResultCmd(args []string) int {
	fs := flag.NewFlagSet("check result", flag.ExitOnError)
	urlF, timeout, jsonMode := checkEnv(fs)
	fs.Parse(args)
	pos := fs.Args()
	if len(pos) < 1 {
		fail("需要表对象 ID(check tables 列表的 id 列)")
	}
	objID := numInt(pos[0])
	c := dsClient(urlF, timeout)
	result := getMap(c.Get(fmt.Sprintf("yashan/check/status/result/%d", objID), nil))
	if jsonMode {
		emit(result, true)
		return 0
	}
	inc := getMap(result["dataInconsistent"])
	same := "不一致"
	if b, ok := result["same"].(bool); ok && b {
		same = "一致"
	}
	fmt.Printf("== 单表校验结果 (checkObjId=%d) ==\n", objID)
	printKV(map[string]any{
		"对比":    same,
		"源行数":   result["sourceRow"],
		"目标行数":  result["targetRow"],
		"差异行数":  result["diffRows"],
		"不一致列名": orDash(result["diffColNames"]),
		"源主键":   orDash(result["sourcePkName"]),
		"目标主键":  orDash(result["targetPkName"]),
		"差异分类": map[string]any{
			"冗余(目标端多出)": inc["notInSourceNum"],
			"缺失(目标端缺少)": inc["notInTargetNum"],
			"数据不一致":     inc["diffNum"],
			"非法值":       inc["invalidNum"],
			"校验键为NULL":  inc["uniqueKeyNullNum"],
		},
	}, 0)
	if lob := getList(result["sourceLobColumn"]); len(lob) > 0 {
		parts := make([]string, len(lob))
		for i, x := range lob {
			parts[i] = fmtCell(x)
		}
		fmt.Printf("LOB 列: %s\n", strings.Join(parts, ","))
	}
	if result["errorMessage"] != nil {
		fmt.Printf("错误: %s\n", fmtCell(result["errorMessage"]))
	}
	return 0
}

func orDash(v any) string {
	switch x := v.(type) {
	case []any:
		if len(x) == 0 {
			return "-"
		}
		parts := make([]string, len(x))
		for i, it := range x {
			parts[i] = fmtCell(it)
		}
		return strings.Join(parts, ",")
	case string:
		if x == "" {
			return "-"
		}
		return x
	}
	if v == nil {
		return "-"
	}
	return fmtCell(v)
}

func checkTables(args []string) int {
	fs := flag.NewFlagSet("check tables", flag.ExitOnError)
	urlF, timeout, jsonMode := checkEnv(fs)
	page := fs.Int("page", 1, "页码")
	size := fs.Int("size", 200, "每页条数")
	fs.Parse(args)
	pos := fs.Args()
	if len(pos) < 1 {
		fail("需要校验任务 ID")
	}
	c := dsClient(urlF, timeout)
	cid, _ := resolveCheckID(c, int(numInt(pos[0])))
	result := getMap(c.Get("yashan/check/status/detail",
		paramsOf("checkTaskId", fmt.Sprintf("%d", cid),
			"pageNum", fmt.Sprintf("%d", *page),
			"pageSize", fmt.Sprintf("%d", *size))))
	tables := getList(result["tableDetail"])
	if jsonMode {
		emit(result, true)
		return 0
	}
	shown := make([]map[string]any, 0, len(tables))
	for _, t := range tables {
		tm := getMap(t)
		row := map[string]any{}
		for k, v := range tm {
			row[k] = v
		}
		row["source_table"] = fmt.Sprintf("%s.%s",
			fmtCell(tm["sourceSchemaName"]), fmtCell(tm["sourceTable"]))
		row["target_table"] = fmt.Sprintf("%s.%s",
			fmtCell(tm["targetSchemaName"]), fmtCell(tm["targetTable"]))
		cr := int(numInt(tm["checkResult"]))
		if v, ok := tableCheckResult[cr]; ok {
			row["checkResult"] = v
		}
		dt := int(numInt(tm["diffTypes"]))
		if v, ok := tableDiffType[dt]; ok {
			row["diffTypes"] = v
		}
		shown = append(shown, row)
	}
	printTable(shown, []col{
		{"source_table", "源表"}, {"target_table", "目标表"},
		{"checkResult", "结果"}, {"diffTypes", "差异类型"},
		{"sourceRowCount", "源行数"}, {"targetRowCount", "目标行数"},
		{"checkProgress", "进度%"}, {"objectStatus", "状态"},
	})
	fmt.Printf("共 %s 张表\n", fmtCell(result["total"]))
	return 0
}

func checkShowdiff(args []string) int {
	fs := flag.NewFlagSet("check showdiff", flag.ExitOnError)
	urlF, timeout, _ := checkEnv(fs)
	all := fs.Bool("all", false, "一致表也输出([OK]行)")
	detail := fs.Bool("detail", false, "每张差异表追加行数/分类/不一致列")
	rowsN := fs.Int("rows", 0, "每表附带行级差异示例条数(配合 --detail)")
	size := fs.Int("size", 500, "表级列表最大条数")
	fs.Parse(args)
	pos := fs.Args()
	if len(pos) < 1 {
		fail("需要校验任务 ID")
	}
	c := dsClient(urlF, timeout)
	cid, _ := resolveCheckID(c, int(numInt(pos[0])))
	result := getMap(c.Get("yashan/check/status/detail",
		paramsOf("checkTaskId", fmt.Sprintf("%d", cid),
			"pageNum", "1", "pageSize", fmt.Sprintf("%d", *size))))
	tables := getList(result["tableDetail"])
	fmt.Println("====SHOW DIFF=====")
	fmt.Println("数据校验对比结果")
	hasDiff := false
	for _, t := range tables {
		tm := getMap(t)
		bad := int(numInt(tm["checkResult"])) != 0 || tm["checkResult"] == nil
		if bad {
			hasDiff = true
		} else if !*all {
			continue
		}
		mark := "[OK]"
		if bad {
			mark = "[NO]"
		}
		fmt.Printf("%s %s.%s == %s.%s\n", mark,
			fmtCell(tm["sourceSchemaName"]), fmtCell(tm["sourceTable"]),
			fmtCell(tm["targetSchemaName"]), fmtCell(tm["targetTable"]))
		if bad && *detail {
			summ := getMap(c.Get(fmt.Sprintf("yashan/check/status/result/%d",
				numInt(tm["id"])), nil))
			inc := getMap(summ["dataInconsistent"])
			fmt.Printf("    行数: 源=%s 目标=%s 差异行=%s\n",
				fmtCell(summ["sourceRow"]), fmtCell(summ["targetRow"]),
				fmtCell(summ["diffRows"]))
			cats := []struct {
				name string
				v    any
			}{{"冗余(目标多出)", inc["notInSourceNum"]},
				{"缺失(目标缺少)", inc["notInTargetNum"]},
				{"数据不一致", inc["diffNum"]},
				{"非法值", inc["invalidNum"]},
				{"校验键为NULL", inc["uniqueKeyNullNum"]}}
			var parts []string
			for _, ca := range cats {
				if numInt(ca.v) > 0 {
					parts = append(parts, fmt.Sprintf("%s=%s", ca.name, fmtCell(ca.v)))
				}
			}
			fmt.Printf("    分类: %s\n", strings.Join(parts, "  "))
			cols := getList(summ["diffColNames"])
			if len(cols) == 0 {
				fmt.Println("    不一致列: -")
			} else {
				parts := make([]string, len(cols))
				for i, x := range cols {
					parts[i] = fmtCell(x)
				}
				fmt.Printf("    不一致列: %s\n", strings.Join(parts, ","))
			}
			if *rowsN > 0 {
				rd := getMap(c.Get("yashan/check/status/resultDetail",
					paramsOf("checkObjId", fmtCell(tm["id"]),
						"pageNum", "1", "pageSize", fmt.Sprintf("%d", *rowsN))))
				for _, rr := range getList(rd["records"]) {
					rm := getMap(rr)
					dt := int(numInt(rm["resultType"]))
					dtLabel, ok := diffType[dt]
					if !ok {
						dtLabel = fmtCell(rm["resultType"])
					}
					fmt.Printf("    [%s] 源=%s / 目标=%s 差异列=%s\n",
						dtLabel, parseRowData(rm["sourceData"]),
						parseRowData(rm["targetData"]),
						orDash(rm["diffColName"]))
				}
			}
		}
	}
	fmt.Println("====CHECK_COMPARE_END=====")
	if hasDiff {
		return 1
	}
	return 0
}

func checkRows(args []string) int {
	fs := flag.NewFlagSet("check rows", flag.ExitOnError)
	urlF, timeout, jsonMode := checkEnv(fs)
	page := fs.Int("page", 1, "页码")
	size := fs.Int("size", 50, "每页条数")
	fs.Parse(args)
	pos := fs.Args()
	if len(pos) < 1 {
		fail("需要表对象 ID")
	}
	objID := numInt(pos[0])
	c := dsClient(urlF, timeout)
	result := getMap(c.Get("yashan/check/status/resultDetail",
		paramsOf("checkObjId", fmt.Sprintf("%d", objID),
			"pageNum", fmt.Sprintf("%d", *page),
			"pageSize", fmt.Sprintf("%d", *size))))
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
		dt := int(numInt(rm["resultType"]))
		if v, ok := diffType[dt]; ok {
			row["resultType"] = v
		}
		row["sourceData"] = parseRowData(rm["sourceData"])
		row["targetData"] = parseRowData(rm["targetData"])
		shown = append(shown, row)
	}
	printTable(shown, []col{
		{"resultType", "差异类型"}, {"sourcePk", "源主键"},
		{"targetPk", "目标主键"}, {"sourceData", "源数据"},
		{"targetData", "目标数据"}, {"diffColName", "差异列"},
	})
	if result["total"] != nil {
		fmt.Printf("共 %s 条差异行\n", fmtCell(result["total"]))
	}
	return 0
}

func checkAction(args []string, op, what string) int {
	fs := flag.NewFlagSet("check "+what, flag.ExitOnError)
	urlF, timeout, jsonMode := checkEnv(fs)
	fs.Parse(args)
	pos := fs.Args()
	if len(pos) < 1 {
		fail("需要校验任务 ID")
	}
	c := dsClient(urlF, timeout)
	cid, _ := resolveCheckID(c, int(numInt(pos[0])))
	result := c.PostRaw(fmt.Sprintf("yashan/check/task/%s/%d", op, cid), nil)
	if jsonMode {
		emit(result, true)
		return 0
	}
	fmt.Printf("%s指令已受理（checkTaskId=%d）\n", what, cid)
	if _, ok := result.(map[string]any); ok {
		printKV(result, 0)
	}
	fmt.Printf("查看状态: ympctl check info %d   统计: ympctl check statistics %d\n", cid, cid)
	return 0
}

func checkWatch(args []string) int {
	fs := flag.NewFlagSet("check watch", flag.ExitOnError)
	urlF, timeout, _ := checkEnv(fs)
	interval := fs.Float64("interval", 3.0, "轮询间隔秒")
	fs.Parse(args)
	pos := fs.Args()
	if len(pos) < 1 {
		fail("需要校验任务 ID")
	}
	c := dsClient(urlF, timeout)
	cid, _ := resolveCheckID(c, int(numInt(pos[0])))
	doneOK := map[int]bool{22: true, 42: true, 48: true}
	doneAny := map[int]bool{20: true, 21: true, 22: true, 23: true, 24: true,
		25: true, 40: true, 41: true, 42: true, 43: true, 44: true,
		45: true, 46: true, 47: true, 48: true, 49: true, 50: true,
		51: true, 53: true, 54: true}
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, os.Interrupt)
	for {
		result := getMap(c.Get(fmt.Sprintf("yashan/check/status/statistics/%d", cid), nil))
		st := int(numInt(result["status"]))
		rpi := getMap(result["rowProgressInfo"])
		ts := time.Now().Format("15:04:05")
		fmt.Printf("[%s] 状态=%s(%d) 行进度=%s%% 结果=%s (行 %s/%s, 失败 %s)\n",
			ts, label(checkStatus, result["status"]), st,
			pfloat(rpi["progress"]), label(checkResult, result["result"]),
			fmtCell(rpi["completeRows"]), fmtCell(rpi["totalRows"]),
			fmtCell(rpi["failedRows"]))
		if doneAny[st] {
			fmt.Printf("校验已进入终态: %s(%d)\n", label(checkStatus, result["status"]), st)
			res := int(numInt(result["result"]))
			if doneOK[st] && (res == 0 || res == 4) {
				return 0
			}
			return 1
		}
		select {
		case <-sig:
			return 130
		case <-time.After(time.Duration(*interval * float64(time.Second))):
		}
	}
}

func checkLog(args []string) int {
	fs := flag.NewFlagSet("check log", flag.ExitOnError)
	urlF, timeout, jsonMode := checkEnv(fs)
	lines := fs.Int("lines", 0, "日志行数")
	fs.Parse(args)
	pos := fs.Args()
	if len(pos) < 1 {
		fail("需要校验任务 ID")
	}
	c := dsClient(urlF, timeout)
	cid, _ := resolveCheckID(c, int(numInt(pos[0])))
	params := paramsOf("checkTaskId", fmt.Sprintf("%d", cid))
	if *lines > 0 {
		params.Add("logLine", fmt.Sprintf("%d", *lines))
	}
	emit(c.Get("yashan/check/status/log/view", params), jsonMode)
	return 0
}

func checkLogDL(args []string) int {
	fs := flag.NewFlagSet("check log-dl", flag.ExitOnError)
	urlF, timeout, _ := checkEnv(fs)
	output := fs.String("output", "", "输出文件名")
	fs.Parse(args)
	pos := fs.Args()
	if len(pos) < 1 {
		fail("需要校验任务 ID")
	}
	c := dsClient(urlF, timeout)
	cid, _ := resolveCheckID(c, int(numInt(pos[0])))
	out := *output
	if out == "" {
		out = fmt.Sprintf("check-task-%d-log.zip", cid)
	}
	c.GetOut("yashan/check/status/log/download",
		paramsOf("checkTaskId", fmt.Sprintf("%d", cid)),
		map[string]string{"Content-Type": "application/zip"}, out)
	fmt.Printf("已下载: %s\n", out)
	return 0
}

func checkPost(args []string, path string) int {
	fs := flag.NewFlagSet("check post", flag.ExitOnError)
	urlF, timeout, jsonMode := checkEnv(fs)
	var data string
	fs.StringVar(&data, "data", "", "请求 JSON 或 @file")
	fs.Parse(args)
	raw := parseDataArg(data)
	if raw == nil {
		fail("需要 --data JSON")
	}
	c := dsClient(urlF, timeout)
	emit(c.PostRaw(path, raw), jsonMode)
	return 0
}

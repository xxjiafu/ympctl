package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"time"
)

const taskHelp = `task 子命令:
  list                     任务列表
  show <task_id>           任务详情
  start [task_id]          触发迁移任务(自动合并已保存配置)
  save --data <json>       保存迁移任务配置
  precheck --data <json>   迁移前检查
  stop/pause/resume <id>   停止/暂停/恢复
  delete <id> [--yes]      删除任务
  progress <task_id>       迁移进度(迁移量换算为MB)
  metrics <task_id>        迁移指标(--hours N, 默认24)
  objects <task_id>        迁移对象列表
  log <task_id>            迁移日志(--lines N, --follow)
  log-dl <task_id> -o x.zip  下载迁移日志
  export-config <id> -o f.json   导出迁移配置(--modules config,objects)
  import-config -m <mid> -f f.json  导入迁移配置
  watch <task_id>          轮询直至终态(0=成功,1=失败,130=中断)`

type taskEnv struct {
	jsonMode bool
	mid      int
	urlF     string
	timeout  int
}

func addTaskFlags(fs *flag.FlagSet, e *taskEnv) {
	fs.BoolVar(&e.jsonMode, "json", false, "输出原始 JSON")
	fs.IntVar(&e.mid, "migration-id", 0, "迁移子任务ID(默认自动推断)")
	fs.IntVar(&e.mid, "m", 0, "迁移子任务ID(默认自动推断)")
	fs.StringVar(&e.urlF, "url", "", "")
	fs.IntVar(&e.timeout, "timeout", 0, "")
}

func taskClient(e *taskEnv) *Client {
	c := newClient(e.urlF, e.timeout, false)
	ensureToken(c)
	return c
}

func cmdTask(args []string) int {
	if len(args) > 0 { // 只重排子命令名之后的参数
		args = append([]string{args[0]}, reorderArgs(args[1:])...)
	}
	if len(args) == 0 {
		fmt.Println(taskHelp)
		return 0
	}
	switch args[0] {
	case "list":
		return taskList(args[1:])
	case "show":
		return taskShow(args[1:])
	case "start":
		return taskStart(args[1:])
	case "save":
		return taskSave(args[1:])
	case "precheck":
		return taskPrecheck(args[1:])
	case "stop":
		return taskAction(args[1:], "stopTaskById", "停止")
	case "pause":
		return taskAction(args[1:], "suspendTaskById", "暂停")
	case "resume":
		return taskAction(args[1:], "recoverTaskById", "恢复")
	case "delete":
		return taskDelete(args[1:])
	case "progress":
		return taskProgress(args[1:])
	case "metrics":
		return taskMetrics(args[1:])
	case "objects":
		return taskObjects(args[1:])
	case "log":
		return taskLog(args[1:])
	case "log-dl":
		return taskLogDL(args[1:])
	case "export-config":
		return taskExportConfig(args[1:])
	case "import-config":
		return taskImportConfig(args[1:])
	case "watch":
		return taskWatch(args[1:])
	}
	fmt.Fprintf(os.Stderr, "未知 task 子命令 %q\n", args[0])
	return 2
}

func taskList(args []string) int {
	fs := flag.NewFlagSet("task list", flag.ExitOnError)
	var e taskEnv
	var page, size int
	var name string
	addTaskFlags(fs, &e)
	fs.IntVar(&page, "page", 1, "页码")
	fs.IntVar(&size, "size", 20, "每页条数")
	fs.StringVar(&name, "name", "", "按任务名过滤")
	fs.Parse(args)

	c := taskClient(&e)
	params := paramsOf("pageNum", fmt.Sprintf("%d", page),
		"pageSize", fmt.Sprintf("%d", size))
	if name != "" {
		params.Add("taskName", name)
	}
	result := getMap(c.Get("yashan/task/getTaskList", params))
	records := getList(result["records"])
	if e.jsonMode {
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
		row["sourceDbType"] = fmt.Sprintf("%s(%s)",
			label(dbType, rm["sourceDbType"]), fmtCell(rm["sourceDbType"]))
		st := numInt(rm["taskStatus"])
		row["taskStatus"] = fmt.Sprintf("%s(%d)", label(taskStatus, rm["taskStatus"]), st)
		shown = append(shown, row)
	}
	printTable(shown, []col{
		{"id", "ID"}, {"taskName", "任务名"}, {"sourceDbType", "源库"},
		{"targetDsId", "目标DS"}, {"taskStage", "阶段"},
		{"taskStatus", "状态"}, {"taskProgress", "进度%"},
		{"startTime", "开始时间"},
	})
	fmt.Printf("共 %s 条，第 %s/%s 页\n", fmtCell(result["total"]),
		fmtCell(result["current"]), fmtCell(result["pages"]))
	return 0
}

func taskShow(args []string) int {
	fs := flag.NewFlagSet("task show", flag.ExitOnError)
	var e taskEnv
	var brief bool
	addTaskFlags(fs, &e)
	fs.BoolVar(&brief, "brief", false, "只显示概要")
	fs.Parse(args)
	pos := fs.Args()
	if len(pos) < 1 {
		fail("需要任务 ID: ympctl task show <task_id>")
	}
	taskID := numInt(pos[0])

	c := taskClient(&e)
	base := getMap(c.Get(fmt.Sprintf("yashan/task/getTaskBaseInfo/%d", taskID), nil))
	if e.jsonMode {
		emit(base, true)
		return 0
	}
	task := getMap(base["task"])
	st := numInt(task["taskStatus"])
	fmt.Printf("== 任务 %d ==\n", taskID)
	printKV(map[string]any{
		"任务名":             task["taskName"],
		"状态":              fmt.Sprintf("%s(%d)", label(taskStatus, task["taskStatus"]), st),
		"进度":              task["taskProgress"],
		"源库类型":            label(dbType, task["sourceDbType"]),
		"源数据源":            mapGet(getMap(base["sourceDSInfo"]), "connectStr"),
		"目标数据源":           mapGet(getMap(base["targetDSInfo"]), "connectStr"),
		"开始时间":            task["startTime"],
		"migrationTaskId": mapGet(getMap(base["migrationTask"]), "id"),
		"checkTask":       base["checkTask"],
		"备注":              task["remark"],
	}, 0)
	if !brief {
		exclude := map[string]bool{"task": true, "sourceDSInfo": true, "targetDSInfo": true}
		extra := map[string]any{}
		for k, v := range base {
			if !exclude[k] && v != nil {
				extra[k] = v
			}
		}
		if len(extra) > 0 {
			fmt.Println("-- 其他信息 --")
			printKV(extra, 0)
		}
	}
	return 0
}

func taskStart(args []string) int {
	fs := flag.NewFlagSet("task start", flag.ExitOnError)
	var e taskEnv
	var force bool
	var data string
	addTaskFlags(fs, &e)
	fs.BoolVar(&force, "force", false, "forceCreate=true")
	fs.StringVar(&data, "data", "", "完整启动请求 JSON(覆盖默认参数)")
	fs.Parse(args)
	pos := fs.Args()
	taskID := 0
	if len(pos) >= 1 {
		taskID = int(numInt(pos[0]))
	}

	c := taskClient(&e)
	var payload map[string]any
	if raw := parseDataArg(data); raw != nil {
		m, err := decodeAny(raw)
		if err != nil {
			fail("--data 不是合法 JSON: %v", err)
		}
		payload = getMap(m)
	} else {
		if taskID == 0 {
			fail("需要任务 ID: ympctl task start <task_id>")
		}
		mid := resolveMigrationID(c, e.mid, taskID)
		config := getMap(c.Get("yashan/migration/offlineTask/config",
			paramsOf("migrationTaskId", fmt.Sprintf("%d", mid),
				"taskId", fmt.Sprintf("%d", taskID))))
		payload = map[string]any{}
		for k, v := range config {
			payload[k] = v
		}
		needAssessment := false
		if v, ok := config["needAssessment"]; ok {
			switch x := v.(type) {
			case bool:
				needAssessment = x
			case json.Number:
				needAssessment = numInt(x) != 0
			case string:
				needAssessment = x == "true" || x == "1"
			}
		}
		payload["taskId"] = taskID
		payload["migrationTaskId"] = mid
		payload["needAssessment"] = needAssessment
		payload["forceCreate"] = force
	}
	if getMap(payload)["migrationTaskId"] == nil && e.mid > 0 {
		payload["migrationTaskId"] = e.mid
	}
	result := c.PostRaw("yashan/migration/startTask", mustJSON(payload))
	if e.jsonMode {
		emit(result, true)
		return 0
	}
	fmt.Printf("迁移任务已触发（taskId=%s, migrationTaskId=%s）\n",
		fmtCell(payload["taskId"]), fmtCell(payload["migrationTaskId"]))
	if result != nil {
		printKV(result, 0)
	}
	fmt.Printf("查看进度: ympctl task progress %s\n", fmtCell(payload["taskId"]))
	return 0
}

func mustJSON(v any) []byte {
	b, err := json.Marshal(v)
	if err != nil {
		fail("JSON 序列化失败: %v", err)
	}
	return b
}

func taskSave(args []string) int {
	fs := flag.NewFlagSet("task save", flag.ExitOnError)
	var e taskEnv
	var data string
	addTaskFlags(fs, &e)
	fs.StringVar(&data, "data", "", "配置 JSON 或 @file")
	fs.Parse(args)
	c := taskClient(&e)
	raw := parseDataArg(data)
	if raw == nil {
		fail("需要 --data 提供完整迁移配置 JSON（可先用 task export-config 导出模板）")
	}
	emit(c.PostRaw("yashan/migration/saveTask", raw), e.jsonMode)
	return 0
}

func taskPrecheck(args []string) int {
	fs := flag.NewFlagSet("task precheck", flag.ExitOnError)
	var e taskEnv
	var data string
	addTaskFlags(fs, &e)
	fs.StringVar(&data, "data", "", "请求 JSON 或 @file")
	fs.Parse(args)
	c := taskClient(&e)
	raw := parseDataArg(data)
	if raw == nil {
		fail("需要 --data JSON")
	}
	emit(c.PostRaw("yashan/migration/preCheck", raw), e.jsonMode)
	return 0
}

func taskAction(args []string, endpoint, what string) int {
	fs := flag.NewFlagSet("task "+what, flag.ExitOnError)
	var urlF string
	var timeout int
	var yes bool
	fs.StringVar(&urlF, "url", "", "")
	fs.IntVar(&timeout, "timeout", 0, "")
	fs.BoolVar(&yes, "yes", false, "跳过确认")
	fs.Parse(args)
	pos := fs.Args()
	if len(pos) < 1 {
		fail("需要任务 ID")
	}
	taskID := numInt(pos[0])
	c := newClient(urlF, timeout, false)
	ensureToken(c)
	c.PostRaw("yashan/task/"+endpoint, []byte(fmt.Sprintf("%d", taskID)))
	fmt.Printf("%s指令已下发（taskId=%d，后台异步执行）\n", what, taskID)
	return 0
}

func taskDelete(args []string) int {
	fs := flag.NewFlagSet("task delete", flag.ExitOnError)
	var urlF string
	var timeout int
	var yes bool
	var cascade string
	fs.StringVar(&urlF, "url", "", "")
	fs.IntVar(&timeout, "timeout", 0, "")
	fs.BoolVar(&yes, "yes", false, "跳过确认")
	fs.StringVar(&cascade, "cascade", "", "级联参数 deleteCheck")
	fs.Parse(args)
	pos := fs.Args()
	if len(pos) < 1 {
		fail("需要任务 ID")
	}
	taskID := numInt(pos[0])
	if !yes {
		ans := strings.ToLower(readLine(fmt.Sprintf("确认删除任务 %d？(y/N): ", taskID)))
		if ans != "y" && ans != "yes" {
			fmt.Println("已取消")
			return 0
		}
	}
	c := newClient(urlF, timeout, false)
	ensureToken(c)
	path := fmt.Sprintf("yashan/task/deleteTaskById/%d", taskID)
	if cascade != "" {
		path += "?" + paramsOf("deleteCheck", cascade).Encode()
	}
	c.PostRaw(path, nil)
	fmt.Printf("任务 %d 已删除\n", taskID)
	return 0
}

func taskProgress(args []string) int {
	fs := flag.NewFlagSet("task progress", flag.ExitOnError)
	var e taskEnv
	addTaskFlags(fs, &e)
	fs.Parse(args)
	pos := fs.Args()
	if len(pos) < 1 {
		fail("需要任务 ID: ympctl task progress <task_id>")
	}
	taskID := int(numInt(pos[0]))

	c := taskClient(&e)
	mid := resolveMigrationID(c, e.mid, taskID)
	result := getMap(c.Get("yashan/migration/offlineTask/progress",
		paramsOf("migrationTaskId", fmt.Sprintf("%d", mid))))
	if e.jsonMode {
		emit(result, true)
		return 0
	}
	disp := map[string]any{}
	for k, v := range result {
		disp[k] = v
	}
	if data, ok := disp["data"].(map[string]any); ok {
		dd := map[string]any{}
		for k, v := range data {
			dd[k] = v
		}
		labels := map[string]string{"total": "总量", "success": "已成功",
			"failure": "失败", "unfinished": "未完成"}
		for k, lab := range labels {
			if _, ok := dd[k]; ok {
				dd[k] = fmt.Sprintf("%s (%s)", fmtMB(dd[k]), lab)
			}
		}
		disp["data"] = dd
		fmt.Printf("== 迁移进度 (migrationTaskId=%d，迁移量单位: MB) ==\n", mid)
	}
	printKV(disp, 0)
	return 0
}

func taskMetrics(args []string) int {
	fs := flag.NewFlagSet("task metrics", flag.ExitOnError)
	var e taskEnv
	var hours int
	addTaskFlags(fs, &e)
	fs.IntVar(&hours, "hours", 24, "统计最近 N 小时")
	fs.Parse(args)
	pos := fs.Args()
	if len(pos) < 1 {
		fail("需要任务 ID")
	}
	taskID := int(numInt(pos[0]))
	c := taskClient(&e)
	mid := resolveMigrationID(c, e.mid, taskID)
	result := c.Get("yashan/migration/offlineTask/metrics",
		paramsOf("migrationTaskId", fmt.Sprintf("%d", mid),
			"lastHours", fmt.Sprintf("%d", hours)))
	emit(result, e.jsonMode)
	return 0
}

func taskObjects(args []string) int {
	fs := flag.NewFlagSet("task objects", flag.ExitOnError)
	var e taskEnv
	var page, size int
	addTaskFlags(fs, &e)
	fs.IntVar(&page, "page", 1, "页码")
	fs.IntVar(&size, "size", 200, "每页条数")
	fs.Parse(args)
	pos := fs.Args()
	if len(pos) < 1 {
		fail("需要任务 ID")
	}
	taskID := int(numInt(pos[0]))
	c := taskClient(&e)
	mid := resolveMigrationID(c, e.mid, taskID)
	result := getMap(c.Get("yashan/migration/offlineTask/objects",
		paramsOf("migrationTaskId", fmt.Sprintf("%d", mid),
			"pageNum", fmt.Sprintf("%d", page),
			"pageSize", fmt.Sprintf("%d", size))))
	records := getList(result["records"])
	if e.jsonMode {
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
		row["migrate_size"] = fmt.Sprintf("%s / 总量 %s",
			fmtMB(rm["dataMigrationSize"]), fmtMB(rm["dataTotalSize"]))
		shown = append(shown, row)
	}
	printTable(shown, []col{
		{"sourceSchemaName", "源Schema"}, {"sourceName", "源对象"},
		{"targetSchemaName", "目标Schema"}, {"targetName", "目标对象"},
		{"objectType", "类型"}, {"migrate_size", "迁移量(MB)"},
		{"dataProgress", "进度%"}, {"dataStartTime", "开始"},
		{"dataEndTime", "结束"}, {"failed", "失败"},
	})
	if result["total"] != nil {
		fmt.Printf("共 %s 条\n", fmtCell(result["total"]))
	}
	return 0
}

func taskLog(args []string) int {
	fs := flag.NewFlagSet("task log", flag.ExitOnError)
	var e taskEnv
	var lines int
	var follow bool
	var interval float64
	addTaskFlags(fs, &e)
	fs.IntVar(&lines, "lines", 100, "读取日志行数")
	fs.BoolVar(&follow, "follow", false, "持续轮询新日志")
	fs.Float64Var(&interval, "interval", 3.0, "轮询间隔秒")
	fs.Parse(args)
	pos := fs.Args()
	if len(pos) < 1 {
		fail("需要任务 ID")
	}
	taskID := int(numInt(pos[0]))
	c := taskClient(&e)
	mid := resolveMigrationID(c, e.mid, taskID)
	midStr := fmt.Sprintf("%d", mid)

	if !follow {
		result := c.Get("yashan/migration/task/log",
			paramsOf("migrationTaskId", midStr, "logLine", fmt.Sprintf("%d", lines)))
		emit(result, e.jsonMode)
		return 0
	}
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, os.Interrupt)
	prev := int64(-1)
	for {
		r := getMap(c.Get("yashan/migration/task/log",
			paramsOf("migrationTaskId", midStr, "logLine", fmt.Sprintf("%d", lines))))
		total := numInt(r["logOffset"])
		if prev == -1 {
			fmt.Print(fmtCell(r["log"]))
			prev = total
		} else if total > prev {
			d := getMap(c.Get("yashan/migration/task/log",
				paramsOf("migrationTaskId", midStr,
					"logLine", fmt.Sprintf("%d", total-prev))))
			fmt.Print(fmtCell(d["log"]))
			prev = total
		}
		select {
		case <-sig:
			return 130
		case <-time.After(time.Duration(interval * float64(time.Second))):
		}
	}
}

func taskLogDL(args []string) int {
	fs := flag.NewFlagSet("task log-dl", flag.ExitOnError)
	var e taskEnv
	var output string
	addTaskFlags(fs, &e)
	fs.StringVar(&output, "output", "", "输出文件名")
	fs.StringVar(&output, "o", "", "输出文件名")
	fs.Parse(args)
	pos := fs.Args()
	if len(pos) < 1 {
		fail("需要任务 ID")
	}
	taskID := int(numInt(pos[0]))
	c := taskClient(&e)
	mid := resolveMigrationID(c, e.mid, taskID)
	if output == "" {
		output = fmt.Sprintf("migration-task-%d-log.zip", mid)
	}
	c.GetOut("yashan/migration/task/log/download",
		paramsOf("migrationTaskId", fmt.Sprintf("%d", mid)),
		map[string]string{"Content-Type": "application/zip"}, output)
	fmt.Printf("已下载: %s\n", output)
	return 0
}

func taskExportConfig(args []string) int {
	fs := flag.NewFlagSet("task export-config", flag.ExitOnError)
	var e taskEnv
	var modules, output string
	addTaskFlags(fs, &e)
	fs.StringVar(&modules, "modules", "config", "导出模块: config,objects(逗号分隔)")
	fs.StringVar(&output, "output", "", "输出文件名")
	fs.StringVar(&output, "o", "", "输出文件名")
	fs.Parse(args)
	pos := fs.Args()
	if len(pos) < 1 {
		fail("需要任务 ID")
	}
	taskID := int(numInt(pos[0]))
	c := taskClient(&e)
	mid := resolveMigrationID(c, e.mid, taskID)
	if output == "" {
		output = fmt.Sprintf("migration-config-%d.json", mid)
	}
	mods := []string{}
	for _, m := range strings.Split(modules, ",") {
		if m = strings.TrimSpace(m); m != "" {
			mods = append(mods, m)
		}
	}
	c.PostRawOut("yashan/migration/config/export",
		mustJSON(map[string]any{"migrationId": mid, "moduleTypes": mods}),
		nil, output)
	fmt.Printf("已导出: %s\n", filepath.Clean(output))
	return 0
}

func taskImportConfig(args []string) int {
	fs := flag.NewFlagSet("task import-config", flag.ExitOnError)
	var e taskEnv
	var file string
	addTaskFlags(fs, &e)
	fs.StringVar(&file, "file", "", "配置文件")
	fs.StringVar(&file, "f", "", "配置文件")
	fs.Parse(args)
	if e.mid == 0 {
		fail("需要 -m/--migration-id")
	}
	if file == "" {
		fail("需要 -f/--file")
	}
	c := taskClient(&e)
	body, ctype := writeMigrateImport(e.mid, file)
	res, err := c.Request("POST", "yashan/migration/config/import", nil, body,
		map[string]string{"Content-Type": ctype}, "")
	if err != nil {
		fail("%v", err)
	}
	emit(mustAny(res), e.jsonMode)
	return 0
}

func taskWatch(args []string) int {
	fs := flag.NewFlagSet("task watch", flag.ExitOnError)
	var e taskEnv
	var interval float64
	addTaskFlags(fs, &e)
	fs.Float64Var(&interval, "interval", 5.0, "轮询间隔秒")
	fs.Parse(args)
	pos := fs.Args()
	if len(pos) < 1 {
		fail("需要任务 ID: ympctl task watch <task_id>")
	}
	taskID := int(numInt(pos[0]))

	c := taskClient(&e)
	mid := resolveMigrationID(c, e.mid, taskID)
	doneOK := map[int]bool{9: true, 22: true, 42: true, 48: true}
	doneAny := map[int]bool{8: true, 9: true, 16: true, 22: true, 23: true,
		24: true, 26: true, 42: true, 43: true, 45: true, 48: true,
		49: true, 51: true, 1804: true}
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, os.Interrupt)
	for {
		recs := getList(getMap(c.Get("yashan/task/getTaskList",
			paramsOf("pageNum", "1", "pageSize", "100")))["records"])
		var status any
		for _, r := range recs {
			rm := getMap(r)
			if int(numInt(rm["id"])) == taskID {
				status = rm["taskStatus"]
				break
			}
		}
		prog := getMap(c.Get("yashan/migration/offlineTask/progress",
			paramsOf("migrationTaskId", fmt.Sprintf("%d", mid))))
		data := getMap(prog["data"])
		ts := time.Now().Format("15:04:05")
		fmt.Printf("[%s] 状态=%s(%s) 进度=%s%% 已迁移=%s\n",
			ts, label(taskStatus, status), fmtCell(status),
			pfloat(data["progress"]), fmtMB(data["success"]))
		si := int(numInt(status))
		if doneAny[si] {
			fmt.Printf("任务已进入终态: %s(%d)\n", label(taskStatus, status), si)
			if doneOK[si] {
				return 0
			}
			return 1
		}
		select {
		case <-sig:
			return 130
		case <-time.After(time.Duration(interval * float64(time.Second))):
		}
	}
}

package main

import (
	"encoding/json"
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
)

// ------------------------------------------------- 状态映射

var taskStatus = map[int]string{
	0: "评估初始化", 1: "评估运行中", 2: "评估已停止", 3: "评估完成",
	4: "迁移待配置", 5: "元数据迁移一", 6: "数据迁移中", 7: "元数据迁移二",
	8: "迁移已停止", 9: "迁移完成", 10: "评估刷新中", 11: "迁移运行中",
	12: "获取迁移对象中", 13: "评估刷新已取消", 14: "迁移取消中",
	15: "迁移暂停中", 16: "迁移已暂停",
	20: "校验等待", 21: "校验运行中", 22: "校验完成", 23: "校验失败",
	24: "校验已停止", 25: "校验停止中", 26: "任务创建成功",
	40: "修复等待", 41: "修复运行中", 42: "修复完成", 43: "修复失败",
	44: "修复取消中", 45: "修复已取消",
	46: "复验等待", 47: "复验运行中", 48: "复验完成", 49: "复验失败",
	50: "复验取消中", 51: "复验已取消",
	53: "哈希比对中", 54: "哈希确认中",
	1800: "增量迁移", 1801: "增量迁移编辑", 1802: "增量迁移运行中",
	1803: "增量迁移已暂停", 1804: "增量迁移已停止",
}

var dbType = map[int]string{1: "Oracle", 2: "MySQL", 3: "DM(达梦)", 4: "YashanDB"}

var checkStatus = map[int]string{
	20: "校验等待", 21: "校验运行中", 22: "校验完成", 23: "校验失败",
	24: "校验已停止", 25: "校验停止中", 26: "任务创建成功",
	40: "修复等待", 41: "修复运行中", 42: "修复完成", 43: "修复失败",
	44: "修复取消中", 45: "修复已取消",
	46: "复验等待", 47: "复验运行中", 48: "复验完成", 49: "复验失败",
	50: "复验取消中", 51: "复验已取消",
	53: "哈希比对中", 54: "哈希确认中",
}

var checkResult = map[int]string{0: "一致", 1: "不一致", 2: "存在差异", 3: "未校验"}

// 行级差异类型（来源：YMP 校验报告映射）
var diffType = map[int]string{0: "冗余", 1: "缺失", 2: "差异", 4: "非法值", 5: "校验键为NULL"}

// 表级枚举（与行级不同）
var tableDiffType = map[int]string{1: "数据不一致", 2: "目标表不存在", 3: "结构不一致", 9: "源表不存在"}
var tableCheckResult = map[int]string{0: "一致", 1: "不一致", 6: "校验失败", 7: "不一致", 8: "跳过"}

// numInt: json.Number/float64/int → int64
func numInt(v any) int64 {
	switch x := v.(type) {
	case json.Number:
		n, _ := x.Int64()
		return n
	case float64:
		return int64(x)
	case int:
		return int64(x)
	case int64:
		return x
	case string:
		n, _ := strconv.ParseInt(x, 10, 64)
		return n
	}
	return 0
}

func label(m map[int]string, v any) string {
	return m[int(numInt(v))]
}

// ------------------------------------------------- 输出

func runeWidth(r rune) int {
	if r < 0x80 {
		return 1
	}
	return 2
}

func strWidth(s string) int {
	w := 0
	for _, r := range s {
		w += runeWidth(r)
	}
	return w
}

func pad(s string, w int) string {
	d := w - strWidth(s)
	if d <= 0 {
		return s
	}
	return s + strings.Repeat(" ", d)
}

func fmtCell(v any) string {
	switch x := v.(type) {
	case nil:
		return "-"
	case json.Number:
		return x.String()
	case string:
		return x
	case bool:
		if x {
			return "true"
		}
		return "false"
	case map[string]any, []any:
		b, _ := json.Marshal(x)
		return string(b)
	default:
		return fmt.Sprintf("%v", x)
	}
}

type col struct{ key, header string }

func printTable(rows []map[string]any, cols []col) {
	if len(rows) == 0 {
		fmt.Println("(空)")
		return
	}
	// 无列定义时自动取所有 key
	if cols == nil {
		seen := map[string]bool{}
		var keys []string
		for _, r := range rows {
			for k := range r {
				if !seen[k] {
					seen[k] = true
					keys = append(keys, k)
				}
			}
		}
		sort.Strings(keys)
		cols = make([]col, 0, len(keys))
		for _, k := range keys {
			cols = append(cols, col{k, k})
		}
	}
	widths := make([]int, len(cols))
	for i, c := range cols {
		widths[i] = strWidth(c.header)
	}
	cells := make([][]string, len(rows))
	for ri, r := range rows {
		cells[ri] = make([]string, len(cols))
		for ci, c := range cols {
			s := fmtCell(r[c.key])
			cells[ri][ci] = s
			if w := strWidth(s); w > widths[ci] {
				widths[ci] = w
			}
		}
	}
	head := make([]string, len(cols))
	for i, c := range cols {
		head[i] = pad(c.header, widths[i])
	}
	line := strings.Join(head, "  ")
	fmt.Println(strings.TrimRight(line, " "))
	fmt.Println(strings.Repeat("-", strWidth(line)))
	for _, row := range cells {
		parts := make([]string, len(cols))
		for i := range cols {
			parts[i] = pad(row[i], widths[i])
		}
		fmt.Println(strings.TrimRight(strings.Join(parts, "  "), " "))
	}
}

func printKV(v any, indent int) {
	m, ok := v.(map[string]any)
	if !ok {
		fmt.Printf("%s%s\n", strings.Repeat(" ", indent), fmtCell(v))
		return
	}
	if m == nil {
		fmt.Println("(空)")
		return
	}
	// 稳定排序输出
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	pad0 := strings.Repeat(" ", indent)
	for _, k := range keys {
		val := m[k]
		switch x := val.(type) {
		case map[string]any:
			fmt.Printf("%s%s:\n", pad0, k)
			printKV(x, indent+2)
		case []any:
			if len(x) > 0 && isMapList(x) {
				fmt.Printf("%s%s: (%d 条)\n", pad0, k, len(x))
				rows := make([]map[string]any, len(x))
				for i, it := range x {
					rows[i] = getMap(it)
				}
				printTable(rows, nil)
			} else {
				fmt.Printf("%s%s: %s\n", pad0, k, fmtCell(x))
			}
		default:
			fmt.Printf("%s%s: %s\n", pad0, k, fmtCell(x))
		}
	}
}

func isMapList(l []any) bool {
	for _, it := range l {
		if _, ok := it.(map[string]any); ok {
			return true
		}
	}
	return false
}

func emit(v any, jsonMode bool) {
	if jsonMode {
		b, _ := json.MarshalIndent(v, "", "  ")
		fmt.Println(string(b))
		return
	}
	if v == nil {
		fmt.Println("(空)")
		return
	}
	switch x := v.(type) {
	case map[string]any:
		printKV(x, 0)
	case []any:
		if len(x) > 0 && !isMapList(x) {
			for _, it := range x {
				fmt.Println(fmtCell(it))
			}
			return
		}
		rows := make([]map[string]any, len(x))
		for i, it := range x {
			rows[i] = getMap(it)
		}
		printTable(rows, nil)
	default:
		fmt.Println(fmtCell(x))
	}
}

// fmtMB: YMP 迁移量字段单位为 KB(Oracle 段大小)，换算为 MB 显示
func fmtMB(kbv any) string {
	if kbv == nil {
		return "-"
	}
	kb, err := strconv.ParseFloat(strings.TrimSpace(fmtCell(kbv)), 64)
	if err != nil {
		return fmtCell(kbv)
	}
	mb := kb / 1024.0
	if mb >= 1 {
		return fmt.Sprintf("%.2fMB", mb)
	}
	return fmt.Sprintf("%.2fMB(原始%.0fKB)", mb, kb)
}

// parseRowData: resultDetail 的 sourceData/targetData 为 JSON 数组字符串
func parseRowData(v any) string {
	if v == nil {
		return "-"
	}
	if s, ok := v.(string); ok {
		var arr []any
		if err := json.Unmarshal([]byte(s), &arr); err == nil {
			parts := make([]string, len(arr))
			for i, x := range arr {
				parts[i] = fmtCell(x)
			}
			return strings.Join(parts, ",")
		}
		return s
	}
	return fmtCell(v)
}

func pfloat(v any) string {
	switch x := v.(type) {
	case json.Number:
		return x.String()
	case float64:
		if x == math.Trunc(x) {
			return strconv.FormatInt(int64(x), 10)
		}
		return strconv.FormatFloat(x, 'f', -1, 64)
	}
	return fmtCell(v)
}

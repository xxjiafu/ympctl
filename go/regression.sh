#!/usr/bin/env bash
# ympctl-go 集成回归测试
# 前提: 可访问的 YMP 实例(URL 下可改), 任务1=o2y(迁移完成), 任务2=o2y_check(校验),
#       校验存在真实差异(目标端 EMPLOYEE 多一行)。
# 安全性: 不触发真实迁移(task start 仅测错误路径), 不改密码, 不动数据。
# 用法: bash regression.sh   (退出码=失败数, 0=全部通过)

set -u
EXE="$(cd "$(dirname "$0")" && pwd)/ympctl.exe"
URL="http://192.168.72.149:8090"
USER="admin"
PW="Cod-2022"
PASS=0; FAIL=0
FAILED=()

t() { # t <名称> <期望退出码> <输出须包含的子串,空串跳过> <命令...>
  local name="$1" eexit="$2" pat="$3"; shift 3
  local out code ok=1 reason=""
  out=$("$EXE" "$@" 2>&1); code=$?
  [ "$code" -ne "$eexit" ] && { ok=0; reason="exit=$code(期望$eexit)"; }
  if [ -n "$pat" ] && ! printf '%s' "$out" | grep -qF -- "$pat"; then
    ok=0; reason="$reason 未包含[$pat]"
  fi
  if [ "$ok" = 1 ]; then
    PASS=$((PASS+1)); printf 'PASS  %s\n' "$name"
  else
    FAIL=$((FAIL+1)); FAILED+=("$name: $reason")
    printf 'FAIL  %s  [%s]\n      输出: %s\n' "$name" "$reason" \
      "$(printf '%s' "$out" | head -c 220 | tr '\n' ' ')"
  fi
}

tij() { # tij <名称> <python表达式> <命令...>  —— 校验 --json 输出
  local name="$1" expr="$2"; shift 2
  local out code ok
  out=$("$EXE" "$@" 2>&1); code=$?
  ok=$(printf '%s' "$out" | python -I -c "
import sys, json
try:
    d = json.loads(sys.stdin.read())
    print(1 if ($expr) else 0)
except Exception:
    print(0)" 2>/dev/null)
  if [ "$code" = 0 ] && [ "$ok" = 1 ]; then
    PASS=$((PASS+1)); printf 'PASS  %s\n' "$name"
  else
    FAIL=$((FAIL+1)); FAILED+=("$name: json断言失败 exit=$code")
    printf 'FAIL  %s  [json断言: %s]\n      输出: %s\n' "$name" "$expr" \
      "$(printf '%s' "$out" | head -c 220 | tr '\n' ' ')"
  fi
}

echo "==================== 0. 离线/基础 ===================="
t "version"             0 "go 1.0.0"                    --version
t "encrypt 明文对照"     0 "iMCXJz8toWzYIoMHP61zBg=="    encrypt "x"
t "encrypt 空输入报错"   1 "用法"                        encrypt ""
t "未知命令 exit2"       2 "未知命令"                    nosuch
t "task 无参数给帮助"    0 "task 子命令"                 task

echo "==================== 1. 登录与状态 ===================="
printf '%s\n' "$PW" | "$EXE" login --url "$URL" --user "$USER" --password-stdin >/dev/null 2>&1
t "login password-stdin" 0 "登录成功" login --url "$URL" --user "$USER" --password-stdin < <(printf '%s\n' "$PW")
t "status"               0 "23.5.24.102"               status
t "status 含当前用户"     0 "admin"                     status
tij "status --json"      "d.get('ympVersion')=='23.5.24.102'" status --json

echo "==================== 2. 任务模块(读) ===================="
t "task list"            0 "共 2 条"                    task list
t "task list 含 o2y"      0 "o2y_check"                 task list
tij "task list --json"   "d['total']==2"               task list --json
t "task show 1 --brief"  0 "任务名: o2y"                task show 1 --brief
t "task show 2 含校验"    0 "checkTask"                 task show 2 --brief
tij "task show 2 --json" "d['checkTask']['id']==1"     task show 2 --json
t "task show 99999"      1 "YMP"                       task show 99999
t "task show 缺参"        1 "需要任务 ID"                task show
t "task progress 1"      0 "0.06MB(原始64KB) (已成功)"   task progress 1
tij "task progress --json" "d['data']['total']==64"    task progress 1 --json
t "task progress 99999"  1 "task does not exist"       task progress 99999
t "task metrics 1"       0 "avgRPS"                    task metrics 1
t "task metrics --hours" 0 "currentBPS"                task metrics 1 --hours 1
t "task objects 1"       0 "EMPLOYEE"                  task objects 1
t "task objects MB列"     0 "0.06MB(原始64KB) / 总量"    task objects 1
tij "task objects --json" "d['records'][0]['dataTotalSize']==64" task objects 1 --json
t "task log 1"           0 "logOffset"                 task log 1 --lines 5
t "task log 内容"         0 "migration completed"       task log 1 --lines 30
t "task log-dl 1"        0 "已下载"                     task log-dl 1 -o /tmp/reg_mlog.zip
python -I -m zipfile -t /tmp/reg_mlog.zip >/dev/null 2>&1 \
  && { PASS=$((PASS+1)); echo "PASS  日志zip有效性"; } \
  || { FAIL=$((FAIL+1)); FAILED+=("日志zip有效性"); echo "FAIL  日志zip有效性"; }
t "task export-config"   0 "已导出"                     task export-config 1 -o /tmp/reg_cfg.json
if [ "$(stat -c %s /tmp/reg_cfg.json 2>/dev/null)" = "3621" ]; then
  PASS=$((PASS+1)); echo "PASS  导出配置大小(3621, 与Python一致)"
else
  FAIL=$((FAIL+1)); FAILED+=("导出配置大小"); echo "FAIL  导出配置大小"
fi
t "task watch 1(终态)"    0 "迁移完成(9)"                task watch 1
t "task watch 99999"     1 "task does not exist"       task watch 99999
t "task start 99999"     1 "task does not exist"       task start 99999
t "task start 缺参"       1 "需要任务 ID"                task start
t "task save 缺参"        1 "需要 --data"                task save
t "task stop 99999"      0 "停止指令已下发"              task stop 99999
t "task pause 99999"     1 "YMP"                       task pause 99999
t "task resume 99999"    1 "YMP"                       task resume 99999
t "task delete 99999"    0 "已删除"                     task delete 99999 --yes
t "task import-config 缺参" 1 "需要"                    task import-config

echo "==================== 3. 数据源模块 ===================="
t "ds list"              0 "192.168.72.169:1521/orcl"  ds list
t "ds list 含 yashan"     0 "YashanDB(4)"               ds list
tij "ds list --json"     "d['total']>=2"               ds list --json
t "ds show 1"            0 "192.168.72.169:1521/orcl"  ds show 1
t "ds show 不存在"        0 "(空)"                      ds show 999
t "ds schemas 1"         0 "GSMROOTUSER"               ds schemas 1
t "ds schemas 黑名单"     0 "APPUSER"                   ds schemas 1 --blacklist "GSMROOTUSER"
t "ds test(AES 密文)"     0 "ORACLE data source cannot be connected" ds test --data '{"name":"go-reg","type":1,"connectType":0,"host":"127.0.0.1","port":1521,"userName":"nobody","password":"x","databaseName":"nodb"}'
t "ds add 不可达拒绝"     1 "YMP"                       ds add --data '{"name":"go-reg-ds","type":1,"connectType":0,"host":"127.0.0.1","port":1521,"userName":"nobody","password":"x","databaseName":"nodb"}'
t "ds delete 不存在"      0 "已删除"                     ds delete 999 --yes
t "ds types(本版缺失)"    1 "YMP-00005"                 ds types

echo "==================== 4. 评估模块 ===================="
t "assess history(本版缺失)" 1 "YMP-00005"              assess history
t "assess situation 1"   0 "changeObjAssessmentTaskStats" assess situation 1
t "assess execute 缺参"   1 "需要 --data"                assess execute

echo "==================== 5. 校验模块 ===================="
t "check list"           0 "校验ID"                    check list
t "check list 含任务"     0 "o2y_check"                 check list
t "check info 2 --brief" 0 "校验完成(22)"               check info 2 --brief
t "check info 1(解析)"    0 "checkTaskId=1"             check info 1 --brief
t "check info 99999"     1 "task does not exist"       check info 99999
t "check statistics 2"   0 "校验完成(22)"               check statistics 2
t "check statistics 行数" 0 "totalRows: 2"              check statistics 2
t "check result 1"       0 "差异分类:"                  check result 1
tij "check result JSON"  "d.get('dataInconsistent') is not None" check result 1 --json
t "check tables 2"       0 "APPUSER.EMPLOYEE"          check tables 2
t "check tables 汇总"     0 "共 1 张表"                  check tables 2
t "check rows 1"         0 "条差异行"                   check rows 1
tij "check rows --json"  "d.get('total') is not None"  check rows 1 --json
t "check log 1"          0 ""                          check log 1 --lines 5
t "check log-dl 1"       0 "已下载"                     check log-dl 1 -o /tmp/reg_clog.zip
t "check start 2"        0 "启动指令已受理"              check start 2
# 差异状态动态断言(环境数据可能被重新同步): 输出必须与断言时刻的状态自洽
has_diff_probe() {
  "$EXE" check tables 2 --json 2>/dev/null | python -I -c "
import sys, json
d = json.load(sys.stdin)
print(1 if any(t.get('checkResult') not in (0, None) for t in d.get('tableDetail') or []) else 0)"
}
wout=$("$EXE" check watch 2 2>&1); wcode=$?
has_diff=$(has_diff_probe)
if [ "$wcode" = "$has_diff" ] && printf '%s' "$wout" | grep -qF "校验已进入终态"; then
  PASS=$((PASS+1)); echo "PASS  check watch 2(终态退出码与状态自洽: diff=$has_diff)"
else
  FAIL=$((FAIL+1)); FAILED+=("check watch 2: exit=$wcode 状态=$has_diff")
  echo "FAIL  check watch 2  exit=$wcode 状态=$has_diff"; printf '%s
' "$wout" | tail -2
fi
sout=$("$EXE" check showdiff 2 2>&1); scode=$?
has_diff=$(has_diff_probe)
ok=1; reason=""
[ "$scode" = "$has_diff" ] || { ok=0; reason="exit=$scode 状态=$has_diff"; }
printf '%s' "$sout" | grep -qF "====SHOW DIFF=====" || { ok=0; reason="$reason 缺头部"; }
printf '%s' "$sout" | grep -qF "====CHECK_COMPARE_END=====" || { ok=0; reason="$reason 缺尾部"; }
printf '%s' "$sout" | grep -qF "数据校验对比结果" || { ok=0; reason="$reason 缺节标题"; }
if [ "$has_diff" = 1 ]; then
  printf '%s' "$sout" | grep -qF "[NO]" || { ok=0; reason="$reason 有差异但无[NO]"; }
else
  printf '%s' "$sout" | grep -qF "[NO]" && { ok=0; reason="$reason 无差异却有[NO]"; }
fi
if [ "$ok" = 1 ]; then
  PASS=$((PASS+1)); echo "PASS  check showdiff 2(格式+退出码自洽: diff=$has_diff)"
else
  FAIL=$((FAIL+1)); FAILED+=("check showdiff 2: $reason")
  echo "FAIL  check showdiff 2  [$reason]"
fi
if [ "$has_diff" = 1 ]; then
  d2=$("$EXE" check showdiff 2 --detail --rows 3 2>&1)
  if printf '%s' "$d2" | grep -qF "行数: 源=" && printf '%s' "$d2" | grep -qE '\[(冗余|缺失|差异|非法值)\]'; then
    PASS=$((PASS+1)); echo "PASS  showdiff --detail/--rows 差异明细"
  else
    FAIL=$((FAIL+1)); FAILED+=("showdiff --detail 明细缺失")
    echo "FAIL  showdiff --detail/--rows"; printf '%s
' "$d2" | head -6
  fi
fi
t "check save 缺参"       1 "需要 --data"                check save
t "check repair 缺参"     1 "需要 --data"                check repair

echo "==================== 6. 报告与透传 ===================="
t "report migration 1"   0 "已下载"                     report migration 1 -o /tmp/reg_mrep.zip
sz=$(stat -c %s /tmp/reg_mrep.zip 2>/dev/null || echo 0)
if [ "$sz" -gt 1000000 ]; then
  PASS=$((PASS+1)); echo "PASS  迁移报告大小($sz, 与Python同量级)"
else
  FAIL=$((FAIL+1)); FAILED+=("迁移报告大小"); echo "FAIL  迁移报告大小: $sz"
fi
t "report check 1"       0 "已下载"                     report check 1 -o /tmp/reg_crep.zip
t "report check 99999"   1 "下载失败"                   report check 99999 -o /tmp/reg_bad.zip
t "api GET getInfo"      0 "ympVersion"                api GET yashan/platform/getInfo
tij "api GET 任务列表"     "d['total']==2"               api GET yashan/task/getTaskList --query pageNum=1,pageSize=1
t "api POST stopTaskById" 0 ""                             api POST yashan/task/stopTaskById --data 99999
t "api 非法方法"          1 "不支持的 HTTP 方法"          api FOO yashan/platform/getInfo
t "api 不存在路径"        1 "YMP-00005"                 api GET yashan/nosuch/endpoint

echo "==================== 7. 登出与恢复 ===================="
t "logout"               0 "已登出"                     logout
t "登出后 401 提示"       1 "尚未登录"                   task list
printf '%s\n' "$PW" | "$EXE" login --url "$URL" --user "$USER" --password-stdin >/dev/null 2>&1
t "恢复登录"              0 "共 2 条"                    task list

echo "===================================================="
echo "回归结果: PASS=$PASS FAIL=$FAIL"
if [ "$FAIL" -gt 0 ]; then
  printf '失败项:\n'
  for f in "${FAILED[@]}"; do printf '  - %s\n' "$f"; done
fi
exit "$FAIL"

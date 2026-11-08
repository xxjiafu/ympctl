#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ympctl - YMP (YashanDB Migration Platform) 命令行控制工具

通过 YMP 的 OpenAPI (yashan/* REST 接口) 实现迁移任务的触发、监控与管理。

环境要求: Python 3.7+，无第三方依赖。

快速上手:
    python ympctl.py login --url http://192.168.72.149:8090 --user admin --password-stdin
    python ympctl.py task list
    python ympctl.py task start 1
    python ympctl.py task log 1 --follow

更多: python ympctl.py --help   或   python ympctl.py <group> --help
"""
import argparse
import getpass
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

VERSION = "1.0.0"
CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".ympctl.json")
DEFAULT_URL = "http://192.168.72.149:8090"
SUCCESS_CODE = "YMP-00000"

# ---------------------------------------------------------------- 状态映射

TASK_STATUS = {
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

DB_TYPE = {1: "Oracle", 2: "MySQL", 3: "DM(达梦)", 4: "YashanDB"}

# ---------------------------------------------------------------- 配置与 HTTP


def load_config():
    cfg = {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass


class Client(object):
    """极简 YMP OpenAPI 客户端（基于 urllib，无第三方依赖）。"""

    def __init__(self, base_url, token=None, timeout=60):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def request(self, method, path, params=None, data=None, raw=False,
                headers=None, out_file=None):
        url = self.base_url + "/" + path.lstrip("/")
        if params:
            qs = urllib.parse.urlencode(params, doseq=True)
            url = url + ("&" if "?" in url else "?") + qs
        body = None
        req_headers = {"Accept": "application/json"}
        if self.token:
            req_headers["Access-Token"] = self.token
            req_headers["Authorization"] = self.token
        if data is not None:
            if isinstance(data, (dict, list)):
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            elif isinstance(data, str):
                body = data.encode("utf-8")
            elif isinstance(data, bytes):
                body = data
            else:  # int/float 等：JSON 数字字面量（如 taskId）
                body = str(data).encode("utf-8")
            req_headers["Content-Type"] = "application/json; charset=UTF-8"
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(url, data=body, headers=req_headers,
                                     method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = resp.read()
        except urllib.error.HTTPError as e:
            payload = e.read()
            if e.code == 401:
                die("认证失败(401)：Token 缺失或已过期，请先执行 ympctl login", e)
            if out_file is not None:
                die("下载失败: HTTP %s %s" % (e.code, e.reason), e)
            # 非 401 的 HTTP 错误也尝试按 JSON 解析
        except (urllib.error.URLError, OSError) as e:
            die("连接/传输失败 (%s %s): %s"
                % (method.upper(), path, e), e)

        if out_file is not None:
            # 下载接口出错时服务端可能返回 JSON 错误体，而不是二进制文件
            if payload[:1] == b"{":
                try:
                    err = json.loads(payload.decode("utf-8"))
                    if isinstance(err, dict) and err.get("code") \
                            and err["code"] != SUCCESS_CODE:
                        die("下载失败，YMP 错误 %s: %s"
                            % (err.get("code"), err.get("message")))
                except ValueError:
                    pass
            with open(out_file, "wb") as f:
                f.write(payload)
            return {"file": out_file, "size": len(payload)}
        if not payload:
            return None
        if raw:
            return payload
        try:
            parsed = json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            die("响应不是 JSON（可能接口路径错误），HTTP payload: %s"
                % payload[:200])
        code = parsed.get("code")
        if code != SUCCESS_CODE:
            die("YMP 错误 %s: %s" % (code, parsed.get("message")))
        return parsed.get("result")

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, **kw):
        return self.request("POST", path, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)


def die(msg, err=None):
    if err is not None and os.environ.get("YMP_DEBUG"):
        import traceback
        traceback.print_exc()
    sys.stderr.write("ympctl: 错误: %s\n" % msg)
    sys.exit(1)


def get_client(args):
    cfg = load_config()
    url = getattr(args, "url", None) or os.environ.get("YMP_URL") \
        or cfg.get("url") or DEFAULT_URL
    token = os.environ.get("YMP_TOKEN") or cfg.get("token")
    timeout = int(getattr(args, "timeout", None) or 60)
    if getattr(args, "no_token", False):
        token = None
    return Client(url, token=token, timeout=timeout)


def do_login(client, user, password, save_password=False, cfg=None):
    """执行登录；成功后把 token 写入配置文件。"""
    if not user or not password:
        die("缺少用户名或密码（--user / --password / --password-stdin / 环境变量）")
    pwd_sha = hashlib.sha256(password.encode("utf-8")).hexdigest()
    cfg = cfg or load_config()
    cfg["url"] = client.base_url
    cfg["user"] = user
    if save_password:
        cfg["password"] = password
    else:
        cfg.pop("password", None)
    result = client.request("POST", "yashan/user/login",
                            data={"userName": user, "password": pwd_sha})
    if not result or not result.get("token"):
        die("登录成功但未返回 token: %s" % result)
    cfg["token"] = result["token"]
    cfg["login_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_config(cfg)
    return result


def ensure_token(client, args):
    """token 缺失时，若有保存的密码/环境变量则自动重登。"""
    if client.token:
        return
    cfg = load_config()
    user = cfg.get("user") or os.environ.get("YMP_USER")
    password = cfg.get("password") or os.environ.get("YMP_PASSWORD")
    if user and password:
        do_login(client, user, password, cfg=cfg)
        client.token = cfg["token"]
    else:
        die("尚未登录或 Token 失效，请先执行: ympctl login")


# ---------------------------------------------------------------- 输出辅助


def emit(data, json_mode=False):
    if json_mode:
        print(json.dumps(data, ensure_ascii=False, indent=2,
                         default=str))
        return
    if data is None:
        print("(空)")
        return
    if isinstance(data, list):
        print_table(data)
    elif isinstance(data, dict):
        print_kv(data)
    else:
        print(data)


def fmt_cell(v):
    if v is None:
        return "-"
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)





def print_table(records, columns=None):
    """简单对齐的表格输出。columns: [(key, 显示名), ...]"""
    if not records:
        print("(空)")
        return
    if columns is None:
        if not isinstance(records[0], dict):  # 字符串等标量列表直接逐行输出
            for item in records:
                print(fmt_cell(item))
            return
        keys, seen = [], set()
        for r in records:
            if isinstance(r, dict):
                for k in r:
                    if k not in seen:
                        seen.add(k)
                        keys.append(k)
        columns = [(k, k) for k in keys]
    rows = []
    for r in records:
        if not isinstance(r, dict):
            rows.append([fmt_cell(r)])
            continue
        rows.append([fmt_cell(r.get(k)) for k, _ in columns])

    headers = [n for _, n in columns]
    widths = []
    for i, h in enumerate(headers):
        w = _width(h)
        for row in rows:
            w = max(w, _width(row[i]) if i < len(row) else 0)
        widths.append(w)
    line = "  ".join(_pad(h, widths[i]) for i, h in enumerate(headers))
    print(line)
    print("-" * _width(line))
    for row in rows:
        print("  ".join(
            _pad(row[i] if i < len(row) else "-", widths[i])
            for i in range(len(headers))))


def _width(s):
    return sum(2 if ord(c) > 127 else 1 for c in s)


def _pad(s, w):
    return s + " " * max(0, w - _width(s))


def print_kv(d, indent=0):
    pad = " " * indent
    for k, v in d.items():
        if isinstance(v, dict):
            print("%s%s:" % (pad, k))
            print_kv(v, indent + 2)
        elif isinstance(v, list) and v and isinstance(v[0], dict):
            print("%s%s: (%d 条)" % (pad, k, len(v)))
            print_table(v)
        else:
            print("%s%s: %s" % (pad, k, fmt_cell(v)))


def parse_data_arg(args):
    """--data 支持: JSON 字符串 / @file.json / - (stdin)。"""
    data = getattr(args, "data", None)
    if data is None:
        return None
    if data == "-":
        return json.load(sys.stdin)
    if data.startswith("@"):
        with open(data[1:], "r", encoding="utf-8") as f:
            return json.load(f)
    try:
        return json.loads(data)
    except ValueError as e:
        die("--data 不是合法 JSON: %s" % e)


def add_common(p):
    p.add_argument("--url", help="YMP 地址（默认取配置/环境变量 %s）" % DEFAULT_URL)
    p.add_argument("--timeout", type=int, help="HTTP 超时秒数")


# ---------------------------------------------------------------- 命令组


def cmd_login(args):
    client = get_client(args)
    password = args.password
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    if not password:
        password = os.environ.get("YMP_PASSWORD") \
            or getpass.getpass("YMP 密码: ")
    result = do_login(client, args.user, password,
                      save_password=args.save_password)
    cfg = load_config()
    print("登录成功: %s (user=%s)" % (client.base_url, cfg.get("user")))
    print("Token 已保存到 %s" % CONFIG_FILE)
    if args.save_password:
        print("警告: 密码已明文保存在配置文件中，仅供自动化使用")


def cmd_logout(args):
    client = get_client(args)
    if client.token:
        try:
            client.post("yashan/user/logout")
        except SystemExit:
            pass
    cfg = load_config()
    cfg.pop("token", None)
    save_config(cfg)
    print("已登出并清除本地 Token")


def cmd_status(args):
    client = get_client(args)
    info = client.get("yashan/platform/getInfo")
    if args.json:
        emit(info, True)
        return
    rows = [
        ("YMP 地址", client.base_url),
        ("YMP 版本", info.get("ympVersion")),
        ("YashanDB 版本", info.get("yashanDBVersion")),
        ("yasldr 版本", info.get("yasldrVersion")),
        ("JDBC 版本", info.get("jdbcVersion")),
        ("OCI 版本", info.get("ociVersion")),
    ]
    for k, v in rows:
        if v:
            print("%-16s %s" % (k + ":", v))
    cfg = load_config()
    if cfg.get("user"):
        u = client.get("yashan/user/info",
                       params={"userName": cfg["user"]})
        print("%-16s %s (状态=%s)" % ("当前用户:", u.get("userName"),
                                     u.get("status")))


def cmd_passwd(args):
    client = get_client(args)
    ensure_token(client, args)
    cfg = load_config()
    user = args.user or cfg.get("user")
    old = args.old or getpass.getpass("当前密码: ")
    new = args.new or getpass.getpass("新密码: ")
    if not args.new and new != getpass.getpass("确认新密码: "):
        die("两次输入的新密码不一致")
    client.post("yashan/user/password", data={
        "userName": user,
        "oldPassword": hashlib.sha256(old.encode()).hexdigest(),
        "newPassword": hashlib.sha256(new.encode()).hexdigest(),
    })
    cfg["user"], cfg["password"] = user, new
    do_login(client, user, new, cfg=cfg)
    print("密码修改成功，已重新登录")


# ---------------------------- 迁移任务


def resolve_migration_id(client, args):
    """--migration-id 显式给定，否则从任务基础信息推断。"""
    mid = args.migration_id
    if mid is not None:
        return int(mid)
    base = client.get("yashan/task/getTaskBaseInfo/%d" % args.task_id)
    mt = base.get("migrationTask") or {}
    if mt.get("id"):
        return int(mt["id"])
    die("任务 %s 尚无迁移子任务(migrationTask)，无法定位 migrationTaskId；"
        "请先在向导中保存迁移配置，或用 --migration-id 显式指定" % args.task_id)


def cmd_task_list(args):
    client = get_client(args)
    ensure_token(client, args)
    params = {"pageNum": args.page, "pageSize": args.size}
    if args.name:
        params["taskName"] = args.name
    result = client.get("yashan/task/getTaskList", params=params)
    records = result.get("records") or []
    if args.json:
        emit(result, True)
        return
    cols = [
        ("id", "ID"), ("taskName", "任务名"),
        ("sourceDbType", "源库"), ("targetDsId", "目标DS"),
        ("taskStage", "阶段"), ("taskStatus", "状态"),
        ("taskProgress", "进度%"), ("startTime", "开始时间"),
    ]
    shown = []
    for r in records:
        r = dict(r)
        r["sourceDbType"] = "%s(%s)" % (DB_TYPE.get(r.get("sourceDbType"),
                                                   "?"), r.get("sourceDbType"))
        st = r.get("taskStatus")
        r["taskStatus"] = "%s(%s)" % (TASK_STATUS.get(st, "?"), st)
        shown.append(r)
    print_table(shown, cols)
    print("共 %s 条，第 %s/%s 页" % (result.get("total"),
                                    result.get("current"),
                                    result.get("pages")))


def cmd_task_show(args):
    client = get_client(args)
    ensure_token(client, args)
    base = client.get("yashan/task/getTaskBaseInfo/%d" % args.task_id)
    if args.json:
        emit(base, True)
        return
    task = base.get("task") or {}
    st = task.get("taskStatus")
    print("== 任务 %s ==" % args.task_id)
    print_kv({
        "任务名": task.get("taskName"),
        "状态": "%s(%s)" % (TASK_STATUS.get(st, "?"), st),
        "进度": task.get("taskProgress"),
        "源库类型": DB_TYPE.get(task.get("sourceDbType"), "?"),
        "源数据源": (base.get("sourceDSInfo") or {}).get("connectStr"),
        "目标数据源": (base.get("targetDSInfo") or {}).get("connectStr"),
        "开始时间": task.get("startTime"),
        "migrationTaskId": (base.get("migrationTask") or {}).get("id"),
        "checkTask": base.get("checkTask"),
        "备注": task.get("remark"),
    })
    extra = {k: v for k, v in base.items()
             if k not in ("task", "sourceDSInfo", "targetDSInfo") and v}
    if extra and not args.brief:
        print("-- 其他信息 --")
        print_kv(extra)


def cmd_task_get(args, path_tmpl, params=None):
    client = get_client(args)
    ensure_token(client, args)
    mid = resolve_migration_id(client, args)
    result = client.get(path_tmpl, params=params or {"migrationTaskId": mid})
    emit(result, args.json)


def cmd_task_start(args):
    """触发迁移任务：POST yashan/migration/startTask

    与前端向导一致：先取已保存的迁移配置(offlineTask/config)合并后提交，
    否则服务端会因 targetDataSourceId 等为空而报错。
    """
    client = get_client(args)
    ensure_token(client, args)
    payload = parse_data_arg(args)
    if payload is None:
        mid = resolve_migration_id(client, args)
        config = client.get("yashan/migration/offlineTask/config",
                            params={"migrationTaskId": mid,
                                    "taskId": args.task_id}) or {}
        payload = dict(config)
        payload.update({
            "taskId": args.task_id,
            "migrationTaskId": mid,
            "needAssessment": config.get("needAssessment", False),
            "forceCreate": bool(args.force),
        })
    if payload.get("migrationTaskId") is None and args.migration_id:
        payload["migrationTaskId"] = args.migration_id
    result = client.post("yashan/migration/startTask", data=payload)
    if args.json:
        emit(result, True)
        return
    print("迁移任务已触发（taskId=%s, migrationTaskId=%s）"
          % (args.task_id, payload.get("migrationTaskId")))
    if result:
        print_kv(result)
    print("查看进度: ympctl task progress %s" % args.task_id)


def cmd_task_save(args):
    """保存/更新迁移任务配置: POST yashan/migration/saveTask（完整向导 JSON）"""
    client = get_client(args)
    ensure_token(client, args)
    payload = parse_data_arg(args)
    if payload is None:
        die("需要 --data 提供完整迁移配置 JSON（可先用 task export-config 导出模板）")
    result = client.post("yashan/migration/saveTask", data=payload)
    emit(result, args.json)


def cmd_task_precheck(args):
    client = get_client(args)
    ensure_token(client, args)
    payload = parse_data_arg(args)
    if payload is None:
        die("需要 --data JSON")
    result = client.post("yashan/migration/preCheck", data=payload)
    emit(result, args.json)


def cmd_task_stop(args):
    client = get_client(args)
    ensure_token(client, args)
    client.post("yashan/task/stopTaskById", data=args.task_id)
    print("停止指令已下发（taskId=%s，后台异步终止）" % args.task_id)


def cmd_task_suspend(args):
    client = get_client(args)
    ensure_token(client, args)
    client.post("yashan/task/suspendTaskById", data=args.task_id)
    print("暂停指令已下发（taskId=%s）" % args.task_id)


def cmd_task_resume(args):
    client = get_client(args)
    ensure_token(client, args)
    client.post("yashan/task/recoverTaskById", data=args.task_id)
    print("恢复指令已下发（taskId=%s）" % args.task_id)


def cmd_task_delete(args):
    client = get_client(args)
    ensure_token(client, args)
    if not args.yes:
        confirm = input("确认删除任务 %s？(y/N): " % args.task_id)
        if confirm.strip().lower() not in ("y", "yes"):
            print("已取消")
            return
    params = {}
    if args.cascade is not None:
        params = {"deleteCheck": args.cascade}
    client.post("yashan/task/deleteTaskById/%d" % args.task_id,
                params=params)
    print("任务 %s 已删除" % args.task_id)


def cmd_task_log(args):
    client = get_client(args)
    ensure_token(client, args)
    mid = resolve_migration_id(client, args)
    lines = args.lines or 100
    if args.follow:
        shown = 0
        try:
            while True:
                result = client.get(
                    "yashan/migration/task/log",
                    params={"migrationTaskId": mid, "logLine": lines})
                new_lines = result.get("logs") or result.get("logList") or []
                if isinstance(new_lines, list):
                    for ln in new_lines[shown:]:
                        print(fmt_cell(ln))
                    shown = len(new_lines)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            return
    result = client.get("yashan/migration/task/log",
                        params={"migrationTaskId": mid, "logLine": lines})
    emit(result, args.json)


def cmd_task_download_log(args):
    client = get_client(args)
    ensure_token(client, args)
    mid = resolve_migration_id(client, args)
    out = args.output or ("migration-task-%s-log.zip" % mid)
    client.get("yashan/migration/task/log/download",
               params={"migrationTaskId": mid}, out_file=out,
               headers={"Content-Type": "application/zip"})
    print("已下载: %s" % out)


def cmd_task_export_config(args):
    client = get_client(args)
    ensure_token(client, args)
    mid = resolve_migration_id(client, args)
    out = args.output or ("migration-config-%s.json" % mid)
    modules = [m.strip() for m in (args.modules or "config").split(",")
               if m.strip()]
    client.post("yashan/migration/config/export",
                data={"migrationId": mid, "moduleTypes": modules},
                out_file=out, raw=True)
    print("已导出: %s" % out)


def cmd_task_import_config(args):
    client = get_client(args)
    ensure_token(client, args)
    boundary = "----ympctl%s" % int(time.time() * 1000)
    with open(args.file, "rb") as f:
        content = f.read()
    body = (
        ("--%s\r\nContent-Disposition: form-data; name=\"migrationId\"\r\n\r\n%s\r\n"
         % (boundary, args.migration_id)).encode("utf-8")
        + ("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
           "Content-Type: application/octet-stream\r\n\r\n"
           % (boundary, os.path.basename(args.file))).encode("utf-8")
        + content + ("\r\n--%s--\r\n" % boundary).encode("utf-8"))
    result = client.post("yashan/migration/config/import", data=body,
                         headers={"Content-Type":
                                  "multipart/form-data; boundary=" + boundary})
    emit(result, args.json)








def cmd_task_watch(args):
    """轮询直到任务进入终态(脚本等待迁移结束用)，退出码 0=成功终态。"""
    client = get_client(args)
    ensure_token(client, args)
    mid = resolve_migration_id(client, args)
    done_ok = {9, 22, 42, 48}
    done_any = {8, 9, 16, 22, 23, 24, 26, 42, 43, 45, 48, 49, 51, 1804}
    try:
        while True:
            recs = client.get("yashan/task/getTaskList",
                              params={"pageNum": 1, "pageSize": 100})
            rec = next((r for r in (recs.get("records") or [])
                        if r.get("id") == args.task_id), None)
            status = (rec or {}).get("taskStatus")
            prog = client.get("yashan/migration/offlineTask/progress",
                              params={"migrationTaskId": mid})
            data = (prog or {}).get("data") or {}
            ts = time.strftime("%H:%M:%S")
            print("[%s] 状态=%s(%s) 进度=%s%% 已迁移(KB)=%s"
                  % (ts, TASK_STATUS.get(status, "?"), status,
                     data.get("progress"), data.get("success")))
            if status in done_any:
                print("任务已进入终态: %s(%s)" % (TASK_STATUS.get(status, "?"),
                                                 status))
                return 0 if status in done_ok else 1
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 130


# ---------------------------- 数据源


def cmd_ds_list(args):
    client = get_client(args)
    ensure_token(client, args)
    result = client.get("yashan/dataSource/getDatasourceList")
    records = result.get("records") if isinstance(result, dict) else result
    if args.json:
        emit(result, True)
        return
    cols = [("id", "ID"), ("name", "名称"), ("type", "类型"),
            ("version", "版本"), ("connectStr", "连接串"),
            ("userName", "用户"), ("createTime", "创建时间")]
    shown = []
    for r in records or []:
        r = dict(r)
        r["type"] = "%s(%s)" % (DB_TYPE.get(r.get("type"), "?"), r.get("type"))
        shown.append(r)
    print_table(shown, cols)


def cmd_ds_item(args):
    client = get_client(args)
    ensure_token(client, args)
    result = client.get("yashan/dataSource/getDatasourceList")
    records = result.get("records") if isinstance(result, dict) else result
    match = [r for r in (records or []) if r.get("id") == args.ds_id]
    emit(match[0] if match else None, args.json)


def cmd_ds_action(args, path):
    client = get_client(args)
    ensure_token(client, args)
    payload = parse_data_arg(args)
    if payload is None:
        die("需要 --data JSON（数据源参数）")
    result = client.post(path, data=payload)
    emit(result, args.json)


def cmd_ds_delete(args):
    client = get_client(args)
    ensure_token(client, args)
    if not args.yes:
        confirm = input("确认删除数据源 %s？(y/N): " % args.ds_id)
        if confirm.strip().lower() not in ("y", "yes"):
            print("已取消")
            return
    client.post("yashan/dataSource/deleteDatasource/%d" % args.ds_id)
    print("数据源 %s 已删除" % args.ds_id)


def cmd_ds_schemas(args):
    client = get_client(args)
    ensure_token(client, args)
    if args.blacklist is not None:
        bl = [s for s in args.blacklist.split(",") if s] or ["__all__"]
        result = client.get(
            "yashan/dataSource/getSchemasWithBlackList/%d" % args.ds_id,
            params={"blackList": bl})
    else:
        result = client.get("yashan/dataSource/getSchemas/%d" % args.ds_id)
    emit(result, args.json)


def cmd_ds_types(args):
    client = get_client(args)
    ensure_token(client, args)
    emit(client.get("yashan/dataSource/getConvertDBType/"), args.json)


# ---------------------------- 评估任务


def cmd_assess_history(args):
    client = get_client(args)
    ensure_token(client, args)
    params = {k: v for k, v in
              (("pageNum", args.page), ("pageSize", args.size)) if v}
    result = client.get("yashan/objAssessmentTask/getHistoryLog",
                        params=params)
    records = result.get("records") if isinstance(result, dict) else result
    if args.json:
        emit(result, True)
        return
    print_table(records or [], [("id", "评估ID"), ("taskName", "名称"),
                                ("taskStatus", "状态"),
                                ("sourceDbType", "源库"),
                                ("startTime", "开始时间"),
                                ("updateTime", "更新时间")])


def cmd_assess_cmd(args, path, method="GET", params=None):
    client = get_client(args)
    ensure_token(client, args)
    payload = parse_data_arg(args)
    if method == "GET":
        result = client.get(path, params=params)
    else:
        if payload is None:
            die("需要 --data JSON")
        result = client.post(path, data=payload)
    emit(result, args.json)


# ---------------------------- 数据校验


def cmd_check_list(args):
    client = get_client(args)
    ensure_token(client, args)
    payload = parse_data_arg(args)
    if payload is None:
        payload = {"pageNum": args.page, "pageSize": args.size}
    result = client.post("yashan/check/task/obj/list", data=payload)
    emit(result, args.json)


def cmd_check_info(args):
    client = get_client(args)
    ensure_token(client, args)
    result = client.get("yashan/check/status/info/%d" % args.check_id)
    emit(result, args.json)


def cmd_check_statistics(args):
    client = get_client(args)
    ensure_token(client, args)
    result = client.get("yashan/check/status/statistics/%d" % args.check_id)
    emit(result, args.json)


def cmd_check_result(args):
    client = get_client(args)
    ensure_token(client, args)
    result = client.get("yashan/check/status/result/%d" % args.check_id)
    emit(result, args.json)











def cmd_check_log(args):
    client = get_client(args)
    ensure_token(client, args)
    params = {"checkTaskId": args.check_id}
    if args.lines:
        params["logLine"] = args.lines
    result = client.get("yashan/check/status/log/view", params=params)
    emit(result, args.json)


def cmd_check_download_log(args):
    client = get_client(args)
    ensure_token(client, args)
    out = args.output or ("check-task-%s-log.zip" % args.check_id)
    client.get("yashan/check/status/log/download",
               params={"checkTaskId": args.check_id}, out_file=out,
               headers={"Content-Type": "application/zip"})
    print("已下载: %s" % out)


def cmd_check_action_id(args, path_tmpl, confirm_msg=None):
    client = get_client(args)
    ensure_token(client, args)
    if confirm_msg and not args.yes:
        if input(confirm_msg).strip().lower() not in ("y", "yes"):
            print("已取消")
            return
    result = client.post(path_tmpl % args.check_id)
    emit(result, args.json)





def cmd_check_cmd(args, path):
    client = get_client(args)
    ensure_token(client, args)
    payload = parse_data_arg(args)
    if payload is None:
        die("需要 --data JSON")
    result = client.post(path, data=payload)
    emit(result, args.json)


# ---------------------------- 报告


def cmd_report_migration(args):
    client = get_client(args)
    ensure_token(client, args)
    out = args.output or ("migration-report-%s.zip" % args.migration_id)
    client.get("yashan/reportDownload/migrationReport",
               params={"migrationTaskId": args.migration_id},
               out_file=out, headers={"Content-Type": "application/zip"})
    print("已下载: %s" % out)


def cmd_report_check(args):
    client = get_client(args)
    ensure_token(client, args)
    out = args.output or ("check-report-%s.zip" % args.check_id)
    client.get("yashan/reportDownload/getCheckTaskReport/%d" % args.check_id,
               out_file=out, headers={"Content-Type": "application/zip"})
    print("已下载: %s" % out)


# ---------------------------- 原始 API 透传





def cmd_api(args):
    client = get_client(args)
    ensure_token(client, args)
    params = {}
    if args.query:
        for kv in args.query.split(","):
            if "=" in kv:
                k, v = kv.split("=", 1)
                params[k] = v
    data = None
    if args.data is not None:
        d = args.data
        if d == "-":
            data = sys.stdin.buffer.read()
        elif d.startswith("@"):
            with open(d[1:], "rb") as f:
                data = f.read()
        else:
            data = d
    result = client.request(args.method.upper(), args.path, params=params,
                            data=data, raw=args.raw)
    if args.raw:
        sys.stdout.buffer.write(result)
    else:
        emit(result, True)


# ---------------------------------------------------------------- 参数解析


def build_parser():
    ap = argparse.ArgumentParser(
        prog="ympctl",
        description="YMP (YashanDB Migration Platform) 命令行控制工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n"
               "  ympctl login --url http://192.168.72.149:8090 --user admin\n"
               "  ympctl task list\n"
               "  ympctl task start 1\n"
               "  ympctl task watch 1\n"
               "  ympctl api GET yashan/dataSource/getDatasourceList\n")
    ap.add_argument("--version", action="version",
                    version="ympctl %s" % VERSION)
    sub = ap.add_subparsers(dest="group")

    # --- 登录/系统
    p = sub.add_parser("login", help="登录并保存 Token")
    p.add_argument("--user", default=os.environ.get("YMP_USER"),
                   help="用户名")
    p.add_argument("--password", help="密码（建议用 --password-stdin）")
    p.add_argument("--password-stdin", action="store_true",
                   help="从 stdin 读取密码")
    p.add_argument("--save-password", action="store_true",
                   help="明文保存密码到配置文件（自动化场景，慎用）")
    add_common(p)
    p.set_defaults(func=cmd_login)

    p = sub.add_parser("logout", help="登出并清除本地 Token")
    add_common(p)
    p.set_defaults(func=cmd_logout)

    p = sub.add_parser("status", help="查看 YMP 平台版本与登录状态")
    p.add_argument("--json", action="store_true", help="输出原始 JSON")
    add_common(p)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("passwd", help="修改当前用户密码")
    p.add_argument("--user")
    p.add_argument("--old", help="旧密码")
    p.add_argument("--new", help="新密码")
    add_common(p)
    p.set_defaults(func=cmd_passwd)

    # --- 迁移任务
    tp = sub.add_parser("task", help="迁移任务：列表/详情/触发/停止/日志")
    tsub = tp.add_subparsers(dest="action")

    p = tsub.add_parser("list", help="任务列表")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--size", type=int, default=20)
    p.add_argument("--name", help="按任务名过滤")
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=cmd_task_list)

    p = tsub.add_parser("show", help="任务详情（含源/目标数据源）")
    p.add_argument("task_id", type=int, help="任务 ID")
    p.add_argument("--json", action="store_true")
    p.add_argument("--brief", action="store_true", help="只显示概要")
    add_common(p)
    p.set_defaults(func=cmd_task_show)

    p = tsub.add_parser("start", help="触发迁移任务(启动)")
    p.add_argument("task_id", type=int, nargs="?", help="任务 ID")
    p.add_argument("-m", "--migration-id", type=int,
                   help="迁移子任务 ID(默认自动推断)")
    p.add_argument("--force", action="store_true",
                   help="forceCreate=true")
    p.add_argument("--data", help="完整启动请求 JSON（覆盖默认简单参数）")
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=cmd_task_start)

    p = tsub.add_parser("save", help="保存迁移任务配置(完整向导 JSON)")
    p.add_argument("--data", help="配置 JSON 或 @file")
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=cmd_task_save)

    p = tsub.add_parser("precheck", help="迁移前检查")
    p.add_argument("--data", help="请求 JSON 或 @file")
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=cmd_task_precheck)

    p = tsub.add_parser("stop", help="停止/终止任务")
    p.add_argument("task_id", type=int)
    add_common(p)
    p.set_defaults(func=cmd_task_stop)

    p = tsub.add_parser("pause", help="暂停任务")
    p.add_argument("task_id", type=int)
    add_common(p)
    p.set_defaults(func=cmd_task_suspend)

    p = tsub.add_parser("resume", help="恢复已暂停任务")
    p.add_argument("task_id", type=int)
    add_common(p)
    p.set_defaults(func=cmd_task_resume)

    p = tsub.add_parser("delete", help="删除任务")
    p.add_argument("task_id", type=int)
    p.add_argument("--yes", action="store_true", help="跳过确认")
    p.add_argument("--cascade", type=int, help="级联参数 deleteCheck")
    add_common(p)
    p.set_defaults(func=cmd_task_delete)

    p = tsub.add_parser("progress", help="迁移进度")
    p.add_argument("task_id", type=int, nargs="?")
    p.add_argument("-m", "--migration-id", type=int)
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=lambda a: cmd_task_get(
        a, "yashan/migration/offlineTask/progress"))

    p = tsub.add_parser("metrics", help="迁移指标")
    p.add_argument("task_id", type=int, nargs="?")
    p.add_argument("-m", "--migration-id", type=int)
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=lambda a: cmd_task_get(
        a, "yashan/migration/offlineTask/metrics"))

    p = tsub.add_parser("objects", help="迁移对象列表")
    p.add_argument("task_id", type=int, nargs="?")
    p.add_argument("-m", "--migration-id", type=int)
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=lambda a: cmd_task_get(
        a, "yashan/migration/offlineTask/objects"))

    p = tsub.add_parser("log", help="查看迁移日志")
    p.add_argument("task_id", type=int, nargs="?")
    p.add_argument("-m", "--migration-id", type=int)
    p.add_argument("--lines", type=int, default=100,
                   help="读取日志行数(默认100)")
    p.add_argument("--follow", action="store_true", help="持续轮询新日志")
    p.add_argument("--interval", type=float, default=3.0)
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=cmd_task_log)

    p = tsub.add_parser("log-dl", help="下载迁移日志 zip")
    p.add_argument("task_id", type=int, nargs="?")
    p.add_argument("-m", "--migration-id", type=int)
    p.add_argument("-o", "--output", help="输出文件名")
    add_common(p)
    p.set_defaults(func=cmd_task_download_log)

    p = tsub.add_parser("export-config", help="导出迁移配置(可作新任务模板)")
    p.add_argument("task_id", type=int, nargs="?")
    p.add_argument("-m", "--migration-id", type=int)
    p.add_argument("--modules", default="config",
                   help="导出模块: config,objects(逗号分隔)")
    p.add_argument("-o", "--output", help="输出文件名")
    add_common(p)
    p.set_defaults(func=cmd_task_export_config)

    p = tsub.add_parser("import-config", help="导入迁移配置")
    p.add_argument("-m", "--migration-id", type=int, required=True)
    p.add_argument("-f", "--file", required=True, help="配置文件")
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=cmd_task_import_config)

    p = tsub.add_parser("watch", help="轮询直至终态(脚本等待迁移结束)")
    p.add_argument("task_id", type=int, help="任务 ID")
    p.add_argument("-m", "--migration-id", type=int)
    p.add_argument("--interval", type=float, default=5.0)
    p.add_argument("--json", action="store_true",
                   help="每轮输出原始 JSON")
    add_common(p)
    p.set_defaults(func=cmd_task_watch)

    # --- 数据源
    dp = sub.add_parser("ds", help="数据源管理")
    dsub = dp.add_subparsers(dest="action")

    p = dsub.add_parser("list", help="数据源列表")
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=cmd_ds_list)

    p = dsub.add_parser("show", help="数据源详情")
    p.add_argument("ds_id", type=int)
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=cmd_ds_item)

    p = dsub.add_parser("add", help="新增数据源")
    p.add_argument("--data", help="数据源 JSON 或 @file(password 会自动加密)")
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=lambda a: cmd_ds_action(
        a, "yashan/dataSource/addDatasource"))

    p = dsub.add_parser("refresh", help="刷新/更新数据源信息")
    p.add_argument("--data", help="数据源 JSON 或 @file(password 会自动加密)")
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=lambda a: cmd_ds_action(
        a, "yashan/dataSource/refreshDatasource"))

    p = dsub.add_parser("test", help="测试数据源连通性")
    p.add_argument("--data", help="数据源 JSON 或 @file(password 会自动加密)")
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=lambda a: cmd_ds_action(
        a, "yashan/dataSource/testConnection"))

    p = dsub.add_parser("delete", help="删除数据源")
    p.add_argument("ds_id", type=int)
    p.add_argument("--yes", action="store_true")
    add_common(p)
    p.set_defaults(func=cmd_ds_delete)

    p = dsub.add_parser("schemas", help="列出数据源 schema")
    p.add_argument("ds_id", type=int)
    p.add_argument("--blacklist", help="逗号分隔的黑名单(传空串=全部)")
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=cmd_ds_schemas)

    p = dsub.add_parser("types", help="支持的目标库类型")
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=cmd_ds_types)

    # --- 评估
    gp = sub.add_parser("assess", help="对象评估任务")
    gsub = gp.add_subparsers(dest="action")

    p = gsub.add_parser("history", help="评估历史记录")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--size", type=int, default=20)
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=cmd_assess_history)

    p = gsub.add_parser("situation", help="评估对象总体情况")
    p.add_argument("assess_id", type=int)
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=lambda a: cmd_assess_cmd(
        a, "yashan/objAssessmentTask/getAllObjSituation/%d" % a.assess_id))

    p = gsub.add_parser("abstract", help="评估摘要情况")
    p.add_argument("assess_id", type=int)
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=lambda a: cmd_assess_cmd(
        a, "yashan/objAssessmentTask/getTaskAbstractSituation/%d"
        % a.assess_id))

    p = gsub.add_parser("objects", help="评估对象明细")
    p.add_argument("--data", help="查询参数 JSON")
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=lambda a: cmd_assess_cmd(
        a, "yashan/objAssessmentTask/getObjAssessmentSituation"))

    p = gsub.add_parser("execute", help="执行对象评估")
    p.add_argument("--data", help="请求 JSON 或 @file")
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=lambda a: cmd_assess_cmd(
        a, "yashan/objAssessmentTask/executeObjAssessmentTask", "POST"))

    p = gsub.add_parser("save", help="保存评估任务")
    p.add_argument("--data", help="请求 JSON 或 @file")
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=lambda a: cmd_assess_cmd(
        a, "yashan/objAssessmentTask/saveObjAssessmentTask", "POST"))

    # --- 校验
    cp = sub.add_parser("check", help="数据校验任务")
    csub = cp.add_subparsers(dest="action")

    p = csub.add_parser("list", help="校验对象列表")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--size", type=int, default=20)
    p.add_argument("--data", help="查询 JSON（覆盖默认分页）")
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=cmd_check_list)

    p = csub.add_parser("info", help="校验任务状态信息")
    p.add_argument("check_id", type=int)
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=cmd_check_info)

    p = csub.add_parser("statistics", help="校验统计")
    p.add_argument("check_id", type=int)
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=cmd_check_statistics)

    p = csub.add_parser("result", help="校验结果")
    p.add_argument("check_id", type=int)
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=cmd_check_result)

    p = csub.add_parser("log", help="校验日志")
    p.add_argument("check_id", type=int)
    p.add_argument("--lines", type=int)
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=cmd_check_log)

    p = csub.add_parser("log-dl", help="下载校验日志 zip")
    p.add_argument("check_id", type=int)
    p.add_argument("-o", "--output")
    add_common(p)
    p.set_defaults(func=cmd_check_download_log)

    p = csub.add_parser("save", help="创建校验任务")
    p.add_argument("--data", help="校验任务 JSON 或 @file")
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=lambda a: cmd_check_cmd(
        a, "yashan/check/task/save"))

    p = csub.add_parser("start", help="启动校验任务")
    p.add_argument("check_id", type=int)
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=lambda a: cmd_check_action_id(
        a, "yashan/check/task/start/%d"))

    p = csub.add_parser("stop", help="取消校验任务")
    p.add_argument("check_id", type=int)
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=lambda a: cmd_check_action_id(
        a, "yashan/check/task/cancel/%d"))

    p = csub.add_parser("repair", help="校验修复(需 --data)")
    p.add_argument("--data", help="请求 JSON 或 @file")
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=lambda a: cmd_check_cmd(
        a, "yashan/check/task/repair"))

    p = csub.add_parser("revalidate", help="校验复验(需 --data)")
    p.add_argument("--data", help="请求 JSON 或 @file")
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=lambda a: cmd_check_cmd(
        a, "yashan/check/task/revalidate"))

    # --- 报告
    rp = sub.add_parser("report", help="报告下载")
    rsub = rp.add_subparsers(dest="action")

    p = rsub.add_parser("migration", help="下载迁移报告")
    p.add_argument("migration_id", type=int)
    p.add_argument("-o", "--output")
    add_common(p)
    p.set_defaults(func=cmd_report_migration)

    p = rsub.add_parser("check", help="下载校验报告")
    p.add_argument("check_id", type=int)
    p.add_argument("-o", "--output")
    add_common(p)
    p.set_defaults(func=cmd_report_check)

    # --- 原始 API
    p = sub.add_parser("api", help="原始 API 透传（覆盖未封装接口）")
    p.add_argument("method", choices=["GET", "POST", "DELETE", "PUT"])
    p.add_argument("path", help="如 yashan/task/getTaskList")
    p.add_argument("--query", help="查询参数: k1=v1,k2=v2")
    p.add_argument("--data", help="请求体: JSON 字符串 / @file / - (stdin)")
    p.add_argument("--raw", action="store_true", help="原样输出响应字节")
    add_common(p)
    p.set_defaults(func=cmd_api)

    return ap


def main():
    ap = build_parser()
    args = ap.parse_args()
    if not hasattr(args, "func"):
        ap.print_help()
        return
    rc = args.func(args) or 0
    sys.exit(rc)


if __name__ == "__main__":
    main()

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
import base64
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

# ---------------------------------------------------------------- 密码加密
# YMP 数据源密码使用 AES-128-CBC + ZeroPadding，输出 Base64，
# key 与 IV 均为 "1234567890123456"（与 YMP 前端 crypto-js 行为一致）。

YMP_AES_KEY = b"1234567890123456"

_SBOX = (
    0x63, 0x7C, 0x77, 0x7B, 0xF2, 0x6B, 0x6F, 0xC5, 0x30, 0x01, 0x67, 0x2B,
    0xFE, 0xD7, 0xAB, 0x76, 0xCA, 0x82, 0xC9, 0x7D, 0xFA, 0x59, 0x47, 0xF0,
    0xAD, 0xD4, 0xA2, 0xAF, 0x9C, 0xA4, 0x72, 0xC0, 0xB7, 0xFD, 0x93, 0x26,
    0x36, 0x3F, 0xF7, 0xCC, 0x34, 0xA5, 0xE5, 0xF1, 0x71, 0xD8, 0x31, 0x15,
    0x04, 0xC7, 0x23, 0xC3, 0x18, 0x96, 0x05, 0x9A, 0x07, 0x12, 0x80, 0xE2,
    0xEB, 0x27, 0xB2, 0x75, 0x09, 0x83, 0x2C, 0x1A, 0x1B, 0x6E, 0x5A, 0xA0,
    0x52, 0x3B, 0xD6, 0xB3, 0x29, 0xE3, 0x2F, 0x84, 0x53, 0xD1, 0x00, 0xED,
    0x20, 0xFC, 0xB1, 0x5B, 0x6A, 0xCB, 0xBE, 0x39, 0x4A, 0x4C, 0x58, 0xCF,
    0xD0, 0xEF, 0xAA, 0xFB, 0x43, 0x4D, 0x33, 0x85, 0x45, 0xF9, 0x02, 0x7F,
    0x50, 0x3C, 0x9F, 0xA8, 0x51, 0xA3, 0x40, 0x8F, 0x92, 0x9D, 0x38, 0xF5,
    0xBC, 0xB6, 0xDA, 0x21, 0x10, 0xFF, 0xF3, 0xD2, 0xCD, 0x0C, 0x13, 0xEC,
    0x5F, 0x97, 0x44, 0x17, 0xC4, 0xA7, 0x7E, 0x3D, 0x64, 0x5D, 0x19, 0x73,
    0x60, 0x81, 0x4F, 0xDC, 0x22, 0x2A, 0x90, 0x88, 0x46, 0xEE, 0xB8, 0x14,
    0xDE, 0x5E, 0x0B, 0xDB, 0xE0, 0x32, 0x3A, 0x0A, 0x49, 0x06, 0x24, 0x5C,
    0xC2, 0xD3, 0xAC, 0x62, 0x91, 0x95, 0xE4, 0x79, 0xE7, 0xC8, 0x37, 0x6D,
    0x8D, 0xD5, 0x4E, 0xA9, 0x6C, 0x56, 0xF4, 0xEA, 0x65, 0x7A, 0xAE, 0x08,
    0xBA, 0x78, 0x25, 0x2E, 0x1C, 0xA6, 0xB4, 0xC6, 0xE8, 0xDD, 0x74, 0x1F,
    0x4B, 0xBD, 0x8B, 0x8A, 0x70, 0x3E, 0xB5, 0x66, 0x48, 0x03, 0xF6, 0x0E,
    0x61, 0x35, 0x57, 0xB9, 0x86, 0xC1, 0x1D, 0x9E, 0xE1, 0xF8, 0x98, 0x11,
    0x69, 0xD9, 0x8E, 0x94, 0x9B, 0x1E, 0x87, 0xE9, 0xCE, 0x55, 0x28, 0xDF,
    0x8C, 0xA1, 0x89, 0x0D, 0xBF, 0xE6, 0x42, 0x68, 0x41, 0x99, 0x2D, 0x0F,
    0xB0, 0x54, 0xBB, 0x16)

_RCON = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36)


def _xt(a):
    a <<= 1
    if a & 0x100:
        a ^= 0x11B
    return a & 0xFF


def _aes128_expand(key):
    w = [list(key[4 * i:4 * i + 4]) for i in range(4)]
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[b] for b in t]
            t[0] ^= _RCON[i // 4 - 1]
        w.append([a ^ b for a, b in zip(w[i - 4], t)])
    return w


def _aes128_enc_block(blk, w):
    s = [blk[i] ^ w[i // 4][i % 4] for i in range(16)]  # AddRoundKey(0)
    for rnd in range(1, 11):
        s = [_SBOX[b] for b in s]                        # SubBytes
        ns = list(s)                                     # ShiftRows
        for r in range(1, 4):
            for c in range(4):
                ns[4 * c + r] = s[4 * ((c + r) % 4) + r]
        s = ns
        if rnd != 10:                                    # MixColumns
            for c in range(4):
                a0, a1, a2, a3 = s[4 * c:4 * c + 4]
                s[4 * c + 0] = _xt(a0) ^ _xt(a1) ^ a1 ^ a2 ^ a3
                s[4 * c + 1] = a0 ^ _xt(a1) ^ _xt(a2) ^ a2 ^ a3
                s[4 * c + 2] = a0 ^ a1 ^ _xt(a2) ^ _xt(a3) ^ a3
                s[4 * c + 3] = _xt(a0) ^ a0 ^ a1 ^ a2 ^ _xt(a3)
        for c in range(4):                               # AddRoundKey
            for j in range(4):
                s[4 * c + j] ^= w[4 * rnd + c][j]
    return s


def ymp_encrypt_password(text):
    """与 YMP 前端一致的 AES-128-CBC/ZeroPadding/Base64 加密。"""
    if not text:
        return ""
    key = YMP_AES_KEY
    iv = YMP_AES_KEY
    w = _aes128_expand(key)
    data = text.encode("utf-8")
    data += b"\x00" * (16 - len(data) % 16)  # crypto-js ZeroPadding(对齐也补整块)
    out = bytearray()
    prev = iv
    for i in range(0, len(data), 16):
        blk = [b ^ p for b, p in zip(data[i:i + 16], prev)]
        ct = _aes128_enc_block(blk, w)
        out.extend(ct)
        prev = bytes(ct)
    return base64.b64encode(bytes(out)).decode("ascii")


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


def fmt_mb(kb):
    """YMP 的迁移量字段单位是 KB(Oracle 段大小)，换算为 MB 显示。"""
    if kb is None:
        return "-"
    try:
        kb = float(kb)
    except (TypeError, ValueError):
        return str(kb)
    mb = kb / 1024.0
    if mb >= 1:
        return "%.2fMB" % mb
    return "%.2fMB(原始%.0fKB)" % (mb, kb)


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
    if params is None:
        params = {"migrationTaskId": mid}
    elif params.get("migrationTaskId") is None:
        params = dict(params, migrationTaskId=mid)
    result = client.get(path_tmpl, params=params)
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


def cmd_task_progress(args):
    """迁移进度；迁移量字段单位为 KB，换算为 MB 显示。"""
    client = get_client(args)
    ensure_token(client, args)
    mid = resolve_migration_id(client, args)
    result = client.get("yashan/migration/offlineTask/progress",
                        params={"migrationTaskId": mid})
    if args.json:
        emit(result, True)
        return
    disp = dict(result) if isinstance(result, dict) else result
    if isinstance(disp, dict) and isinstance(disp.get("data"), dict):
        dd = dict(disp["data"])
        for k in ("total", "success", "failure", "unfinished"):
            if k in dd:
                label = {"total": "总量", "success": "已成功",
                         "failure": "失败", "unfinished": "未完成"}[k]
                dd[k] = "%s (%s)" % (fmt_mb(dd[k]), label)
        disp["data"] = dd
        print("== 迁移进度 (migrationTaskId=%s，迁移量单位: MB) ==" % mid)
    print_kv(disp)


def cmd_task_objects(args):
    """迁移对象列表；迁移量列换算为 MB 显示。"""
    client = get_client(args)
    ensure_token(client, args)
    mid = resolve_migration_id(client, args)
    result = client.get("yashan/migration/offlineTask/objects",
                        params={"pageNum": args.page, "pageSize": args.size,
                                "migrationTaskId": mid})
    records = result.get("records") if isinstance(result, dict) else result
    if args.json:
        emit(result, True)
        return
    shown = []
    for r in records or []:
        r = dict(r)
        r["migrate_size"] = "%s / 总量 %s" % (
            fmt_mb(r.get("dataMigrationSize")), fmt_mb(r.get("dataTotalSize")))
        shown.append(r)
    print_table(shown, [
        ("sourceSchemaName", "源Schema"), ("sourceName", "源对象"),
        ("targetSchemaName", "目标Schema"), ("targetName", "目标对象"),
        ("objectType", "类型"), ("migrate_size", "迁移量(MB)"),
        ("dataProgress", "进度%"), ("dataStartTime", "开始"),
        ("dataEndTime", "结束"), ("failed", "失败"),
    ])
    if isinstance(result, dict) and result.get("total") is not None:
        print("共 %s 条" % result.get("total"))


def cmd_task_watch(args):
    """轮询直到任务进入终态(脚本等待迁移结束用)，退出码 0=成功终态。"""
    client = get_client(args)
    ensure_token(client, args)
    mid = resolve_migration_id(client, args)
    done_ok = {9, 22, 42, 48}                 # 完成/校验成功/修复完成/复验完成
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
            print("[%s] 状态=%s(%s) 进度=%s%% 已迁移=%s"
                  % (ts, TASK_STATUS.get(status, "?"), status,
                     data.get("progress"), fmt_mb(data.get("success"))))
            if status in done_any:
                print("任务已进入终态: %s(%s)" % (TASK_STATUS.get(status, "?"),
                                                 status))
                return 0 if status in done_ok else 1
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 130


CHECK_STATUS = {
    20: "校验等待", 21: "校验运行中", 22: "校验完成", 23: "校验失败",
    24: "校验已停止", 25: "校验停止中", 26: "任务创建成功",
    40: "修复等待", 41: "修复运行中", 42: "修复完成", 43: "修复失败",
    44: "修复取消中", 45: "修复已取消",
    46: "复验等待", 47: "复验运行中", 48: "复验完成", 49: "复验失败",
    50: "复验取消中", 51: "复验已取消",
    53: "哈希比对中", 54: "哈希确认中",
}

CHECK_RESULT = {0: "一致", 1: "不一致", 2: "存在差异", 3: "未校验"}

# 行级差异类型（来源：YMP 校验报告 Ize 映射）
DIFF_TYPE = {0: "冗余", 1: "缺失", 2: "差异", 4: "非法值", 5: "校验键为NULL"}

# 表级枚举（与行级不同：detail.tableDetail.diffTypes / checkResult）
TABLE_DIFF_TYPE = {1: "数据不一致", 2: "目标表不存在", 3: "结构不一致",
                   9: "源表不存在"}
TABLE_CHECK_RESULT = {0: "一致", 1: "不一致", 6: "校验失败", 7: "不一致",
                      8: "跳过"}


def _parse_row_data(v):
    """resultDetail 的 sourceData/targetData 是 JSON 数组字符串，转可读文本。"""
    if v is None:
        return "-"
    if isinstance(v, str):
        try:
            arr = json.loads(v)
            if isinstance(arr, list):
                return ",".join(str(x) for x in arr)
        except ValueError:
            pass
        return v
    if isinstance(v, list):
        return ",".join(str(x) for x in v)
    return str(v)


def resolve_check_id(client, args):
    """把主任务 ID 或校验子任务 ID 统一解析为 (checkTaskId, checkTask)。

    优先按主任务 ID 查 getTaskBaseInfo 取嵌套的 checkTask；若该主任务
    没有校验子任务，则把给定值当作 checkTaskId，并反查主任务补全信息。
    """
    cid = args.check_id
    base = client.get("yashan/task/getTaskBaseInfo/%d" % cid)
    ct = (base or {}).get("checkTask") or {}
    if ct.get("id"):
        return int(ct["id"]), ct
    info = client.get("yashan/check/status/info/%d" % cid)
    if info and info.get("id"):
        for r in (client.get("yashan/task/getTaskList",
                             params={"pageNum": 1, "pageSize": 100})
                  .get("records") or []):
            try:
                b = client.get("yashan/task/getTaskBaseInfo/%d" % r["id"])
            except SystemExit:
                continue
            t = (b or {}).get("checkTask") or {}
            if t.get("id") == int(info["id"]):
                merged = dict(t)
                merged.update(info)
                return int(info["id"]), merged
        return int(info["id"]), info
    die("任务 %s 不是校验任务(无 checkTask 子任务)，也无法作为 checkTaskId "
        "定位；请用 check list 查看可用的校验任务" % cid)


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
    if isinstance(payload, dict) and payload.get("password") \
            and not getattr(args, "plain_password", False):
        # YMP 前端对数据源密码做 AES 加密后再提交
        payload["password"] = ymp_encrypt_password(str(payload["password"]))
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
    """列出校验任务(主任务ID + checkTaskId + 状态)，便于取 start 用的 ID。"""
    client = get_client(args)
    ensure_token(client, args)
    result = client.get("yashan/task/getTaskList",
                        params={"pageNum": args.page, "pageSize": 100})
    records = result.get("records") if isinstance(result, dict) else result
    if args.json:
        emit(result, True)
        return
    shown = []
    for r in records or []:
        try:
            base = client.get("yashan/task/getTaskBaseInfo/%d" % r["id"])
        except SystemExit:
            continue  # 单个任务详情失败不阻塞列表
        ct = (base or {}).get("checkTask")
        if not ct and not args.all:
            continue
        if ct:
            cs = ct.get("checkStatus")
            shown.append({
                "headTaskId": r.get("id"),
                "headTaskName": r.get("taskName"),
                "checkTaskId": ct.get("id"),
                "checkTaskName": ct.get("checkTaskName"),
                "checkStatus": "%s(%s)" % (CHECK_STATUS.get(cs, "?"), cs),
                "checkProcess": ct.get("checkProcess"),
                "checkResult": CHECK_RESULT.get(ct.get("checkResult"),
                                                ct.get("checkResult")),
                "startTime": ct.get("startTime"),
            })
        else:
            shown.append({"headTaskId": r.get("id"),
                          "headTaskName": r.get("taskName"),
                          "checkTaskId": "-",
                          "checkStatus": "(无校验子任务)"})
    print_table(shown, [
        ("headTaskId", "主任务ID"), ("headTaskName", "主任务名"),
        ("checkTaskId", "校验ID"), ("checkTaskName", "校验名"),
        ("checkStatus", "校验状态"), ("checkProcess", "进度%"),
        ("checkResult", "结果"), ("startTime", "开始时间"),
    ])
    print("提示: check start/stop/info 等命令的 ID 接受上面任一 ID，"
          "会自动解析")


def cmd_check_info(args):
    client = get_client(args)
    ensure_token(client, args)
    cid, ct = resolve_check_id(client, args)
    result = client.get("yashan/check/status/info/%d" % cid) or {}
    merged = dict(ct) if isinstance(ct, dict) else {}
    merged.update(result)
    if args.json:
        emit(merged, True)
        return
    st = merged.get("checkStatus")
    print("== 校验任务 %s (checkTaskId=%s) ==" % (
        merged.get("checkTaskName"), cid))
    print_kv({
        "状态": "%s(%s)" % (CHECK_STATUS.get(st, "?"), st),
        "结果": CHECK_RESULT.get(merged.get("checkResult"),
                                 merged.get("checkResult")),
        "进度": merged.get("checkProcess"),
        "开始时间": merged.get("startTime"),
        "结束时间": merged.get("endTime"),
        "校验类型": merged.get("checkType"),
        "schema": merged.get("schemaList"),
    })
    if not args.brief:
        extra = {k: v for k, v in merged.items()
                 if k not in ("checkTaskName", "checkStatus", "checkResult",
                              "checkProcess", "startTime", "endTime",
                              "source", "target", "checkTaskConfig") and v}
        if extra:
            print("-- 其他 --")
            print_kv(extra)


def cmd_check_statistics(args):
    client = get_client(args)
    ensure_token(client, args)
    cid, _ = resolve_check_id(client, args)
    result = client.get("yashan/check/status/statistics/%d" % cid)
    if args.json:
        emit(result, True)
        return
    disp = dict(result) if isinstance(result, dict) else result
    if isinstance(disp, dict):
        disp["status"] = "%s(%s)" % (CHECK_STATUS.get(disp.get("status"), "?"),
                                     disp.get("status"))
        disp["result"] = CHECK_RESULT.get(disp.get("result"),
                                          disp.get("result"))
        rpi = disp.get("rowProgressInfo")
        if isinstance(rpi, dict):
            rpi = dict(rpi)
            rpi["progress"] = "%s%%" % rpi.get("progress")
            disp["rowProgressInfo"] = rpi
    print("== 校验统计 (checkTaskId=%s) ==" % cid)
    print_kv(disp)


def cmd_check_result(args):
    """单表校验结果汇总：含不一致列名(diffColNames)、行数与差异分类计数。"""
    client = get_client(args)
    ensure_token(client, args)
    result = client.get("yashan/check/status/result/%d" % args.check_obj_id)
    if args.json:
        emit(result, True)
        return
    inc = result.get("dataInconsistent") or {}
    print("== 单表校验结果 (checkObjId=%s) ==" % args.check_obj_id)
    print_kv({
        "对比": "一致" if result.get("same") else "不一致",
        "源行数": result.get("sourceRow"),
        "目标行数": result.get("targetRow"),
        "差异行数": result.get("diffRows"),
        "不一致列名": result.get("diffColNames") or "-",
        "源主键": result.get("sourcePkName") or "-",
        "目标主键": result.get("targetPkName") or "-",
        "差异分类": {
            "冗余(目标端多出)": inc.get("notInSourceNum"),
            "缺失(目标端缺少)": inc.get("notInTargetNum"),
            "数据不一致": inc.get("diffNum"),
            "非法值": inc.get("invalidNum"),
            "校验键为NULL": inc.get("uniqueKeyNullNum"),
        },
    })
    if result.get("sourceLobColumn"):
        print("LOB 列: %s" % ",".join(result["sourceLobColumn"]))
    if result.get("errorMessage"):
        print("错误: %s" % result["errorMessage"])


def cmd_check_tables(args):
    """表级校验结果列表：哪些表不一致(checkResult=1)一目了然。"""
    client = get_client(args)
    ensure_token(client, args)
    cid, _ = resolve_check_id(client, args)
    result = client.get("yashan/check/status/detail",
                        params={"checkTaskId": cid, "pageNum": args.page,
                                "pageSize": args.size})
    tables = result.get("tableDetail") or []
    if args.json:
        emit(result, True)
        return
    shown = []
    for t in tables:
        t = dict(t)
        t["source_table"] = "%s.%s" % (t.get("sourceSchemaName"),
                                       t.get("sourceTable"))
        t["target_table"] = "%s.%s" % (t.get("targetSchemaName"),
                                       t.get("targetTable"))
        cr = t.get("checkResult")
        t["checkResult"] = TABLE_CHECK_RESULT.get(cr, cr)
        dt = t.get("diffTypes")
        t["diffTypes"] = TABLE_DIFF_TYPE.get(dt, dt)
        shown.append(t)
    print_table(shown, [
        ("source_table", "源表"), ("target_table", "目标表"),
        ("checkResult", "结果"), ("diffTypes", "差异类型"),
        ("sourceRowCount", "源行数"), ("targetRowCount", "目标行数"),
        ("checkProgress", "进度%"), ("objectStatus", "状态"),
    ])
    print("共 %s 张表" % result.get("total"))


def cmd_check_showdiff(args):
    """按对比报告格式输出：[NO] 源表 == 目标表；发现差异时退出码为 1。"""
    client = get_client(args)
    ensure_token(client, args)
    cid, ct = resolve_check_id(client, args)
    result = client.get("yashan/check/status/detail",
                        params={"checkTaskId": cid, "pageNum": 1,
                                "pageSize": args.size})
    tables = result.get("tableDetail") or []
    print("====SHOW DIFF=====")
    print("数据校验对比结果")
    has_diff = False
    for t in tables:
        bad = t.get("checkResult") not in (0, None)
        if bad:
            has_diff = True
        elif not args.all:
            continue
        print("%s %s.%s == %s.%s" % (
            "[NO]" if bad else "[OK]",
            t.get("sourceSchemaName"), t.get("sourceTable"),
            t.get("targetSchemaName"), t.get("targetTable")))
        if bad and args.detail:
            summ = client.get("yashan/check/status/result/%d" % t["id"]) or {}
            inc = summ.get("dataInconsistent") or {}
            print("    行数: 源=%s 目标=%s 差异行=%s"
                  % (summ.get("sourceRow"), summ.get("targetRow"),
                     summ.get("diffRows")))
            cats = [("冗余(目标多出)", inc.get("notInSourceNum")),
                    ("缺失(目标缺少)", inc.get("notInTargetNum")),
                    ("数据不一致", inc.get("diffNum")),
                    ("非法值", inc.get("invalidNum")),
                    ("校验键为NULL", inc.get("uniqueKeyNullNum"))]
            print("    分类: %s" % "  ".join(
                "%s=%s" % (k, v) for k, v in cats if v))
            cols = summ.get("diffColNames") or []
            print("    不一致列: %s" % (",".join(cols) if cols else "-"))
            if args.rows:
                rd = client.get("yashan/check/status/resultDetail",
                                params={"checkObjId": t["id"], "pageNum": 1,
                                        "pageSize": args.rows})
                for r in (rd.get("records") or []):
                    print("    [%s] 源=%s / 目标=%s 差异列=%s" % (
                        DIFF_TYPE.get(r.get("resultType"),
                                      r.get("resultType")),
                        _parse_row_data(r.get("sourceData")),
                        _parse_row_data(r.get("targetData")),
                        r.get("diffColName") or "-"))
    print("====CHECK_COMPARE_END=====")
    return 1 if has_diff else 0


def cmd_check_rows(args):
    """行级差异明细：冗余/缺失/不一致的具体行数据与差异列。"""
    client = get_client(args)
    ensure_token(client, args)
    result = client.get("yashan/check/status/resultDetail",
                        params={"checkObjId": args.check_obj_id,
                                "pageNum": args.page, "pageSize": args.size})
    records = result.get("records") if isinstance(result, dict) else result
    if args.json:
        emit(result, True)
        return
    shown = []
    for r in records or []:
        r = dict(r)
        r["resultType"] = DIFF_TYPE.get(r.get("resultType"),
                                        r.get("resultType"))
        r["sourceData"] = _parse_row_data(r.get("sourceData"))
        r["targetData"] = _parse_row_data(r.get("targetData"))
        shown.append(r)
    print_table(shown, [
        ("resultType", "差异类型"), ("sourcePk", "源主键"),
        ("targetPk", "目标主键"), ("sourceData", "源数据"),
        ("targetData", "目标数据"), ("diffColName", "差异列"),
    ])
    if isinstance(result, dict) and result.get("total") is not None:
        print("共 %s 条差异行" % result.get("total"))


def cmd_check_log(args):
    client = get_client(args)
    ensure_token(client, args)
    cid, _ = resolve_check_id(client, args)
    params = {"checkTaskId": cid}
    if args.lines:
        params["logLine"] = args.lines
    result = client.get("yashan/check/status/log/view", params=params)
    emit(result, args.json)


def cmd_check_download_log(args):
    client = get_client(args)
    ensure_token(client, args)
    cid, _ = resolve_check_id(client, args)
    out = args.output or ("check-task-%s-log.zip" % cid)
    client.get("yashan/check/status/log/download",
               params={"checkTaskId": cid}, out_file=out,
               headers={"Content-Type": "application/zip"})
    print("已下载: %s" % out)


def cmd_check_action_id(args, path_tmpl, confirm_msg=None, what=""):
    client = get_client(args)
    ensure_token(client, args)
    cid, _ = resolve_check_id(client, args)
    if confirm_msg and not args.yes:
        if input(confirm_msg).strip().lower() not in ("y", "yes"):
            print("已取消")
            return
    result = client.post(path_tmpl % cid)
    if args.json:
        emit(result, True)
        return
    print("%s指令已受理（checkTaskId=%s）" % (what, cid))
    if isinstance(result, (dict, list)):
        print_kv(result)
    print("查看状态: ympctl check info %s   统计: ympctl check statistics %s"
          % (cid, cid))


def cmd_check_watch(args):
    """轮询校验任务直至终态(脚本等待用)，退出码 0=校验通过。"""
    client = get_client(args)
    ensure_token(client, args)
    cid, _ = resolve_check_id(client, args)
    done_ok = {22, 42, 48}
    done_any = {20, 21, 22, 23, 24, 25, 40, 41, 42, 43, 44, 45,
                46, 47, 48, 49, 50, 51, 53, 54}
    try:
        while True:
            result = client.get("yashan/check/status/statistics/%d" % cid)
            st = result.get("status")
            rpi = result.get("rowProgressInfo") or {}
            ts = time.strftime("%H:%M:%S")
            print("[%s] 状态=%s(%s) 行进度=%s%% 结果=%s (行 %s/%s, 失败 %s)"
                  % (ts, CHECK_STATUS.get(st, "?"), st,
                     rpi.get("progress"),
                     CHECK_RESULT.get(result.get("result"),
                                      result.get("result")),
                     rpi.get("completeRows"), rpi.get("totalRows"),
                     rpi.get("failedRows")))
            if st in done_any:
                print("校验已进入终态: %s(%s)" % (CHECK_STATUS.get(st, "?"), st))
                ok = st in done_ok and result.get("result") in (0, 4)
                return 0 if ok else 1
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 130


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


def cmd_encrypt(args):
    """把明文按 YMP 数据源密码加密算法处理，输出 Base64 密文。"""
    text = args.text
    if text == "-":
        text = sys.stdin.readline().rstrip("\r\n")
    print(ymp_encrypt_password(text))


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

    p = tsub.add_parser("progress", help="迁移进度(迁移量换算为MB)")
    p.add_argument("task_id", type=int, nargs="?", help="任务 ID")
    p.add_argument("-m", "--migration-id", type=int)
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=cmd_task_progress)

    p = tsub.add_parser("metrics", help="迁移指标")
    p.add_argument("task_id", type=int, nargs="?")
    p.add_argument("-m", "--migration-id", type=int)
    p.add_argument("--hours", type=int, default=24,
                   help="统计最近 N 小时(默认24)")
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=lambda a: cmd_task_get(
        a, "yashan/migration/offlineTask/metrics",
        params={"migrationTaskId": None, "lastHours": a.hours}))

    p = tsub.add_parser("objects", help="迁移对象列表(迁移量换算为MB)")
    p.add_argument("task_id", type=int, nargs="?")
    p.add_argument("-m", "--migration-id", type=int)
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--size", type=int, default=200)
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=cmd_task_objects)

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
    p.add_argument("--plain-password", action="store_true",
                   help="不加密 password 字段(已手工加密时使用)")
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=lambda a: cmd_ds_action(
        a, "yashan/dataSource/addDatasource"))

    p = dsub.add_parser("refresh", help="刷新/更新数据源信息")
    p.add_argument("--data", help="数据源 JSON 或 @file(password 会自动加密)")
    p.add_argument("--plain-password", action="store_true")
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=lambda a: cmd_ds_action(
        a, "yashan/dataSource/refreshDatasource"))

    p = dsub.add_parser("test", help="测试数据源连通性")
    p.add_argument("--data", help="数据源 JSON 或 @file(password 会自动加密)")
    p.add_argument("--plain-password", action="store_true")
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

    p = csub.add_parser("list", help="校验任务列表(含 checkTaskId)")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--all", action="store_true",
                   help="也显示无校验子任务的主任务")
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=cmd_check_list)

    p = csub.add_parser("info", help="校验任务状态信息")
    p.add_argument("check_id", type=int,
                   help="主任务ID或checkTaskId，自动解析")
    p.add_argument("--brief", action="store_true")
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=cmd_check_info)

    p = csub.add_parser("statistics", help="校验统计")
    p.add_argument("check_id", type=int)
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=cmd_check_statistics)

    p = csub.add_parser("result", help="单表校验结果汇总(含不一致列名)")
    p.add_argument("check_obj_id", type=int,
                   help="表对象ID，来自 check tables 列表的 id 列")
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=cmd_check_result)

    p = csub.add_parser("tables", help="表级校验结果(哪些表不一致)")
    p.add_argument("check_id", type=int,
                   help="主任务ID或checkTaskId，自动解析")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--size", type=int, default=200)
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=cmd_check_tables)

    p = csub.add_parser("showdiff", help="对比报告格式输出([NO] 源表==目标表)")
    p.add_argument("check_id", type=int,
                   help="主任务ID或checkTaskId，自动解析")
    p.add_argument("--all", action="store_true",
                   help="一致表也输出([OK]行，默认只输出[NO])")
    p.add_argument("--detail", action="store_true",
                   help="每张差异表追加行数/分类/不一致列")
    p.add_argument("--rows", type=int, default=0,
                   help="每表附带行级差异示例条数(配合 --detail)")
    p.add_argument("--size", type=int, default=500)
    add_common(p)
    p.set_defaults(func=cmd_check_showdiff)

    p = csub.add_parser("rows", help="行级差异明细")
    p.add_argument("check_obj_id", type=int,
                   help="表对象ID，来自 check tables 列表的 id 列")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--size", type=int, default=50)
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=cmd_check_rows)

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

    p = csub.add_parser("start", help="触发/重跑校验任务")
    p.add_argument("check_id", type=int,
                   help="主任务ID或checkTaskId，自动解析")
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=lambda a: cmd_check_action_id(
        a, "yashan/check/task/start/%d", what="启动"))

    p = csub.add_parser("stop", help="取消校验任务")
    p.add_argument("check_id", type=int)
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=lambda a: cmd_check_action_id(
        a, "yashan/check/task/cancel/%d", what="取消"))

    p = csub.add_parser("watch", help="轮询校验直至终态(0=通过)")
    p.add_argument("check_id", type=int)
    p.add_argument("--interval", type=float, default=3.0)
    p.add_argument("--json", action="store_true")
    add_common(p)
    p.set_defaults(func=cmd_check_watch)

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

    # --- 密码加密工具
    p = sub.add_parser("encrypt", help="按 YMP 算法加密数据源密码")
    p.add_argument("text", help="明文，或 '-' 从 stdin 读入")
    p.set_defaults(func=cmd_encrypt)

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

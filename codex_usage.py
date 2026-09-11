# -*- coding: utf-8 -*-
# 创建时间: 2026-09-10
# 功能: 查询本机 Codex(GPT) 剩余用量与下次重置时间
# 目的: 通过 codex app-server 的 JSON-RPC 接口(account/rateLimits/read)读取
#       官方配额数据, 由 Codex CLI 自行处理 token 刷新, 不直接触碰 auth.json,
#       避免手动刷新 OAuth refresh token 导致掉登录。
# 用法: python codex_usage.py [--json]

import json
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta

# Codex CLI 可能的安装位置, 按顺序探测
CODEX_CANDIDATES = [
    r"C:\Users\Blazar\AppData\Local\OpenAI\Codex\bin\codex.exe",
    "codex",  # PATH 中的 codex
]

RPC_TIMEOUT_SEC = 20.0  # 单次 JSON-RPC 响应等待上限


def find_codex():
    """定位 codex.exe: 先查已知路径, 再查 PATH"""
    for path in CODEX_CANDIDATES:
        found = shutil.which(path)
        if found:
            return found
    return None


def fmt_window(mins):
    """把窗口时长(分钟)转成人类可读文本"""
    if mins == 10080:
        return "7天(周窗口)"
    if mins % 1440 == 0:
        return "%d天" % (mins // 1440)
    if mins % 60 == 0:
        return "%d小时" % (mins // 60)
    return "%d分钟" % mins


def fmt_reset(resets_at, now_ts):
    """把重置时间戳转成本地时间 + 相对剩余时间"""
    dt = datetime.fromtimestamp(resets_at)
    delta = resets_at - now_ts
    if delta <= 0:
        rel = "已重置"
    else:
        h, rem = divmod(int(delta), 3600)
        m, s = divmod(rem, 60)
        rel = ("剩 %d时%02d分" % (h, m)) if h > 0 else ("剩 %d分%02d秒" % (m, s))
    return dt.strftime("%Y-%m-%d %H:%M:%S"), rel


def fetch_rate_limits():
    """启动 codex app-server, 握手后读取配额; 返回(数据dict, None)或(None, 错误信息)"""
    codex = find_codex()
    if not codex:
        return None, "未找到 codex.exe, 请确认 Codex CLI 已安装"

    try:
        proc = subprocess.Popen(
            [codex, "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,  # 屏蔽 config.toml 的无关告警
            text=True,
            encoding="utf-8",
        )
    except OSError as exc:
        return None, "启动 codex 失败: %s" % exc

    lines = []
    lock = threading.Lock()
    done = threading.Event()

    def reader():
        # 后台线程: 持续读取 JSON-RPC stdout
        try:
            for line in proc.stdout:
                with lock:
                    lines.append(line.strip())
        except (ValueError, OSError):
            pass
        finally:
            done.set()

    threading.Thread(target=reader, daemon=True).start()

    next_id = 0

    def rpc_call(method, params=None, notify=False):
        # 发送一条 JSON-RPC 请求/通知并等待响应(通知不等待)
        nonlocal next_id
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            next_id += 1
            msg["id"] = next_id
        try:
            proc.stdin.write(json.dumps(msg) + "\n")
            proc.stdin.flush()
        except (OSError, ValueError) as exc:
            return None, "发送请求失败: %s" % exc
        if notify:
            return True, None

        deadline = time.time() + RPC_TIMEOUT_SEC
        while time.time() < deadline and not done.is_set():
            with lock:
                for line in lines:
                    try:
                        reply = json.loads(line)
                    except ValueError:
                        continue
                    if reply.get("id") == msg["id"] and ("result" in reply or "error" in reply):
                        return reply, None
            time.sleep(0.05)
        return None, "等待 %s 响应超时(%ds)" % (method, RPC_TIMEOUT_SEC)

    try:
        # 1. initialize 握手
        reply, err = rpc_call(
            "initialize",
            {"clientInfo": {"name": "codex_usage_watch", "title": "Codex Usage Watch", "version": "0.1.0"}},
        )
        if err or not reply or "result" not in reply:
            return None, err or ("initialize 失败: %s" % reply)

        # 2. initialized 通知
        rpc_call("initialized", notify=True)

        # 3. 读取配额
        reply, err = rpc_call("account/rateLimits/read", {})
        if err or not reply or "result" not in reply:
            return None, err or ("读取配额失败: %s" % reply)
        return reply["result"], None
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            proc.kill()


def print_report(data):
    """以表格形式打印各档配额的剩余用量与重置时间"""
    now_ts = time.time()
    by_id = data.get("rateLimitsByLimitId") or {}
    if not by_id:
        # 兼容旧结构: 只有单一 rateLimits
        single = data.get("rateLimits")
        if single:
            by_id = {single.get("limitId", "codex"): single}

    for limit_id, lim in by_id.items():
        plan = lim.get("planType") or "?"
        name = lim.get("limitName") or "Codex 通用配额"
        reached = lim.get("rateLimitReachedType")

        print("=" * 56)
        print("配额: %s (%s)  计划: %s" % (name, limit_id, plan))
        if reached:
            print("  状态: 已触发限流(%s)" % reached)

        credits = lim.get("credits")
        if credits:
            if credits.get("unlimited"):
                print("  积分: 无限")
            else:
                print("  积分: %s%s" % (credits.get("balance", "0"), "" if credits.get("hasCredits") else " (无可用积分)"))

        # primary / secondary 两级窗口: primary 通常为短窗口(如5小时), secondary 为周窗口
        for key, label in (("primary", "主窗口"), ("secondary", "副窗口")):
            win = lim.get(key)
            if not win:
                continue
            used = win.get("usedPercent", 0)
            remain = max(0, 100 - used)
            mins = win.get("windowDurationMins", 0)
            reset_at = win.get("resetsAt", 0)
            reset_local, reset_rel = fmt_reset(reset_at, now_ts)
            print("  %s: 已用 %d%% | 剩余 %d%% | 窗口 %s" % (label, used, remain, fmt_window(mins)))
            print("             重置: %s (%s)" % (reset_local, reset_rel))
    print("=" * 56)


def main():
    b_json = "--json" in sys.argv
    data, err = fetch_rate_limits()
    if err:
        print("错误: %s" % err, file=sys.stderr)
        sys.exit(1)

    if b_json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print("Codex/GPT 用量查询  (查询时间: %s)" % now_str)
        print_report(data)


if __name__ == "__main__":
    main()

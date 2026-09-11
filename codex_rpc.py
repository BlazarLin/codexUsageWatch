# -*- coding: utf-8 -*-
# 创建时间: 2026-09-10
# 功能: 封装 Codex app-server JSON-RPC 查询逻辑
# 目的: 供悬浮窗等 UI 调用, 获取各档配额的已用百分比/窗口时长/重置时间戳。
#       通过 codex.exe 自己管理 OAuth token 刷新, 不直接读写 auth.json,
#       避免手动刷新轮换式 refresh token 导致 Codex 掉登录。

import json
import os
import shutil
import subprocess
import threading
import time

# Codex CLI 可能的安装位置, 按顺序探测
CODEX_CANDIDATES = [
    r"C:\Users\Blazar\AppData\Local\OpenAI\Codex\bin\codex.exe",
    "codex",  # PATH 中的 codex
]

RPC_TIMEOUT_SEC = 20.0  # 单次 JSON-RPC 响应等待上限(实测一次查询约 5s)


def find_codex():
    """定位 codex.exe: 先查已知路径, 再查 PATH"""
    for path in CODEX_CANDIDATES:
        found = shutil.which(path)
        if found:
            return found
    return None


def fetch_rate_limits():
    """查询配额; 返回 (数据dict, None) 或 (None, 错误信息)"""
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
            # Windows 下 codex.exe 为控制台程序, 不加此标志会随每次查询弹出命令行窗口
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
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
            {"clientInfo": {"name": "codex_quota_widget", "title": "Codex Quota Widget", "version": "0.1.0"}},
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


def extract_limits(data):
    """从原始应答中拆出 主配额(codex) 与 附加配额(如 Spark 模型) 列表"""
    by_id = (data or {}).get("rateLimitsByLimitId") or {}
    if not by_id:
        single = (data or {}).get("rateLimits")
        if single:
            by_id = {single.get("limitId") or "codex": single}
    main = by_id.get("codex")
    extras = [v for k, v in by_id.items() if k != "codex" and (v.get("primary") or v.get("secondary"))]
    return main, extras

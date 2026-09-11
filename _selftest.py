# -*- coding: utf-8 -*-
# 创建时间: 2026-09-11
# 功能: 悬浮窗无界面(offscreen)功能自测
# 目的: 验证 查询->worker->UI刷新 链路、spinner 切换、窗口缩放与配置序列化, 不弹真实窗口

import json
import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt5.QtCore import Qt, QPoint, QTimer
from PyQt5.QtWidgets import QApplication

app = QApplication([])
from main import QuotaCard

card = QuotaCard()
card.show()
card._request_query()
card.m_clock_timer.start()


def dump():
    print("--- 状态:", card.lb_status.text(), flush=True)
    print("--- 圆环显示值:", card.gauge.m_display, flush=True)
    print("--- 默认尺寸: %dx%d" % (card.width(), card.height()), flush=True)
    print("--- 任务栏可见(Qt.Window):", bool(card.windowFlags() & Qt.Window),
          "| 无Tool标记:", not bool(card.windowFlags() & Qt.Tool), flush=True)

    # 缩放手柄跟随验证
    card.resize(300, 260)
    gp = card.grip.geometry()
    print("--- 手柄位置(应随右下角):", gp.x(), gp.y(),
          "期望", 300 - 18, 260 - 18, flush=True)

    # 缩放回调验证(模拟手柄拖拽)
    card.begin_resize(QPoint(400, 400))
    card.update_resize(QPoint(450, 430))
    card.end_resize()
    print("--- 拖拽后尺寸: %dx%d (应在 min~max 内)" % (card.width(), card.height()), flush=True)

    # 配置序列化验证
    card._save_config()
    cfg = json.load(open("config.json", encoding="utf-8"))
    print("--- 配置键:", sorted(cfg.keys()), "| topmost:", cfg.get("topmost"), flush=True)
    print("--- 置顶标记:", card.m_b_topmost, "| 窗口标题:", card.windowTitle(), flush=True)
    app.quit()


t = QTimer()
t.setSingleShot(True)
t.timeout.connect(dump)
t.start(15000)
QTimer.singleShot(25000, app.quit)  # 兜底退出
app.exec_()

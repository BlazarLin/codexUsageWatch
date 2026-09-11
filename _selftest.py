# -*- coding: utf-8 -*-
# 创建时间: 2026-09-11
# 功能: 悬浮窗无界面(offscreen)功能自测
# 目的: 验证 查询->worker->UI刷新 链路、spinner 切换、只缩不放的窗口缩放、
#       圆环实时压缩与配置序列化, 不弹真实窗口

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
    print("--- 默认尺寸(=最大): %dx%d | maximum: %dx%d"
          % (card.width(), card.height(), card.maximumWidth(), card.maximumHeight()), flush=True)
    print("--- 任务栏可见(Qt.Window):", bool(card.windowFlags() & Qt.Window),
          "| 无Tool标记:", not bool(card.windowFlags() & Qt.Tool), flush=True)

    # 1. 尝试放大 -> 应被钉在默认尺寸
    card.resize(300, 260)
    print("--- 放大尝试后: %dx%d (应保持默认)" % (card.width(), card.height()), flush=True)

    # 2. 缩小 -> 圆环实时压缩
    card.resize(160, 160)
    QApplication.processEvents()
    gh = card.gauge.height()
    side = card.gauge._side_for(card.gauge.width(), gh)
    print("--- 缩小到 %dx%d | 圆环控件 %dx%d | 环径 %d (应小于98)"
          % (card.width(), card.height(), card.gauge.width(), gh, side), flush=True)

    # 3. 缩放到下限
    card.resize(100, 100)
    QApplication.processEvents()
    print("--- 下限夹取: %dx%d (应不小于 %dx%d)"
          % (card.width(), card.height(), card.minimumWidth(), card.minimumHeight()), flush=True)

    # 4. 配置序列化 + 超限夹取回读
    card._save_config()
    cfg = json.load(open("config.json", encoding="utf-8"))
    print("--- 配置键:", sorted(cfg.keys()), "| size:", cfg.get("size"), flush=True)

    app.quit()


t = QTimer()
t.setSingleShot(True)
t.timeout.connect(dump)
t.start(15000)
QTimer.singleShot(25000, app.quit)  # 兜底退出
app.exec_()

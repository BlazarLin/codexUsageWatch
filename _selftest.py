# -*- coding: utf-8 -*-
# 创建时间: 2026-09-10
# 功能: 悬浮窗无界面(offscreen)功能自测
# 目的: 验证 查询->worker->UI刷新 链路与 spinner 切换, 不弹真实窗口

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication

app = QApplication([])
from main import QuotaCard

card = QuotaCard()
card.show()
card._request_query()
card.m_clock_timer.start()


def dump():
    print("--- 状态:", card.lb_status.text())
    print("--- 重置行:", card.lb_reset.text().replace("\n", ""))
    print("--- 圆环显示值:", card.gauge.m_display)
    print("--- spinner 复位:", card.gauge.m_b_spin == False)
    print("--- 窗口尺寸: %dx%d" % (card.width(), card.height()))
    app.quit()


t = QTimer()
t.setSingleShot(True)
t.timeout.connect(dump)
t.start(15000)
QTimer.singleShot(25000, app.quit)  # 兜底退出
app.exec_()

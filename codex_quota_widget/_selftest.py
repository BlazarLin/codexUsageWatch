# -*- coding: utf-8 -*-
# 创建时间: 2026-09-10
# 功能: 悬浮窗 v2 无界面(offscreen)功能自测
# 目的: 验证 查询->worker->UI刷新 链路、详情面板展开/收起、spinner 切换, 不弹真实窗口

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

base_h = card.m_base_h


def dump():
    print("--- 状态:", card.lb_status.text())
    print("--- 重置行:", card.lb_reset.text().replace("\n", ""))
    print("--- 圆环显示值:", card.gauge.m_display)
    print("--- 详情面板行数:", max(0, card.detail_box.count() - 1))
    print("--- spinner 复位:", card.gauge.m_b_spin == False)

    # 展开详情面板: 等高度动画(180ms)结束后再量
    card._expand()

    def expanded_check():
        print("--- 展开态高度:", card.height(), "(应大于 %d)" % base_h)
        print("--- 面板可见:", card.detail.isVisible())
        card._collapse()

        def final():
            print("--- 收回后高度:", card.height(), "(应回到 %d)" % base_h)
            print("--- 面板隐藏:", not card.detail.isVisible())
            app.quit()

        QTimer.singleShot(400, final)

    QTimer.singleShot(400, expanded_check)


t = QTimer()
t.setSingleShot(True)
t.timeout.connect(dump)
t.start(15000)
QTimer.singleShot(30000, app.quit)  # 兜底退出
app.exec_()

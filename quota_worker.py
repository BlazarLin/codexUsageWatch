# -*- coding: utf-8 -*-
# 创建时间: 2026-09-10
# 功能: 配额查询后台 Worker(Q_OBJECT worker-object 模式)
# 目的: 把约 5s 的 app-server 查询放到工作线程, 查询结束通过信号回传结果,
#       避免 UI 线程卡顿。

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

from codex_rpc import fetch_rate_limits


class QuotaWorker(QObject):
    """配额查询 Worker: moveToThread 后由 UI 通过 requestQuery 信号触发"""

    # 查询结果信号: (数据dict或None, 错误信息str或None)
    resultReady = pyqtSignal(object, str)
    # 查询开始信号(UI 据此切换"查询中"状态)
    queryStarted = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.m_busy = False  # 防止重复并发查询

    @pyqtSlot()
    def query(self):
        """执行一次查询; 查询期间忽略新的触发请求"""
        if self.m_busy:
            return
        self.m_busy = True
        self.queryStarted.emit()
        try:
            data, err = fetch_rate_limits()
        except Exception as exc:  # 兜底: 任何异常都转成错误信号, 不让线程崩溃
            data, err = None, "查询异常: %r" % exc
        self.m_busy = False
        self.resultReady.emit(data, err or "")

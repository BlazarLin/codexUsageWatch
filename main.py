# -*- coding: utf-8 -*-
# 创建时间: 2026-09-10
# 功能: Codex 剩余用量桌面悬浮窗(v2 精简版)
# 目的: 顶置可拖拽的半透明仪表卡片, 主视图只保留「剩余百分比圆环 + 重置倒计时」,
#       低频信息(Spark 配额/计划/积分/绝对重置时间)通过悬停展开详情面板与右键菜单按需呈现;
#       每 30min 自动查询, 支持手动刷新, 查询中圆环显示旋转扫描弧, 数字变化带滚动动画。
# 用法: python main.py   (悬停展开详情; 右键菜单: 配额详情/立即刷新/置顶/退出)

import json
import os
import re
import sys
import time
from datetime import datetime

from PyQt5.QtCore import (
    QEasingCurve, QPoint, QRectF, QSize, QVariantAnimation, Qt, QThread, QTimer, pyqtSignal,
)
from PyQt5.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QIcon
from PyQt5.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMenu, QPushButton,
    QVBoxLayout, QWidget,
)

from codex_rpc import extract_limits
from quota_worker import QuotaWorker

def _app_dir():
    """应用目录: PyInstaller 打包后 __file__ 在临时解包目录, 用 exe 所在目录持久化 config"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = _app_dir()
CONFIG_PATH = os.path.join(APP_DIR, "config.json")  # 窗口位置持久化


def _asset_path(rel):
    """资源路径: 打包运行时在 _MEIPASS 解包目录, 源码运行时在仓库目录"""
    base = getattr(sys, "_MEIPASS", APP_DIR)
    return os.path.join(base, rel)

AUTO_REFRESH_MS = 30 * 60 * 1000  # 自动查询周期: 30min
CLOCK_TICK_MS = 60 * 1000         # 倒计时文本重算周期: 1min
ROLL_MS = 500                     # 百分比数字滚动动画时长

DEFAULT_W = 204                   # 默认宽度(同时是最大宽度, 只允许缩小)
MIN_W, MIN_H = 128, 128           # 缩放下限(迷你徽章尺寸)

# 剩余比例配色阈值(与 CodexQuotaMonitor 习惯一致)
AMBER_AT = 30   # 剩余 <30% 转琥珀
RED_AT = 15     # 剩余 <15% 转红

COLOR_TEXT = "#e8eaed"
COLOR_TEXT_DIM = "#9aa0a6"
COLOR_GREEN = "#34d399"
COLOR_AMBER = "#fbbf24"
COLOR_RED = "#f87171"


def health_color(remain_pct):
    """按剩余百分比选择健康色"""
    if remain_pct is None:
        return COLOR_TEXT_DIM
    if remain_pct < RED_AT:
        return COLOR_RED
    if remain_pct < AMBER_AT:
        return COLOR_AMBER
    return COLOR_GREEN


def health_word(remain_pct):
    """剩余百分比对应的语义描述(状态点 tooltip 用)"""
    if remain_pct is None:
        return "待查询"
    if remain_pct < RED_AT:
        return "告急"
    if remain_pct < AMBER_AT:
        return "余量偏低"
    return "正常"


def fmt_window_short(mins):
    """窗口时长缩写: 10080→周, 1440→天, 整小时→N时"""
    if mins == 10080:
        return "周"
    if mins % 1440 == 0:
        return "天"
    if mins % 60 == 0:
        return "%d时" % (mins // 60)
    return "%d分" % mins


def fmt_remain_rel(delta_sec):
    """剩余时间相对描述: 4天16时 / 3时20分 / 42分"""
    if delta_sec <= 0:
        return "已重置"
    total_min = int(delta_sec // 60)
    days, rem = divmod(total_min, 1440)
    hours, minutes = divmod(rem, 60)
    if days > 0:
        return "%d天%d时" % (days, hours)
    if hours > 0:
        return "%d时%02d分" % (hours, minutes)
    return "%d分" % minutes


def fmt_reset_abs(resets_at):
    """绝对重置时间: 09月15日 09:39(tooltip 用, 无宽度约束)"""
    return datetime.fromtimestamp(resets_at).strftime("%m月%d日 %H:%M")


def short_model_name(name):
    """模型名精简: 去掉 GPT- 与版本号前缀(如 5.3-), 缩短右键菜单行宽"""
    if not name:
        return name
    name = re.sub(r"^GPT-", "", name)
    name = re.sub(r"^\d+\.\d+-", "", name)
    return name


class RingGauge(QWidget):
    """圆环仪表: 环径/描边/字号随控件尺寸实时压缩, 查询中切换旋转扫描弧"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.m_display = None   # 当前显示值(动画中)
        self.m_target = None    # 动画目标值
        self.m_b_spin = False   # 查询中旋转标记
        self.m_n_angle = 0      # 扫描弧当前角度

        # 数字滚动动画
        self.m_anim = QVariantAnimation(self)
        self.m_anim.setDuration(ROLL_MS)
        self.m_anim.setEasingCurve(QEasingCurve.OutCubic)
        self.m_anim.valueChanged.connect(self._on_anim_value)

        # 旋转扫描定时器
        self.m_spin_timer = QTimer(self)
        self.m_spin_timer.setInterval(33)
        self.m_spin_timer.timeout.connect(self._tick_spin)

    def sizeHint(self):
        # 默认基准尺寸: 布局据此分配初始高度
        return QSize(186, 114)

    def minimumSizeHint(self):
        # 允许压缩到迷你徽章级别
        return QSize(60, 44)

    @staticmethod
    def _side_for(w, h):
        """环径: 可用空间扣除描边余量后按比例压缩(1.12 = 1 + 描边占比, 保证不裁边)"""
        return max(36, int((min(w, h) - 4) / 1.12))

    def set_remain(self, target_pct):
        """目标剩余值变化时滚动过渡; 首次从 0 滚起, 强化'数据到来'的感知"""
        self.m_target = target_pct
        start = self.m_display if self.m_display is not None else 0.0
        self.m_anim.stop()
        self.m_anim.setStartValue(float(start))
        self.m_anim.setEndValue(float(target_pct))
        self.m_anim.start()

    def set_spinning(self, b_spin):
        """查询中显示旋转扫描弧; 显示值淡化但不丢失"""
        if self.m_b_spin == b_spin:
            return
        self.m_b_spin = b_spin
        if b_spin:
            self.m_spin_timer.start()
        else:
            self.m_spin_timer.stop()
            self.update()

    def _on_anim_value(self, val):
        self.m_display = val
        self.update()

    def _tick_spin(self):
        self.m_n_angle = (self.m_n_angle + 9) % 360
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # 环体几何: 环径随控件实时压缩, 居中绘制; 描边/光晕/字号同步缩放
        side = self._side_for(self.width(), self.height())
        pen_w = max(6, round(side * 0.12))
        cx, cy = self.width() / 2.0, self.height() / 2.0
        rect = QRectF(cx - side / 2.0, cy - side / 2.0, side, side)
        center_y = cy

        # 背景轨道
        p.setPen(QPen(QColor("#31343d"), pen_w, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(rect, 0, 360 * 16)

        if self.m_b_spin:
            # 查询中: 旋转扫描弧
            p.setPen(QPen(QColor("#7d8694"), pen_w, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(rect, self.m_n_angle * 16, -110 * 16)
            num_color, alpha = COLOR_TEXT_DIM, 110
        else:
            remain = self.m_display
            if remain is not None:
                frac = max(0.0, min(100.0, remain)) / 100.0
                color = QColor(health_color(remain))
                # 光晕层: 更宽的低透明度弧, 模拟辉光
                glow = QColor(color)
                glow.setAlpha(38)
                p.setPen(QPen(glow, pen_w + max(4, round(pen_w * 0.6)), Qt.SolidLine, Qt.RoundCap))
                p.drawArc(rect, 90 * 16, int(-360 * 16 * frac))
                # 主弧线: 12 点方向顺时针
                p.setPen(QPen(color, pen_w, Qt.SolidLine, Qt.RoundCap))
                p.drawArc(rect, 90 * 16, int(-360 * 16 * frac))
            num_color = health_color(remain)
            alpha = 255

        # 中心文字: 彩色百分比 + 灰色"剩余"(按环径等比缩放)
        p.setPen(QColor(num_color))
        p.setOpacity(alpha / 255.0)
        f_big = QFont("Microsoft YaHei UI", max(8, round(side * 0.20)))
        f_big.setBold(True)
        p.setFont(f_big)
        text = "--%" if self.m_display is None else "%d%%" % round(self.m_display)
        p.drawText(QRectF(0, center_y - side * 0.31, self.width(), side * 0.35),
                   Qt.AlignCenter, text)
        p.setOpacity(1.0)
        p.setPen(QColor(COLOR_TEXT_DIM))
        p.setFont(QFont("Microsoft YaHei UI", max(6, round(side * 0.082))))
        p.drawText(QRectF(0, center_y + side * 0.04, self.width(), side * 0.17),
                   Qt.AlignCenter, "剩余")


class ResizeGrip(QWidget):
    """右下角透明缩放手柄: 按住拖拽缩放窗口, 悬停显示对角缩放光标"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(18, 18)
        self.setCursor(Qt.SizeFDiagCursor)
        self.setToolTip("拖拽缩放")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.parent().begin_resize(event.globalPos())
            event.accept()

    def mouseMoveEvent(self, event):
        # 按下期间 Qt 隐式抓取鼠标, 移动/释放持续派发到手柄
        self.parent().update_resize(event.globalPos())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.parent().end_resize()


class QuotaCard(QWidget):
    """悬浮配额仪表卡片主窗口"""

    # UI → Worker 的触发信号(worker-object 模式的跨线程入口)
    requestQuery = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.m_main_limit = None   # codex 通用配额原始数据
        self.m_extras = []         # 其余配额(如 Spark)
        self.m_last_plan = ""      # 计划类型
        self.m_b_topmost = True    # 置顶状态
        self.m_drag_pos = QPoint()
        self.m_b_resizing = False  # 缩放进行中标记
        self.m_rstart_g = QPoint() # 缩放起点(全局坐标)
        self.m_rstart_size = None  # 缩放起点尺寸

        self._init_window()
        self._init_ui()
        self._init_worker()
        self._init_timers()
        self._load_config()

    # ---------- 初始化 ----------

    def _init_window(self):
        self.setWindowTitle("Codex Usage Watch")
        # Qt.Window: 任务栏/Alt-Tab 显示应用图标(此前 Qt.Tool 隐藏任务栏)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Window
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(9, 8, 9, 8)
        root.setSpacing(2)

        # 标题行: 名称 + 健康状态点
        title_row = QHBoxLayout()
        self.lb_title = QLabel("Codex")
        self.lb_title.setStyleSheet(
            "color:%s; font:600 9.5pt 'Microsoft YaHei UI';" % COLOR_TEXT)
        self.lb_dot = QLabel("●")
        self.lb_dot.setStyleSheet("color:%s; font:10pt;" % COLOR_TEXT_DIM)
        title_row.addWidget(self.lb_title)
        title_row.addStretch()
        title_row.addWidget(self.lb_dot)
        root.addLayout(title_row)

        # 圆环仪表: 拉伸因子 1 吸收全部垂直伸缩, 实现环径实时压缩
        self.gauge = RingGauge()
        root.addWidget(self.gauge, 1)

        # 重置倒计时主行: 倒计时加粗主色, "后重置"淡化(绝对时间在右键菜单 tooltip)
        self.lb_reset = QLabel("等待首次查询…")
        self.lb_reset.setAlignment(Qt.AlignCenter)
        self.lb_reset.setStyleSheet(
            "color:%s; font:8.5pt 'Microsoft YaHei UI';" % COLOR_TEXT_DIM)
        root.addWidget(self.lb_reset)

        # 弹性空间已由圆环行(拉伸因子 1)吸收, 无需额外 stretch

        # 底部行: 极简状态 + 刷新按钮
        foot_row = QHBoxLayout()
        self.lb_status = QLabel("…")
        self.lb_status.setStyleSheet(
            "color:%s; font:8pt 'Microsoft YaHei UI';" % COLOR_TEXT_DIM)
        self.btn_refresh = QPushButton("↻")
        self.btn_refresh.setFixedSize(24, 24)
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setToolTip("立即刷新(自动刷新周期 30 分钟)")
        self.btn_refresh.setStyleSheet(
            "QPushButton{color:%s; background:#2b2e36; border:none;"
            "border-radius:12px; font:11pt;}"
            "QPushButton:hover{background:#3d414c; color:#ffffff;}"
            "QPushButton:disabled{color:#6b7078;}" % COLOR_TEXT)
        self.btn_refresh.clicked.connect(self._request_query)
        foot_row.addWidget(self.lb_status)
        foot_row.addStretch()
        foot_row.addWidget(self.btn_refresh)
        root.addLayout(foot_row)

        # 先创建右下角缩放手柄(下方 resize() 触发的 resizeEvent 会把它钉到右下角),
        # 默认尺寸即最大尺寸: 只允许缩小, 不允许放大
        self.grip = ResizeGrip(self)
        self.setMinimumSize(MIN_W, MIN_H)
        self.setMaximumSize(self.sizeHint())
        self.resize(self.sizeHint())
        self.grip.raise_()

    def _init_worker(self):
        # worker-object 模式: Worker 移入 QThread, UI 通过信号触发查询
        self.m_thread = QThread(self)
        self.m_worker = QuotaWorker()
        self.m_worker.moveToThread(self.m_thread)
        self.requestQuery.connect(self.m_worker.query)
        self.m_worker.queryStarted.connect(self._on_query_started)
        self.m_worker.resultReady.connect(self._on_result)
        self.m_thread.start()

    def _init_timers(self):
        # 自动查询定时器: 单次触发, 每次查询结束后重新计时
        self.m_auto_timer = QTimer(self)
        self.m_auto_timer.setSingleShot(True)
        self.m_auto_timer.setInterval(AUTO_REFRESH_MS)
        self.m_auto_timer.timeout.connect(self._request_query)
        # 悬停展开已按需求关闭: 低频信息统一走右键菜单
        self.m_clock_timer = QTimer(self)
        self.m_clock_timer.setInterval(CLOCK_TICK_MS)
        self.m_clock_timer.timeout.connect(self._refresh_countdown_display)

    # ---------- 查询流程 ----------

    def _request_query(self):
        # 信号触发 worker.query; 忙时 worker 内部会自行忽略
        self.requestQuery.emit()

    def _on_query_started(self):
        self.btn_refresh.setEnabled(False)
        self.gauge.set_spinning(True)
        self.lb_status.setText("查询中…")
        self.lb_status.setStyleSheet(
            "color:%s; font:8pt 'Microsoft YaHei UI';" % COLOR_TEXT_DIM)
        self.lb_dot.setToolTip("查询中…")

    def _on_result(self, data, err):
        self.btn_refresh.setEnabled(True)
        self.gauge.set_spinning(False)
        self.m_auto_timer.start()  # 无论成败, 重置 30min 自动查询

        if err:
            self._show_error(err)
            return

        main, extras = extract_limits(data)
        if main is None:
            self._show_error("应答中无配额数据")
            return

        self.m_main_limit = main
        self.m_extras = extras
        self.m_last_plan = main.get("planType") or ""

        primary = main.get("primary") or {}
        remain = max(0, 100 - primary.get("usedPercent", 0))

        # 状态点: 触发限流→红, 否则按剩余健康度
        dot_color = COLOR_RED if main.get("rateLimitReachedType") else health_color(remain)
        self.lb_dot.setStyleSheet("color:%s; font:10pt;" % dot_color)
        self.lb_dot.setToolTip("状态: %s(剩余 %d%%)" % (
            "限流中" if main.get("rateLimitReachedType") else health_word(remain), remain))

        self.gauge.set_remain(remain)
        self._refresh_countdown_display()

        # 底部极简状态: 完整信息进 tooltip
        now = datetime.now()
        self.lb_status.setText("✓ %s" % now.strftime("%H:%M"))
        self.lb_status.setStyleSheet(
            "color:%s; font:8pt 'Microsoft YaHei UI';" % COLOR_GREEN)
        self.lb_status.setToolTip(
            "上次更新 %s\n30 分钟后自动刷新, 右键可手动刷新\n点击 ↻ 立即刷新"
            % now.strftime("%H:%M:%S"))

    def _show_error(self, err):
        # 错误不打断旧数据展示: 状态行红色简报, 完整信息进 tooltip
        self.lb_status.setText("⚠ 查询失败")
        self.lb_status.setStyleSheet(
            "color:%s; font:8pt 'Microsoft YaHei UI';" % COLOR_RED)
        self.lb_status.setToolTip(err)
        self.lb_dot.setToolTip("查询失败: %s" % err)

    # ---------- 显示刷新 ----------

    def _refresh_countdown_display(self):
        """按缓存的 resetsAt 重算倒计时文本(每分钟由时钟定时器调用)"""
        main = self.m_main_limit
        if not main:
            return
        primary = main.get("primary") or {}
        resets_at = primary.get("resetsAt", 0)
        if not resets_at:
            self.lb_reset.setText("无重置时间信息")
            return
        rel = fmt_remain_rel(resets_at - time.time())
        # 倒计时为主语, 绝对时间放 tooltip
        self.lb_reset.setText(
            "<span style='color:%s; font-weight:600;'>%s</span>"
            "<span style='color:%s;'> 后重置</span>"
            % (health_color(max(0, 100 - primary.get("usedPercent", 0))), rel, COLOR_TEXT_DIM))
        self.lb_reset.setToolTip("%s 重置" % fmt_reset_abs(resets_at))

    # ---------- 缩放(右下角手柄) ----------

    def begin_resize(self, gpos):
        self.m_b_resizing = True
        self.m_rstart_g = gpos
        self.m_rstart_size = self.size()
        QApplication.setOverrideCursor(Qt.SizeFDiagCursor)

    def update_resize(self, gpos):
        if not self.m_b_resizing:
            return
        dw = gpos.x() - self.m_rstart_g.x()
        dh = gpos.y() - self.m_rstart_g.y()
        # 只允许缩小: 上限即 maximumSize(默认尺寸)
        w = max(self.minimumWidth(), min(self.maximumWidth(), self.m_rstart_size.width() + dw))
        h = max(self.minimumHeight(), min(self.maximumHeight(), self.m_rstart_size.height() + dh))
        self.resize(w, h)

    def end_resize(self):
        if not self.m_b_resizing:
            return
        self.m_b_resizing = False
        QApplication.restoreOverrideCursor()
        self._save_config()  # 缩放结束即持久化尺寸

    def resizeEvent(self, event):
        # 手柄始终钉在右下角(构造早期 grip 尚未创建, 需防护)
        grip = getattr(self, "grip", None)
        if grip:
            grip.move(self.width() - grip.width(), self.height() - grip.height())
        super().resizeEvent(event)

    # ---------- 交互: 拖拽 / 右键菜单 ----------

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.m_drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            QApplication.setOverrideCursor(Qt.ClosedHandCursor)  # 拖拽手型反馈
            event.accept()

    def mouseMoveEvent(self, event):
        # 拖动窗口(仅按住左键时)
        if event.buttons() & Qt.LeftButton and not self.m_drag_pos.isNull():
            self.move(event.globalPos() - self.m_drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.m_drag_pos = QPoint()
            QApplication.restoreOverrideCursor()
            self._save_config()  # 拖完即存位置, 防意外退出丢位置

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#26282f; color:%s; border:1px solid #3a3f4b;}"
            "QMenu::item{padding:4px 20px; font:8.5pt 'Microsoft YaHei UI';}"
            "QMenu::item:selected{background:#3a3e48;}"
            "QMenu::item:disabled{color:%s;}" % (COLOR_TEXT, COLOR_TEXT_DIM))

        # 顶部只读配额详情区(文字进右键菜单)
        main = self.m_main_limit
        if main is not None:
            primary = main.get("primary") or {}
            remain = max(0, 100 - primary.get("usedPercent", 0))
            resets_at = primary.get("resetsAt", 0)
            info = menu.addAction("通用配额  剩%d%% · %s重置" % (
                remain, fmt_remain_rel(resets_at - time.time()) if resets_at else "-"))
            info.setEnabled(False)
            for lim in self.m_extras:
                name = short_model_name(lim.get("limitName") or lim.get("limitId") or "附加配额")
                pri = lim.get("primary") or {}
                sec = lim.get("secondary") or {}
                txt = name
                if pri:
                    txt += "  %s剩%d%%" % (fmt_window_short(pri.get("windowDurationMins", 0)),
                                           max(0, 100 - pri.get("usedPercent", 0)))
                if sec:
                    txt += " / 周剩%d%%" % max(0, 100 - sec.get("usedPercent", 0))
                act = menu.addAction(txt)
                act.setEnabled(False)
            plan = menu.addAction("计划 %s · 积分 %s" % (
                self.m_last_plan or "?", (main.get("credits") or {}).get("balance", "0")))
            plan.setEnabled(False)
            menu.addSeparator()

        act_refresh = menu.addAction("立即刷新")
        act_top = menu.addAction("窗口置顶")
        act_top.setCheckable(True)
        act_top.setChecked(self.m_b_topmost)
        menu.addSeparator()
        act_quit = menu.addAction("退出")

        chosen = menu.exec_(event.globalPos())
        if chosen == act_refresh:
            self._request_query()
        elif chosen == act_top:
            self.m_b_topmost = not self.m_b_topmost
            self.setWindowFlag(Qt.WindowStaysOnTopHint, self.m_b_topmost)
            self.show()  # setWindowFlag 后需要重新 show
            self._save_config()
        elif chosen == act_quit:
            self.close()

    # ---------- 位置持久化 ----------

    def _load_config(self):
        pos, size, topmost = None, None, True
        try:
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                pos = cfg.get("pos")
                size = cfg.get("size")
                topmost = cfg.get("topmost", True)
        except (OSError, ValueError):
            pos = None
        # 置顶标记(窗口 show 之前设置, 无需重刷)
        self.m_b_topmost = bool(topmost)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, self.m_b_topmost)
        # 尺寸(旧配置无 size 键则用默认; 超出上下限则夹取, 只允许缩小)
        if size and len(size) == 2:
            w = max(self.minimumWidth(), min(self.maximumWidth(), int(size[0])))
            h = max(self.minimumHeight(), min(self.maximumHeight(), int(size[1])))
            self.resize(w, h)
        if pos:
            self.move(int(pos[0]), int(pos[1]))
        else:
            # 默认停靠主屏右上角
            screen = QApplication.primaryScreen().availableGeometry()
            self.move(screen.right() - self.width() - 24, screen.top() + 24)
        self._clamp_into_screen()

    def _save_config(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump({
                    "pos": [self.x(), self.y()],
                    "size": [self.width(), self.height()],
                    "topmost": self.m_b_topmost,
                }, f)
        except OSError:
            pass  # 位置保存失败不影响功能

    def _clamp_into_screen(self):
        """把窗口约束回可见屏幕(防止分辨率变化后消失)"""
        geo = QApplication.primaryScreen().availableGeometry()
        x = max(geo.left(), min(self.x(), geo.right() - self.width()))
        y = max(geo.top(), min(self.y(), geo.bottom() - self.height()))
        self.move(x, y)

    # ---------- 绘制与关闭 ----------

    def paintEvent(self, event):
        # 深色渐变圆角卡片 + 1px 高光描边
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)

        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0.0, QColor(38, 41, 50, 240))
        grad.setColorAt(1.0, QColor(22, 24, 29, 240))
        p.fillPath(path, grad)

        # 高光描边: 顶部亮底部暗, 增加玻璃质感
        border = QLinearGradient(0, 0, 0, self.height())
        border.setColorAt(0.0, QColor(255, 255, 255, 34))
        border.setColorAt(1.0, QColor(255, 255, 255, 10))
        p.setPen(QPen(border, 1))
        p.drawPath(path)

    def closeEvent(self, event):
        self._save_config()
        self.m_auto_timer.stop()
        self.m_clock_timer.stop()
        self.m_thread.quit()
        if not self.m_thread.wait(2000):
            # 查询仍在进行(约5s)时直接退出: 强制结束线程;
            # 进程退出后 stdin 管道关闭, codex app-server 子进程也会随之退出
            self.m_thread.terminate()
        event.accept()


def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)  # 高DPI适配
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication([])
    app.setWindowIcon(QIcon(_asset_path(os.path.join("assets", "icon.ico"))))

    card = QuotaCard()
    card.show()
    card._request_query()      # 启动即查一次
    card.m_clock_timer.start()

    raise SystemExit(app.exec_())


if __name__ == "__main__":
    main()

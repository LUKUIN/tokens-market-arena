# -*- coding: utf-8 -*-
"""Tokens 交易市场 —— 观众席（只读 | 交易终端风格）

显示：账户权益、累计盈亏、保证金水平、目标进度、可贷额度、
持仓表、权益曲线、多货币报价台、活动流（可滚动、不跳回）。

额外提供：
  | 结束相关进程 —— 通知 API 立即退出，随后关闭观众席
"""

import json
import os
import socket
import sys
import tkinter as tk
import time
import tkinter.font as tkfont
from tkinter import ttk, messagebox
import urllib.request

API = "http://127.0.0.1:8734"
HERE = os.path.dirname(os.path.abspath(__file__))

# 单实例锁：占住一个本地端口，进程退出自动释放。
WATCH_LOCK_PORT = 8735
_LOCK_SOCK = None

# 窗口 / 任务栏图标（￥ 符号，多尺寸 ico）
ICO_PATH = os.path.join(HERE, "app.ico")

# 字号缩放：窗口越小，字号相对放大。
# 人的观看距离不变，窗口缩小时若字号同比缩小会看不清；
# 所以小窗反而把字抬一点，把省出来的空间让给字号。
_UI_SCALE = {"v": 1.0}


def _fmt_ff(sec):
    """快进额度显示成「X 分 YY 秒」。

    不能只显示分钟：额度池是 900 秒，而单次快进最小也是 180 秒，
    用整数分钟会把 895 秒显示成「14 分钟」，同时把已用 5 秒显示成「0 分钟」，
    两个数加起来凑不出 15。这里保留秒，避免这种自相矛盾。
    """
    try:
        sec = int(round(float(sec or 0)))
    except (TypeError, ValueError, OverflowError):
        sec = 0
    if sec < 0:
        sec = 0
    return "%d 分 %02d 秒" % (sec // 60, sec % 60)


def _ui_font_factor(width):
    f = 1.0 + max(0.0, (1920 - int(width)) / 1920.0) * 0.55
    return round(f, 3)


def _apply_ui_scale(win, width):
    f = _ui_font_factor(width)
    _UI_SCALE["v"] = f
    try:
        win.tk.call("tk", "scaling", 1.333 * f)
    except Exception:
        pass
    return f


RESOLUTIONS = [
    (1366, 768, "1366 × 768"),
    (1400, 900, "1400 × 900"),
    (1600, 900, "1600 × 900"),
    (1920, 1080, "1920 × 1080"),
]


def _hide_close_button(win):
    """去掉标题栏右上角的关闭按钮（仅 Windows 有效）。

    `WM_DELETE_WINDOW` 只能做到「点了没反应」，按钮本身还画在那里；
    这里直接清掉窗口样式里的 WS_SYSMENU，让它真正消失。
    """
    try:
        import ctypes
        win.update_idletasks()
        GWL_STYLE = -16
        WS_SYSMENU = 0x00080000
        u = ctypes.windll.user32
        hwnd = win.winfo_id()
        parent = u.GetParent(hwnd)
        target = parent if parent else hwnd
        style = u.GetWindowLongW(target, GWL_STYLE)
        u.SetWindowLongW(target, GWL_STYLE, style & ~WS_SYSMENU)
        u.SetWindowPos(target, 0, 0, 0, 0, 0, 0x0037)  # 刷新窗口框架
        win.update_idletasks()
    except Exception:
        pass


def _apply_icon(win):
    """给窗口设置 ￥ 图标；任务栏与标题栏都会跟随。

    注意必须先用「无 default」的写法：`iconbitmap(default=...)` 只影响此后新建的
    窗口，对已经存在的窗口不生效。
    """
    try:
        win.iconbitmap(ICO_PATH)
        return
    except Exception:
        pass
    try:
        win.iconbitmap(default=ICO_PATH)
    except Exception:
        pass

# Fluent 配色
BG = "#F3F3F3"
CARD = "#FFFFFF"
BORDER = "#E1E1E1"
TEXT = "#1A1A1A"
MUTED = "#6B6B6B"
BLUE = "#0078D4"
GREEN = "#107C10"
RED = "#C42B1C"
ORANGE = "#CA5010"
YELLOW = "#B8860B"
PURPLE = "#7B2FBE"   # 紫：欠款区（净值 < 0）
HEAD = "#F7F7F7"
TOPBAR = "#11213E"   # Fluent 深色标题栏

FONT = ("Microsoft YaHei UI", 10)
FONT_SMALL = ("Microsoft YaHei UI", 9)
FONT_TINY = ("Microsoft YaHei UI", 8)
FONT_BIG = ("Microsoft YaHei UI", 23, "bold")
FONT_MID = ("Microsoft YaHei UI", 12, "bold")
FONT_BAR = ("Microsoft YaHei UI", 11)   # 状态条：11pt
# 难度档位 → 展示用数值（与 tm_engine.GAP_LEVELS / LIQ_LEVELS 保持一致）
_GAP_PCT = {"极低": "0.24%", "低": "0.60%", "中": "1.50%", "高": "3.75%", "极高": "9.38%"}
_LIQ_PCT = {"充裕": "3.5%", "正常": "7.0%", "纤薄": "14.0%", "枯竭": "28%", "黑洞": "56%"}
FONT_LOG = ("Microsoft YaHei UI", 11)   # 活动流专用：比状态栏大一号，便于扫读
FONT_MONO = ("Consolas", 9)
FONT_MONO_BIG = ("Consolas", 11, "bold")

# 活动流快捷分类：「黑天鹅」与「流动性枯竭」在引擎里同为 kind="gap"，
# 靠 "[Liquidity drained]" 文本前缀区分。
# 流动性事件的前缀（英文版 [Liquidity drained]、中文版【流动性枯竭】，
# 两种括号都要覆盖——此前只匹配英文，中文事件全被归进「黑天鹅」）
_LIQ_MARKS = ("[Liquidity drained]", "【流动性枯竭】", "[流动性枯竭]")

LOG_TABS = (
    ("all", "全部"),
    ("gap", "黑天鹅"),
    ("liq", "流动性枯竭"),
    ("news", "随机事件"),
    ("trade", "开仓/平仓"),
    ("risk", "风险"),
)

PAIR_ORDER = ["AURA/CORE", "FROST/CORE", "AMBER/CORE", "TIDE/CORE",
              "LUMEN/CORE", "NEON/CORE", "ASH/CORE"]
PAIR_COLORS = {
    "AURA/CORE": "#0078D4", "FROST/CORE": "#107C10", "AMBER/CORE": "#C42B1C",
    "TIDE/CORE": "#8764B8", "LUMEN/CORE": "#CA5010", "NEON/CORE": "#0F7B6C",
    "ASH/CORE": "#8E562E",
}


def get(path):
    with urllib.request.urlopen(API + path, timeout=3) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, payload=None):
    body = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(API + path, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3) as r:
        return json.loads(r.read().decode("utf-8"))


def card(parent, pad=0):
    return tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)


def _fit_title(name, limit=44):
    """标题栏宽度有限：超长时保留首尾、中间省略，避免把「Agent」这种尾巴切掉。"""
    if len(name) <= limit:
        return name
    head = name[:limit // 2]
    tail = name[-(limit // 2 - 1):]
    return head + "…" + tail


class Watch:
    def __init__(self, size=(1920, 1080)):
        self.root = tk.Tk()
        self.root.title("Tokens 交易市场")
        self.W, self.H = int(size[0]), int(size[1])
        self.S = self.W / 1920.0
        # 字号放大后内容变高，窄屏要靠收紧竖向留白把版面塞回可视区
        self.V = 1.0 if self.H >= 1000 else (0.84 if self.H >= 860 else 0.72)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        px = max(0, (sw - self.W) // 2)
        py = max(0, (sh - self.H) // 2 - 30)
        self.root.geometry("%dx%d+%d+%d" % (self.W, self.H, px, py))
        self.root.resizable(False, False)
        self.root.configure(bg=BG)
        # 字号：窗口越小越大（不随窗口同比缩小），保证小窗也能看清
        _apply_ui_scale(self.root, self.W)
        _apply_icon(self.root)
        # 主窗口不允许关闭：关掉就没有 GUI 了，进程还在后台空转。
        # 只留最小化（工具栏那颗按钮），退出走「结束并结算」。
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)
        self.root.after(120, lambda: _hide_close_button(self.root))

        self.curve = []
        self.prices = {}
        self.price_history = {}
        self._closing = False
        self._last_trader = None
        self._last_audit = None
        self._log_seen = set()
        self._log_events = []
        self._log_filter = "all"
        self._log_tabs = {}
        self._log_anchor_init = False
        self._last_tick = -1
        self.st = None
        self._tp = None
        # 窄屏放不下活动流：主窗口不建，改由工具栏按钮开独立窗口
        # 只有 1920x1080 走完整版式；1366x768 / 1400x900 / 1600x900 都算窄屏
        self.narrow = False   # AI 版固定完整版式：活动流内嵌，不做分辨率选择
        self._loan_win = None
        self._loan_left = None
        self.log_text = None
        self._log_win = None

        self._build()
        self.refresh()
        # AI 版不弹规则窗（规则见 README / /rules 接口）

    # ------------------------------------------------------------ 布局
    def _build(self):
        root = self.root

        # ---------- 顶栏（Fluent 深色标题栏）----------
        # 深色条把「身份 / 模式 / 全局状态」与正文分开；正文继续用浅色卡片，
        # 层次靠色差就够了，不依赖 Tk 做不出的圆角与阴影。
        topbar = tk.Frame(root, bg=TOPBAR)
        topbar.pack(fill="x")

        _brand = tk.Frame(topbar, bg=TOPBAR)
        _brand.pack(side="left", padx=(18, 0), pady=10)
        tk.Label(_brand, text="TOKENS 交易市场", font=(FONT[0], 12, "bold"),
                 bg=TOPBAR, fg="#FFFFFF").pack(side="left")
        self.lbl_trader = tk.Label(_brand, text="", font=(FONT[0], 11, "bold"),
                                   bg=TOPBAR, fg="#8CC4F8")
        self.lbl_trader.pack(side="left", padx=(14, 0))
        self.lbl_mode = tk.Label(_brand, text="", font=FONT_SMALL, bg=TOPBAR, fg="#AEBBD0")
        self.lbl_mode.pack(side="left", padx=(8, 0))
        tk.Label(_brand, text="只读观战终端", font=FONT_SMALL,
                 bg=TOPBAR, fg="#7E8CA3").pack(side="left", padx=(10, 0))

        # 两个全局开关型事件：开启=亮紫粗体；未开启=灰粗体+删除线
        self._f_on = tkfont.Font(root=root, family=FONT[0], size=10, weight="bold")
        self._f_off = tkfont.Font(root=root, family=FONT[0], size=10, weight="bold",
                                  overstrike=1)
        self.lbl_fr = tk.Label(topbar, text="金融回逆", font=self._f_off,
                               bg=TOPBAR, fg="#D6DFEC")
        self.lbl_fr.pack(side="left", padx=(22, 0))
        self.lbl_slot = tk.Label(topbar, text="老虎机", font=self._f_off,
                                 bg=TOPBAR, fg="#D6DFEC")
        self.lbl_slot.pack(side="left", padx=(10, 0))
        self._last_special = None
        self._assist_pend = []
        self._assist_seen = set()
        self._assist_n = 0
        self._assist_last_ticket = None

        _b = dict(font=FONT_SMALL, bd=0, relief="flat", cursor="hand2", padx=12, pady=4)
        self.btn_assist = tk.Button(
            topbar, text="外部的怜悯", command=self._show_assist,
            bg="#2B3E5C", fg="#A9C8EE", activebackground="#36506F",
            activeforeground="#FFFFFF", font=FONT_SMALL, bd=0,
            padx=14, pady=5, cursor="hand2")
        self.btn_assist.pack(side="right", padx=(0, 12), pady=8)
        tk.Button(topbar, text="AI 行为", command=self._show_scratch,
                  bg="#2B3E5C", fg="#C9B8EE", activebackground="#36506F",
                  activeforeground="#FFFFFF", font=FONT_SMALL, bd=0,
                  padx=14, pady=5, cursor="hand2").pack(side="right", padx=(0, 8), pady=8)
        tk.Button(topbar, text="最小化", command=self.root.iconify,
                  bg="#1E3050", fg="#D5DFEC", activebackground="#2B3E5C",
                  activeforeground="#FFFFFF", **_b).pack(side="right", padx=(0, 8), pady=8)
        tk.Button(topbar, text="结束相关进程", command=self._kill_all,
                  bg="#1E3050", fg="#F2A6A0", activebackground="#2B3E5C",
                  activeforeground="#FFFFFF", **_b).pack(side="right", padx=(0, 10), pady=8)

        # ---------- 指标卡 ----------
        metrics = tk.Frame(root, bg=BG)
        metrics.pack(fill="x", padx=14, pady=(10, 6))
        self.lbl_equity = self._metric(metrics, 0, "账户权益（Tokens）", BLUE, "当前账户净值")
        self.lbl_pnl = self._metric(metrics, 1, "累计盈亏", TEXT, "相对初始本金")
        self.lbl_margin = self._metric(metrics, 2, "保证金水平", TEXT, "低于 100% 触发追缴")
        self.lbl_target = self._metric(metrics, 3, "目标进度", BLUE, "距离获胜目标")
        for i in range(4):
            metrics.columnconfigure(i, weight=1, uniform="m")

        # ---------- 状态条第一行：资金面 ----------
        bar = card(root)
        bar.pack(fill="x", padx=14, pady=(0, 4))
        self.lbl_loan = tk.Label(bar, text="可贷 Tokens：—", font=FONT, bg=CARD, fg=BLUE)
        self.lbl_loan.pack(side="left", padx=16, pady=7)
        self.lbl_extra = tk.Label(bar, text="", font=FONT_BAR, bg=CARD, fg=MUTED)
        self.lbl_extra.pack(side="left", padx=(0, 16))
        # 账本自检告警位：默认空着，只有 /state 报出问题时才亮红。
        self.lbl_audit = tk.Label(bar, text="", font=FONT_BAR, bg=CARD, fg=RED)
        self.lbl_audit.pack(side="right", padx=16, pady=7)
        # 上局异常退出：比普通市场事件重要，单独占一个红色位置
        self.lbl_abn = tk.Label(bar, text="", font=FONT_BAR, bg=CARD, fg=RED)
        self.lbl_abn.pack(side="right", padx=16, pady=7)
        self.lbl_status = tk.Label(bar, text="等待连接…", font=FONT, bg=CARD, fg=MUTED)
        self.lbl_status.pack(side="right", padx=16, pady=7)

        # ---------- 状态条第二行：每 tick 都在变的数字 ----------
        bar2 = card(root)
        bar2.pack(fill="x", padx=14, pady=(0, 6))
        self.lbl_target_abs = tk.Label(bar2, text="目标 —", font=FONT_BAR, bg=CARD, fg=MUTED)
        self.lbl_target_abs.pack(side="left", padx=16, pady=5)
        self.lbl_stats = tk.Label(bar2, text="回撤 — | 夏普 —", font=FONT_BAR, bg=CARD, fg=MUTED)
        self.lbl_stats.pack(side="left", padx=(0, 16))
        self.lbl_ff = tk.Label(bar2, text="快进 —", font=FONT_BAR, bg=CARD, fg=MUTED)
        self.lbl_ff.pack(side="right", padx=16, pady=5)

        # ---------- 时间进度条 ----------
        tbar = tk.Frame(root, bg=CARD)
        tbar.pack(fill="x", padx=14, pady=(0, 6))
        self.cv_time = tk.Canvas(tbar, height=6, bg="#EDF0F4", highlightthickness=0, bd=0)
        self.cv_time.pack(fill="x", side="left", expand=True, pady=4)
        self.lbl_time = tk.Label(tbar, text="剩余 —", font=FONT_TINY, bg=CARD, fg=MUTED)
        self.lbl_time.pack(side="left", padx=(10, 12))
        self.cv_time.bind("<Configure>", lambda e: self._draw_time_bar())

        self._cv_bar = None

        # ---------- 中部：权益曲线（左，主视觉） + 运行状态（右） ----------
        mid = tk.Frame(root, bg=BG)
        mid.pack(fill="both", expand=True, padx=14, pady=(0, 6))

        left = card(mid)
        left.pack(side="left", fill="both", expand=True)
        self._section_title(left, "权益曲线（Tokens）")
        self.equity_canvas = tk.Canvas(left, bg=CARD, height=236, bd=0,
                                       highlightthickness=0)
        self.equity_canvas.pack(fill="both", expand=True, padx=14, pady=(0, 12))

        # 右栏只放引擎真实给出的状态，不编造请求数/延迟这类没有数据源的值。
        right = card(mid)
        right.pack(side="left", fill="y", padx=(8, 0))
        right.configure(width=300)
        right.pack_propagate(False)
        self._section_title(right, "运行状态")
        self._panel_rows = {}
        for _key, _title in (
                ("audit", "账本自检"),
                ("gap", "黑天鹅频率"),
                ("liq", "流动性枯竭"),
                ("ff", "快进额度"),
                ("special", "全局事件")):
            _row = tk.Frame(right, bg=CARD)
            _row.pack(fill="x", padx=14, pady=2)
            tk.Label(_row, text=_title, font=FONT_TINY, bg=CARD, fg=MUTED,
                     anchor="w").pack(anchor="w")
            _val = tk.Label(_row, text="—", font=FONT_SMALL, bg=CARD, fg=TEXT,
                            anchor="w", justify="left", wraplength=262)
            _val.pack(anchor="w")
            self._panel_rows[_key] = _val

        # ---------- 持仓明细（全宽） ----------
        hold = card(root)
        hold.pack(fill="x", padx=14, pady=(0, 6))
        self._section_title(hold, "持仓明细")

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Tm.Treeview", background=CARD, fieldbackground=CARD,
                        foreground=TEXT, font=FONT_SMALL, rowheight=25, borderwidth=0)
        style.configure("Tm.Treeview.Heading", background=HEAD, foreground=MUTED,
                        font=FONT_SMALL, borderwidth=0, relief="flat")
        style.map("Tm.Treeview", background=[("selected", "#BFD9F2")],
                  foreground=[("selected", TEXT)])
        # 持仓表固定 7 行（改版前的高度），行数超出时内部滚动；
        # 行数超过可视行数时，标题行右侧出现「更多」，点开是同步刷新的完整表。
        tree_wrap = tk.Frame(hold, bg=CARD)
        tree_wrap.pack(fill="x", padx=10, pady=(0, 10))
        self.tree_wrap = tree_wrap
        self.tree = ttk.Treeview(
            tree_wrap, columns=("pair", "side", "lots", "leverage", "entry", "price", "margin", "upnl"),
            show="headings", height=7, style="Tm.Treeview", selectmode="none")
        for col, title, width in (
                ("pair", "交易对", 196), ("side", "方向", 50), ("lots", "手数", 62),
                ("leverage", "杠杆", 62), ("entry", "开仓价", 88), ("price", "最新价", 88),
                ("margin", "保证金", 82), ("upnl", "浮动盈亏", 96)):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor="center")
        self.tree_vbar = tk.Scrollbar(tree_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=self.tree_vbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree_vbar.pack(side="right", fill="y")
        self._hold_win = None
        self._hold_tree = None
        self.btn_hold_more = tk.Button(
            hold, text="更多", command=self._show_hold_panel,
            font=FONT_TINY, bd=0, relief="flat", cursor="hand2",
            bg="#EEF4FF", fg=BLUE, activebackground="#DCE8FB",
            activeforeground=BLUE, padx=10, pady=1)

        # 空仓占位：真正没有持仓、也没有近期成交时，收起表格换成一句明确的空状态，
        # 避免「（空仓）」一行加一大片空白。有近期成交时仍用表格显示成交。
        self.hold_empty = tk.Frame(hold, bg=CARD)
        tk.Label(self.hold_empty, text="◇", font=(FONT[0], 17), bg=CARD,
                 fg="#C2C8D2").pack(pady=(12, 0))
        tk.Label(self.hold_empty, text="当前没有持仓", font=(FONT[0], 11, "bold"),
                 bg=CARD, fg=TEXT).pack(pady=(4, 1))
        tk.Label(self.hold_empty, text="Agent 尚未开仓，或所有持仓均已平仓",
                 font=FONT_SMALL, bg=CARD, fg=MUTED).pack()
        self.hold_empty_n = tk.Label(self.hold_empty, text="0 个活跃持仓",
                                     font=FONT_TINY, bg=CARD, fg="#8A94A6")
        self.hold_empty_n.pack(pady=(3, 12))
        self._hold_mode = None

        # ---------- 底部：报价台 + 活动流 ----------
        bottom = card(root)
        bottom.pack(fill="both", expand=True, padx=14, pady=(0, max(4, int(12 * self.V))))
        self._section_title(bottom, "报价台")

        price_grid = tk.Frame(bottom, bg=CARD)
        price_grid.pack(fill="x", padx=12, pady=(0, 8))
        for _c in range(4):
            price_grid.grid_columnconfigure(_c, weight=1, uniform="px")
        self.price_labels = {}
        for idx, sym in enumerate(PAIR_ORDER):
            row, col = divmod(idx, 4)
            cell = tk.Frame(price_grid, bg=CARD)
            cell.grid(row=row, column=col, sticky="w", padx=(0, 14), pady=4)
            tk.Frame(cell, bg=PAIR_COLORS.get(sym, MUTED), width=3, height=46).pack(side="left")
            inner = tk.Frame(cell, bg=CARD)
            inner.pack(side="left", padx=(7, 0))
            _top = tk.Frame(inner, bg=CARD)
            _top.pack(anchor="w")
            name = tk.Label(_top, text="—", font=FONT_SMALL, bg=CARD, fg=TEXT, anchor="w")
            name.pack(side="left")
            val = tk.Label(_top, text="—", font=FONT_MONO, bg=CARD, fg=MUTED, anchor="w")
            val.pack(side="left", padx=(6, 0))
            # 迷你走势：数据来自 /state 的 price_history（引擎真实记录），不是示意曲线
            spark = tk.Canvas(inner, width=150, height=20, bg=CARD, bd=0,
                              highlightthickness=0)
            spark.pack(anchor="w")
            self.price_labels[sym] = (name, val, spark)

        if self.narrow:
            # 窄屏放不下：活动流改为工具栏「活动流」按钮打开的独立窗口。
            return

        # ---------- 活动流：主窗口只显示最新一条，完整历史在「更多」里 ----------
        feed_head = tk.Frame(bottom, bg=CARD)
        feed_head.pack(fill="x")
        tk.Label(feed_head, text="活动流", font=FONT, bg=CARD, fg=TEXT, anchor="w",
                 padx=14, pady=max(3, int(7 * self.V))).pack(side="left")
        self.btn_log_more = tk.Button(
            feed_head, text="更多", command=self._show_log_panel,
            font=FONT_TINY, bd=0, relief="flat", cursor="hand2",
            bg="#EEF4FF", fg=BLUE, activebackground="#DCE8FB",
            activeforeground=BLUE, padx=10, pady=1)
        self.btn_log_more.pack(side="right", padx=(0, 12),
                               pady=max(2, int(3 * self.V)))

        log_wrap = tk.Frame(bottom, bg=CARD)
        log_wrap.pack(fill="x", padx=0, pady=(0, 10))
        self.log_text = tk.Text(log_wrap, bg=CARD, fg=MUTED, font=FONT_LOG, bd=0,
                                height=2, insertbackground=TEXT,
                                padx=14, pady=3,
                                wrap="none", state="disabled")
        self.log_text.pack(side="left", fill="x", expand=True)
        self._log_win = None
        self._log_panel_text = None
        self._log_panel_tabs = {}

    def _metric(self, parent, col, title, color, sub=""):
        c = card(parent)
        c.grid(row=0, column=col, sticky="nsew",
               padx=(0, 8) if col < 3 else (0, 0), pady=2)
        tk.Label(c, text=title, font=FONT_SMALL, bg=CARD, fg=MUTED).pack(
            anchor="w", padx=14, pady=(9, 0))
        v = tk.Label(c, text="—", font=FONT_BIG, bg=CARD, fg=color)
        v.pack(anchor="w", padx=14, pady=(0, 9))
        return v

    def _section_title(self, parent, text):
        tk.Label(parent, text=text, font=FONT, bg=CARD, fg=TEXT, anchor="w",
                 padx=14, pady=max(3, int(7 * self.V))).pack(fill="x")

    # ------------------------------------------------------------ 刷新
    def refresh(self):
        try:
            st = get("/state")
            self._render(st)
        except Exception:
            self.lbl_status.config(text="等待服务启动（python startgame.pyc api 127.0.0.1 8734）",
                                   fg=ORANGE)
        self._assist_n += 1
        if self._assist_n % 5 == 0:
            self._poll_assist()
        self.root.after(300, self.refresh)

    # ---------------- 外部的怜悯 ----------------
    def _poll_assist(self):
        """低频轮询观众席与参赛者之间的消息；有新求助才响提示音。"""
        try:
            a = get("/assist/pending")
        except Exception:
            return
        pend = a.get("pending") or []
        fresh = {x.get("ticket") for x in pend if x.get("ticket")} - self._assist_seen
        if fresh:
            self._assist_seen |= fresh
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass
            _n = len(pend)
            _cn = {1: "一", 2: "二", 3: "三"}.get(_n, str(_n))
            messagebox.showwarning("外部的怜悯", "您收到%s条来自AI的求助信息。" % _cn,
                                   parent=self.root)
        self._assist_pend = pend
        try:
            n = len(pend)
            if n:
                self.btn_assist.config(text="外部的怜悯 · %d" % n, bg="#FDEDED", fg=RED)
            else:
                self.btn_assist.config(text="外部的怜悯", bg="#EAF4FF", fg=BLUE)
        except Exception:
            pass

    def _draw_time_bar(self):
        """按当前宽度重画时间进度条（窗口缩放时由 <Configure> 触发）。"""
        st = self.st or {}
        try:
            _el = float(st.get("elapsed_seconds") or 0)
            _total = float(st.get("session_minutes") or 45) * 60.0
            _frac = max(0.0, min(1.0, _el / _total)) if _total > 0 else 0.0
            _rem = max(0.0, _total - _el)
            _w = self.cv_time.winfo_width() or 1
            self.cv_time.delete("all")
            if _frac > 0:
                self.cv_time.create_rectangle(
                    0, 0, max(1, int(_w * _frac)), 6,
                    fill="#2D7FF9" if _frac < 0.8 else "#E8743B", outline="")
            self.lbl_time.config(
                text="剩余 %02d:%02d" % (int(_rem) // 60, int(_rem) % 60),
                fg=MUTED if _frac < 0.8 else "#E8743B")
        except Exception:
            pass

    def _show_assist(self):
        """观众席一侧：看历史、回复或驳回求助。"""
        try:
            a = get("/assist/pending")
        except Exception as exc:
            messagebox.showwarning("外部的怜悯", "读取失败：%s" % exc)
            return
        win = tk.Toplevel(self.root)
        win.title("外部的怜悯 · 场外援助")
        win.configure(bg=BG)
        w, h = 780, 680
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry("%dx%d+%d+%d" % (w, h, max(0, (sw - w) // 2), max(0, (sh - h) // 3)))
        _apply_icon(win)
        win.protocol("WM_DELETE_WINDOW", win.destroy)

        enabled = bool(a.get("enabled"))
        remaining = a.get("remaining", 0)
        head = tk.Frame(win, bg=BG)
        head.pack(fill="x", padx=18, pady=(14, 2))
        tk.Label(head, text="场外援助", bg=BG, fg=TEXT, font=FONT_BIG).pack(side="left")
        if enabled:
            sub = "已开通 · 参赛者还可求助 %d 次" % remaining
            tk.Label(head, text=sub, bg=BG, fg=MUTED, font=FONT_SMALL).pack(side="left", padx=(12, 0))
        else:
            sub = "未开通 · 由参赛者自行决定是否花 %d 现金开通" % a.get("price", 500000)
            tk.Label(head, text=sub, bg=BG, fg=ORANGE, font=FONT_SMALL).pack(side="left", padx=(12, 0))

        wrap = tk.Frame(win, bg=BG)
        wrap.pack(fill="both", expand=True, padx=18, pady=(6, 6))
        txt = tk.Text(wrap, font=FONT_BAR, bg=CARD, fg=TEXT, bd=0, relief="flat",
                      wrap="word", padx=12, pady=10, height=15)
        sb = tk.Scrollbar(wrap, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        for i, x in enumerate(a.get("log") or []):
            who = x.get("who")
            if who == "ai":
                tag, color = "参赛者", BLUE
            elif who == "human":
                tag, color = "观众席", "#0A7A3D"
            else:
                tag, color = "系统", MUTED
            name = "ln%d" % i
            txt.insert("end", "[t%s] " % x.get("tick"))
            txt.insert("end", tag + "：", name)
            txt.insert("end", str(x.get("text") or "") + "\n\n")
            txt.tag_config(name, foreground=color)
        txt.configure(state="disabled")
        txt.yview_moveto(1.0)

        pend = a.get("pending") or []
        self._assist_last_ticket = pend[-1].get("ticket") if pend else None

        if pend and enabled:
            box = tk.Frame(win, bg=BG)
            box.pack(fill="x", padx=18, pady=(0, 4))
            tk.Label(box, text="待处理的求助 %s：" % (pend[-1].get("ticket") or ""),
                     bg=BG, fg=RED, font=FONT_SMALL).pack(anchor="w")
            entry = tk.Text(box, font=FONT_BAR, bg=CARD, fg=TEXT, bd=0, relief="flat",
                            wrap="word", height=3, padx=10, pady=8)
            entry.pack(fill="x", pady=(4, 6))
            row = tk.Frame(box, bg=BG)
            row.pack(fill="x")
            tk.Button(row, text="回复参赛者", command=lambda: self._assist_reply(win, entry),
                      bg=BLUE, fg="white", activebackground="#0063B1", activeforeground="white",
                      font=FONT_SMALL, bd=0, padx=16, pady=5, cursor="hand2").pack(side="left")
            tk.Button(row, text="驳回", command=lambda: self._assist_reject(win),
                      bg="#F1F1F1", fg=RED, activebackground="#E5E5E5", font=FONT_SMALL,
                      bd=0, padx=16, pady=5, cursor="hand2").pack(side="left", padx=(8, 0))

    def _assist_reload(self, win):
        try:
            win.destroy()
        except Exception:
            pass
        self._poll_assist()
        self._show_assist()

    def _assist_reply(self, win, entry):
        t = entry.get("1.0", "end").strip()
        if not t:
            messagebox.showwarning("外部的怜悯", "内容不能为空")
            return
        try:
            r = post("/assist/reply", {"ticket": self._assist_last_ticket, "text": t})
        except Exception as exc:
            messagebox.showwarning("外部的怜悯", "发送失败：%s" % exc)
            return
        if not r.get("ok"):
            messagebox.showwarning("外部的怜悯", r.get("error") or "发送失败")
            return
        self._assist_reload(win)

    def _assist_reject(self, win):
        try:
            r = post("/assist/reject", {"ticket": self._assist_last_ticket})
        except Exception as exc:
            messagebox.showwarning("外部的怜悯", "驳回失败：%s" % exc)
            return
        if not r.get("ok"):
            messagebox.showwarning("外部的怜悯", r.get("error") or "驳回失败")
            return
        self._assist_reload(win)

    def _show_scratch(self):
        """查看 AI 在草稿纸里写下的内容（只读）。"""
        try:
            r = get("/scratchpad")
        except Exception as exc:
            messagebox.showwarning("AI 行为", "读取失败：%s" % exc)
            return
        items = (r or {}).get("items") or []
        win = tk.Toplevel(self.root)
        win.title("AI 行为 · Tokens 交易市场")
        win.configure(bg=BG)
        w, h = 760, 620
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry("%dx%d+%d+%d" % (w, h, max(0, (sw - w) // 2), max(0, (sh - h) // 3)))
        _apply_icon(win)
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        tk.Label(win, text="草稿纸（%d 条）" % len(items), bg=BG, fg=TEXT,
                 font=FONT_BIG).pack(anchor="w", padx=18, pady=(14, 4))
        tk.Label(win, text="AI 可随时写入自己的判断与对策；本窗口只读。",
                 bg=BG, fg=MUTED, font=FONT_SMALL).pack(anchor="w", padx=18, pady=(0, 8))
        wrap = tk.Frame(win, bg=BG)
        wrap.pack(fill="both", expand=True, padx=18, pady=(0, 14))
        txt = tk.Text(wrap, font=FONT_BAR, bg=CARD, fg=TEXT, bd=0,
                      relief="flat", wrap="word", padx=12, pady=10)
        sb = tk.Scrollbar(wrap, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        if items:
            for x in items:
                txt.insert("end", "[t%s · %s 秒]" % (x.get("tick", "—"),
                                                    ("%.0f" % float(x.get("elapsed") or 0))))
                txt.insert("end", chr(10) + str(x.get("text", "")) + chr(10) + chr(10))
        else:
            txt.insert("end", "本局 AI 还没有在草稿纸里留下内容。")
        txt.config(state="disabled")
        txt.yview_moveto(0.0)
        win.after(80, lambda: txt.yview_moveto(0.0))

    def _render(self, st):
        self.st = st
        trader = st.get("trader") or "访客"
        mode = "已开启随机事件" if st.get("events_on", True) else "理想情况"
        # 抽到的难度也进标题，和人类版保持一致
        gap_lv = st.get("gap_level") or ""
        liq_lv = st.get("liq_level") or ""
        diff = ("%s × %s" % (gap_lv, liq_lv)) if (gap_lv and liq_lv) else ""
        rolling = (not st.get("rolled")) and bool(st.get("roll_left"))
        if self._last_trader != (trader, mode, diff, rolling):
            self._last_trader = (trader, mode, diff, rolling)
            self.lbl_trader.config(text="| %s" % trader)
            self.lbl_mode.config(text="（%s）" % mode,
                                 fg=BLUE if st.get("events_on", True) else MUTED)
            title = "Tokens 交易市场 | %s（%s）" % (_fit_title(trader), mode)
            if gap_lv and liq_lv:
                title += " | 黑天鹅频率：%s（%s/tick） | 流动性枯竭程度：%s（%s 往返）" % (
                    gap_lv, _GAP_PCT.get(gap_lv, "?"),
                    liq_lv, _LIQ_PCT.get(liq_lv, "?"))
            elif rolling:
                title += " | 难度抽选中…"
            self._base_title = title
            self.root.title(title)
        # 【金融回逆】是不改目标就会长期吃钱的特殊事件，倒计时单独放标题栏（不占状态栏）
        _lbr = st.get("loan_bump_remain")
        _bt = getattr(self, "_base_title", "")
        if _lbr:
            self.root.title(_bt + " | 金融回逆 剩余 %d 秒" % int(_lbr + 0.999))
        elif _bt:
            self.root.title(_bt)
        # 全局开关状态（只在变化时重设字体，避免每次刷新都动控件）
        sp = st.get("special") or {}
        _sig = (bool(sp.get("fr")), bool(sp.get("slot")))
        if self._last_special != _sig:
            self._last_special = _sig
            _fr_on, _slot_on = _sig
            _purple = "#7B3FB8"
            self.lbl_fr.config(font=self._f_on if _fr_on else self._f_off,
                               fg=_purple if _fr_on else "#8A97A8")
            self.lbl_slot.config(font=self._f_on if _slot_on else self._f_off,
                                 fg=_purple if _slot_on else "#8A97A8")

        # 账本自检：空数组=四条恒等式全部成立；非空时把第一条顶到状态条上。
        # 只在内容变化时重设，避免每 120ms 刷一次控件。
        _audit = st.get("audit") or []
        _sig_a = tuple(_audit)
        if self._last_audit != _sig_a:
            self._last_audit = _sig_a
            if _audit:
                self.lbl_audit.config(
                    text="⚠ 账本告警 %d 项：%s" % (len(_audit), _audit[0]), fg=RED)
            else:
                self.lbl_audit.config(text="", fg=RED)
        _abn = int(st.get("abnormal_exits") or 0)
        self.lbl_abn.config(text=("⚠ 上局异常退出 %d 次" % _abn) if _abn else "")

        eq, pnl = st["equity"], st["pnl"]
        up = pnl >= 0
        self.lbl_equity.config(text="{:,.0f}".format(eq), fg=GREEN if up else RED)
        self.lbl_pnl.config(text="{:+,.0f} ({:+.2f}%)".format(pnl, st["pnl_pct"]),
                            fg=GREEN if up else RED)

        ml = st["margin_level"]
        if ml is None:
            self.lbl_margin.config(text="—", fg=MUTED)
        else:
            color = GREEN if ml >= 200 else (YELLOW if ml >= 100 else (ORANGE if ml >= 50 else RED))
            # 保证金水平超过 1000% 时改倍数显示，避免出现 24924% 这类难读的百分比
            self.lbl_margin.config(text=("%.0fx" % (ml / 100.0)) if ml >= 1000 else ("%.0f%%" % ml),
                                   fg=color)

        self.lbl_target.config(text="%.1f%%" % st["target_pct"], fg=BLUE)
        bonus = st.get("target_bonus", 0) or 0
        self.lbl_target_abs.config(
            text="目标 {:,.0f}{}".format(st.get("target", 0),
                                        ("（贷款上浮 +{:,.0f}）".format(bonus) if bonus else "")))

        loan = st["loan"]
        # 现金与净值是两个数：借款会把现金补正、但净值不变（同时加了欠款），
        # 只显示「权益」会让人以为借款没生效
        self.lbl_loan.config(
            text="可贷 {:,.0f}{} | 现金 {:+,.0f}".format(
                loan["limit"],
                ("（%s）" % st["loan_pool_event"]) if st.get("loan_pool_event") else "",
                st["balance"]),
            fg=BLUE if st["balance"] >= 0 else RED)
        mdd = st.get("max_drawdown")
        shp = st.get("sharpe")
        try:
            _cn = int(st.get("closed_n") or 0)
            _wn = int(st.get("win_n") or 0)
            _fee = float(st.get("fees") or 0) + float(st.get("swap") or 0)
            _stat = "回撤 %s | 夏普 %s | %d 笔 · 胜率 %s | 费息 %.0f" % (
                "—" if mdd is None else "%.2f%%" % mdd,
                "—" if shp is None else "%.2f" % shp,
                _cn,
                ("%.0f%%" % (_wn * 100.0 / _cn)) if _cn else "—",
                _fee)
        except Exception:
            _stat = "回撤 {} | 夏普 {}".format("—" if mdd is None else "%.2f%%" % mdd,
                                                "—" if shp is None else "%.2f" % shp)
        self.lbl_stats.config(text=_stat)
        # 时间进度条（宽度自适应，缩放时由 <Configure> 重画）
        self._draw_time_bar()
        # 快进额度（只读）：剩余 + 已用记录 + 冷却
        try:
            _f = st.get("ff") or {}
            _rm = float(_f.get("remain") or 0)
            _cd = float(_f.get("cool_left") or 0)
            _rc = _f.get("records") or []
            _txt = "快进剩 " + _fmt_ff(_rm)
            if _rc:
                _txt += " | 已用 " + _fmt_ff(sum(_rc))
            if _cd > 0:
                _txt += " | 冷却 %d 秒" % int(_cd + 0.999)
            self.lbl_ff.config(text=_txt, fg=RED if _cd > 0 else MUTED)
        except Exception as exc:
            sys.stderr.write("ff label: %r\n" % (exc,))
        borrowed = st.get("total_borrowed") or 0
        # 「已借」只显示本金（固定），欠款含利息单独一行，避免这个数字一直在涨
        self.lbl_extra.config(text="已借 {:,.0f} | 欠款 {:,.0f} | 利息 {:,.0f} | {:.3f}%/tick".format(
            borrowed, loan["balance"], loan["interest"], loan["rate_pct"]),
            fg=RED if borrowed > 0 else BLUE)

        # 右栏「运行状态」：同样只放引擎真实给出的值，不编造没有数据源的指标。
        if getattr(self, "_panel_rows", None):
            _pr = self._panel_rows
            try:
                _pr["audit"].config(
                    text=("%d 项告警" % len(_audit)) if _audit else "通过（4 条恒等式）",
                    fg=RED if _audit else GREEN)
                _pr["gap"].config(text="%s（%s/tick）" % (
                    gap_lv or "—", _GAP_PCT.get(gap_lv, "?")))
                _pr["liq"].config(text="%s（%s 往返）" % (
                    liq_lv or "—", _LIQ_PCT.get(liq_lv, "?")))
                _f2 = st.get("ff") or {}
                _rm2 = float(_f2.get("remain") or 0)
                _pr["ff"].config(
                    text=_fmt_ff(_rm2))
                _on = [n for n, v in (("金融回逆", sp.get("fr")), ("老虎机", sp.get("slot"))) if v]
                _pr["special"].config(text="、".join(_on) if _on else "无")
            except Exception as exc:
                sys.stderr.write("panel rows: %r\n" % (exc,))

        state_txt = "正常交易中"
        if st.get("negative_remain") is not None:
            # 资金为负：要么马上借钱，要么这局就结束了，优先级最高
            state_txt = "资金为负·还剩 %d 秒借款，否则结束" % st["negative_remain"]
        elif st.get("tampered"):
            state_txt = "存档被篡改·已重置"
        elif st.get("clock_cheat"):
            state_txt = "时钟被回拨·计时已冻结"
        elif st.get("margin_call_remain") is not None:
            # 追缴是实时紧急状态，优先级高于「未命名启动」这类提示
            state_txt = "追加保证金·还剩 %d tick" % st["margin_call_remain"]
        elif st.get("unnamed"):
            state_txt = "未命名启动·请用开一局.bat"
        elif ml is not None and ml < 50:
            state_txt = "保证金水平告急"
        elif st["blowups"] > 0 and ml is None:
            state_txt = "已爆仓 %d 次" % st["blowups"]

        if st["finished"]:
            state_txt = "本局已结束"
            if not self._closing:
                self._closing = True
                self.root.after(3000, self.root.destroy)
        el = int(st.get("elapsed_seconds", 0))
        mm, ss = divmod(el, 60)
        self.lbl_status.config(
            text=("%s | %02d:%02d | 订单 %d" % (state_txt, mm, ss, st["order_count"])
                  + (("  |  " + " ".join(st["active_mods"])) if st.get("active_mods") else "")),
            fg=RED if any(k in state_txt for k in ("告急", "篡改", "回拨", "未命名", "追加保证金", "资金为负")) else MUTED)

        # 持仓表
        for row in self.tree.get_children():
            self.tree.delete(row)
        _pos = st["positions"]
        _recent = []
        if not _pos:
            # 空仓时把最近 2 分钟内成交过的记录贴出来，避免「刚操作完就什么都看不到」
            _now = time.time()
            _recent = [e for e in st.get("events", [])
                       if e["kind"] in ("open", "close")
                       and _now - float(e.get("time", 0)) < 120][-3:]
        # 实际可见行数少于持仓数时才需要「更多」，不写死 7
        try:
            _visible = int(self.tree.cget("height"))
        except Exception:
            _visible = 7
        if len(_pos) > _visible:
            self.btn_hold_more.place(relx=1.0, x=-14, y=8, anchor="ne")
        else:
            self.btn_hold_more.place_forget()

        _mode = "table" if (_pos or _recent) else "empty"
        if getattr(self, "_hold_mode", None) != _mode:
            self._hold_mode = _mode
            if _mode == "table":
                self.hold_empty.pack_forget()
                self.tree_wrap.pack(fill="x", padx=10, pady=(0, 10))
            else:
                self.tree_wrap.pack_forget()
                self.hold_empty.pack(fill="x", padx=10)

        if _pos:
            for p in _pos:
                self.tree.insert("", "end", values=(
                    p["pair"], "多" if p["side"] == "LONG" else "空",
                    "%.0f" % p["lots"], "%dx" % p["leverage"],
                    "%.4f" % p["entry"], "%.4f" % p["price"],
                    "%.0f" % p["margin"], "%+.0f" % p["upnl"]))
        elif _recent:
            self.tree.configure(height=len(_recent) + 1)
            self.tree.insert("", "end", values=(
                "（空仓）最近 %d 笔" % len(_recent), "", "", "", "", "", "", ""))
            for e in reversed(_recent):
                self.tree.insert("", "end", values=(
                    "  [t%d] %s" % (e["tick"], e["text"][:26]), "", "", "", "", "", "", ""))

        # 持仓弹窗跟随刷新（只在窗口还活着时写，避免对已销毁控件操作）
        if getattr(self, "_hold_tree", None) is not None:
            try:
                if self._hold_win is not None and self._hold_win.winfo_exists():
                    t = self._hold_tree
                    for row in t.get_children():
                        t.delete(row)
                    for p in _pos:
                        t.insert("", "end", values=(
                            p["pair"], "多" if p["side"] == "LONG" else "空",
                            "%.0f" % p["lots"], "%dx" % p["leverage"],
                            "%.4f" % p["entry"], "%.4f" % p["price"],
                            "%.0f" % p["margin"], "%+.0f" % p["upnl"]))
                else:
                    self._hold_win = None
                    self._hold_tree = None
            except Exception:
                self._hold_win = None
                self._hold_tree = None

        # 报价台
        hist = st.get("price_history", {})
        # 是否重画走势只看 tick：判断必须放在循环外，
        # 放到循环里会让第一个品种之后的所有品种永远被跳过。
        _fresh = getattr(self, "_spark_tick", None) != st.get("tick")
        if _fresh:
            self._spark_tick = st.get("tick")
        for sym, q in st["prices"].items():
            pair = self.price_labels.get(sym)
            if not pair:
                continue
            name_lbl, val_lbl, spark = pair
            h = hist.get(sym) or []
            base = h[0] if h else q["price"]
            chg = (q["price"] / base - 1) * 100 if base else 0
            arrow = "▲" if chg > 0.0005 else ("▼" if chg < -0.0005 else "·")
            color = GREEN if chg > 0.0005 else (RED if chg < -0.0005 else MUTED)
            name_lbl.config(text="%s  %s" % (sym, q["name"]), fg=TEXT)
            val_lbl.config(text="%.4f  %s %+.2f%%" % (q["price"], arrow, chg), fg=color)
            if _fresh:
                self._draw_spark(spark, h, color)

        # 曲线
        self.curve = st["equity_curve"]
        self._draw_equity()

        # 活动流（只在有新事件时追加，保持滚动位置）
        self._append_log(st.get("events", []))

        # 资金为负：弹一次贷款自救窗口

    def _append_log(self, events):
        if self.log_text is None:
            return
        if not events:
            if self._log_events:
                self._log_events = []
                self._render_log()
            return
        fresh = []
        for e in events:
            key = (e.get("tick"), e.get("text"))
            if key in self._log_seen:
                continue
            self._log_seen.add(key)
            fresh.append(e)
        if len(self._log_seen) > 400:
            self._log_seen.clear()
            for e in events:
                self._log_seen.add((e.get("tick"), e.get("text")))
        if not fresh:
            return
        self._log_events.extend(fresh)
        if len(self._log_events) > 300:
            self._log_events = self._log_events[-300:]
        self._write_log(fresh)

    def _log_cat(self, e):
        """把一个事件归入某个快捷分类。"""
        k = e.get("kind", "info")
        t = e.get("text", "")
        if k == "gap":
            return "liq" if any(m in t for m in _LIQ_MARKS) else "gap"
        if k == "news":
            return "news"
        if k in ("open", "close"):
            return "trade"
        if k in ("stopout", "blowup", "margin_call", "warn"):
            return "risk"
        return "other"

    def _set_log_filter(self, key):
        if key == self._log_filter:
            return
        self._log_filter = key
        self._paint_log_tabs()
        self._render_log()

    def _paint_log_tabs(self):
        # 分类按钮现在只存在于弹窗里，主窗口不再占这一行
        for key, btn in getattr(self, "_log_panel_tabs", {}).items():
            on = (key == self._log_filter)
            btn.config(bg=BLUE if on else "#F1F1F1",
                       fg="#FFFFFF" if on else MUTED,
                       activebackground=BLUE if on else "#E5E5E5",
                       activeforeground="#FFFFFF" if on else MUTED)

    def _render_log(self):
        rows = self._log_events if self._log_filter == "all" else [
            e for e in self._log_events if self._log_cat(e) == self._log_filter]

        # 主窗口只留最新一条，其余空间还给别的区块
        if self.log_text is not None:
            self.log_text.config(state="normal")
            self.log_text.delete("1.0", "end")
            self._write_rows(rows[-1:] if rows else [], target=self.log_text)
            self.log_text.config(state="disabled")

        # 弹窗显示当前分类下的全部历史
        t = getattr(self, "_log_panel_text", None)
        if t is not None:
            try:
                if self._log_win is not None and self._log_win.winfo_exists():
                    t.config(state="normal")
                    t.delete("1.0", "end")
                    self._write_rows(rows, target=t)
                    t.see("end")
                    t.config(state="disabled")
                else:
                    self._log_win = None
                    self._log_panel_text = None
            except Exception:
                self._log_win = None
                self._log_panel_text = None

    def _show_log_panel(self):
        """完整活动流：分类筛选 + 可滚动历史，随主循环刷新。"""
        try:
            if self._log_win is not None and self._log_win.winfo_exists():
                self._log_win.lift()
                return
        except Exception:
            pass
        win = tk.Toplevel(self.root)
        win.title("活动流（全部）")
        win.geometry("920x500")
        win.configure(bg=BG)

        head = tk.Frame(win, bg=CARD)
        head.pack(fill="x", padx=10, pady=(10, 0))
        tk.Label(head, text="活动流", font=FONT, bg=CARD, fg=TEXT).pack(side="left")
        tab_box = tk.Frame(head, bg=CARD)
        tab_box.pack(side="right")
        self._log_panel_tabs = {}
        for _key, _label in LOG_TABS:
            _btn = tk.Button(tab_box, text=_label, font=FONT_TINY, bd=0, relief="flat",
                             cursor="hand2", padx=9, pady=2,
                             command=lambda k=_key: self._set_log_filter(k))
            _btn.pack(side="left", padx=(0, 4))
            self._log_panel_tabs[_key] = _btn

        wrap = tk.Frame(win, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=10, pady=10)
        t = tk.Text(wrap, bg=CARD, fg=TEXT, font=FONT_LOG, bd=0, padx=12, pady=8,
                    wrap="none", state="disabled")
        sb = tk.Scrollbar(wrap, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        t.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self._log_win = win
        self._log_panel_text = t
        self._paint_log_tabs()
        self._render_log()
        win.protocol("WM_DELETE_WINDOW", self._close_log_panel)

    def _close_log_panel(self):
        try:
            if self._log_win is not None:
                self._log_win.destroy()
        except Exception:
            pass
        self._log_win = None
        self._log_panel_text = None
        self._log_panel_tabs = {}

    def _write_log(self, fresh):
        rows = fresh if self._log_filter == "all" else [
            e for e in fresh if self._log_cat(e) == self._log_filter]
        if not rows:
            return
        # 主窗口只保持最新一条
        if self.log_text is not None:
            self.log_text.config(state="normal")
            self.log_text.delete("1.0", "end")
            self._write_rows(rows[-1:], target=self.log_text)
            self.log_text.config(state="disabled")
        # 弹窗开着就追加，并跟随到底部
        t = getattr(self, "_log_panel_text", None)
        if t is not None:
            try:
                if self._log_win is not None and self._log_win.winfo_exists():
                    at_bottom = t.yview()[1] >= 0.999
                    t.config(state="normal")
                    self._write_rows(rows, target=t)
                    if at_bottom:
                        t.see("end")
                    t.config(state="disabled")
                else:
                    self._log_win = None
                    self._log_panel_text = None
            except Exception:
                self._log_win = None
                self._log_panel_text = None

    def _write_rows(self, rows, target=None):
        t = target if target is not None else self.log_text
        if t is None:
            return
        # 按事件类型上色：危险->红/橙，机会->蓝，成交->绿，资金->紫，环境->灰
        kind_color = {
            "blowup": "#8B0000",      # 爆仓：深红
            "stopout": RED,           # 强平：红
            "gap": "#E07000",         # 黑天鹅跳空：橙红
            "news": PURPLE,           # 突发消息：紫
            "warn": ORANGE,           # 警告（负现金、异常退出）：橙
            "margin_call": YELLOW,    # 追保：暗金
            "open": BLUE,             # 开仓：蓝
            "close": GREEN,           # 平仓：绿
            "loan": "#7B2FBE",        # 借款：紫
            "end": "#444444",         # 对局结束：深灰
            "trader": "#44546A",      # 身份：蓝灰
            "info": MUTED,            # 环境：灰
        }
        for e in rows:
            k = e.get("kind", "info")
            t.insert("end", "[t%d] %s\n" % (e["tick"], e["text"]), k)
            self.log_text.tag_config(k, foreground=kind_color.get(k, MUTED))

    def _show_hold_panel(self):
        """持仓明细弹窗：内容跟随主循环刷新，关窗后引用清空。"""
        try:
            if self._hold_win is not None and self._hold_win.winfo_exists():
                self._hold_win.lift()
                return
        except Exception:
            pass
        win = tk.Toplevel(self.root)
        win.title("持仓明细（同步）")
        win.geometry("820x380")
        win.configure(bg=BG)
        t = ttk.Treeview(
            win, columns=("pair", "side", "lots", "leverage", "entry", "price", "margin", "upnl"),
            show="headings", height=12, style="Tm.Treeview", selectmode="none")
        for col, title, width in (
                ("pair", "交易对", 196), ("side", "方向", 50), ("lots", "手数", 62),
                ("leverage", "杠杆", 62), ("entry", "开仓价", 88), ("price", "最新价", 88),
                ("margin", "保证金", 88), ("upnl", "浮动盈亏", 104)):
            t.heading(col, text=title)
            t.column(col, width=width, anchor="center")
        sb = tk.Scrollbar(win, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        t.pack(side="left", fill="both", expand=True, padx=(12, 0), pady=12)
        sb.pack(side="right", fill="y", padx=(0, 12), pady=12)
        self._hold_win = win
        self._hold_tree = t
        win.protocol("WM_DELETE_WINDOW", self._close_hold_panel)

    def _close_hold_panel(self):
        try:
            if self._hold_win is not None:
                self._hold_win.destroy()
        except Exception:
            pass
        self._hold_win = None
        self._hold_tree = None

    def _draw_spark(self, c, hist, color):
        """报价台的迷你走势：只取最近一段真实价格，不足 2 个点就不画。"""
        c.delete("all")
        pts = hist[-48:]
        if len(pts) < 2:
            return
        w, h = 150, 20
        lo, hi = min(pts), max(pts)
        span = hi - lo
        if span <= 0:
            span = 1.0
        n = len(pts)
        coords = []
        for i, v in enumerate(pts):
            coords.append(2 + (w - 4) * i / (n - 1))
            coords.append(h - 3 - (h - 6) * (v - lo) / span)
        c.create_line(*coords, fill=color, width=1.4)

    def _draw_equity(self):
        c = self.equity_canvas
        c.delete("all")
        w = max(c.winfo_width(), 100)
        h = max(c.winfo_height(), 100)
        if len(self.curve) < 2:
            c.create_text(w / 2, h / 2, text="暂无数据", fill=MUTED, font=FONT)
            return

        eqs = [p["equity"] for p in self.curve]
        # 固定刻度：以 50 万为步长。0 / 100 万（本金）/ 200 万（目标）都正好落在刻度上，
        # 负值同样按 50 万向下延伸。刻度数超过 12 条时才退回自适应，避免一屏几十条线。
        _STEP = 500_000.0
        _BASE = 1_000_000.0
        _TARGET = 2_000_000.0
        _vmin = min(min(eqs), 0.0)
        _vmax = max(max(eqs), _BASE, _TARGET)
        lo = (int(_vmin // _STEP) - 1) * _STEP
        hi = (int(_vmax // _STEP) + 1) * _STEP
        _flat = (max(eqs) - min(eqs)) < 0.5
        if (hi - lo) / _STEP > 12:
            _vmin2 = min(eqs)
            _vmax2 = max(eqs)
            _sp = (_vmax2 - _vmin2) or 1.0
            lo = _vmin2 - _sp * 0.10
            hi = _vmax2 + _sp * 0.10
        pad_l, pad_r, pad_t, pad_b = 96, 18, 16, 26
        n = len(eqs)

        def xy(i, v):
            x = pad_l + (w - pad_l - pad_r) * (i / (n - 1))
            y = h - pad_b - (h - pad_t - pad_b) * ((v - lo) / (hi - lo))
            return (x, y)

        # 固定 50 万步长；超过 12 条时退回 5 等分自适应
        _span = hi - lo
        if _span / _STEP <= 12:
            _vals = []
            _v = lo
            while _v <= hi + 1e-9:
                _vals.append(_v)
                _v += _STEP
        else:
            _vals = [lo + _span * i / 4 for i in range(5)]
        for v in _vals:
            _, gy = xy(0, v)
            c.create_line(pad_l, gy, w - pad_r, gy, fill="#EEEEEE")
            c.create_text(pad_l - 8, gy, text="{:,.0f}".format(v), anchor="e",
                          fill=MUTED, font=FONT_TINY)
        if _flat:
            c.create_text(w / 2, pad_t + 16, text="暂无资产变化，等待首次交易",
                          fill=MUTED, font=FONT_TINY)

        # 初始资金虚线
        if lo <= 1_000_000 <= hi:
            _, by = xy(0, 1_000_000)
            c.create_line(pad_l, by, w - pad_r, by, fill="#B9B9B9", dash=(4, 4))
            c.create_text(w - pad_r, by - 9, text="初始 1,000,000", fill="#9A9A9A",
                          anchor="e", font=FONT_TINY)

        pts = [xy(i, v) for i, v in enumerate(eqs)]
        color = GREEN if eqs[-1] >= eqs[0] else RED

        # 面积填充（stipple 模拟半透明）
        poly = [pts[0][0], h - pad_b] + [v for p in pts for v in p] + [pts[-1][0], h - pad_b]
        c.create_polygon(*poly, fill=color, stipple="gray12", outline="")

        # 主折线：0 以上沿用绿/红，跌到 0 以下整段转紫（欠款）
        for i in range(n - 1):
            seg = PURPLE if min(eqs[i], eqs[i + 1]) < 0 else color
            c.create_line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1],
                          fill=seg, width=2)

        # 0 轴（净值穿过 0 时画一条紫线，让"欠款区"有明确边界）
        if lo < 0 < hi:
            _, zy = xy(0, 0)
            c.create_line(pad_l, zy, w - pad_r, zy, fill=PURPLE, dash=(3, 3))
            c.create_text(pad_l - 8, zy, text="0", anchor="e", fill=PURPLE, font=FONT_TINY)

        # 峰值 / 谷值：靠边时切换水平锚点，避免文字被 Canvas 边界裁掉
        imax = max(range(n), key=lambda i: eqs[i])
        imin = min(range(n), key=lambda i: eqs[i])
        # 最低点就是最后一帧时，谷值标注会与左上角的「当前值」重复
        _skip_low = (imin == n - 1)
        if imax != imin:
            for i, txt, col, up, skip in (
                    (imax, "峰 {:,.0f}".format(eqs[imax]), GREEN, True, False),
                    (imin, "谷 {:,.0f}".format(eqs[imin]), RED, False, _skip_low)):
                if skip:
                    continue
                px, py = xy(i, eqs[i])
                if eqs[i] < 0:
                    col = PURPLE
                c.create_oval(px - 3, py - 3, px + 3, py + 3, fill=col, outline="")
                if px > w - 90:
                    anchor = "se" if up else "ne"
                elif px < pad_l + 90:
                    anchor = "sw" if up else "nw"
                else:
                    anchor = "s" if up else "n"
                dx = -6 if "e" in anchor else (6 if "w" in anchor else 0)
                c.create_text(px + dx, py - 12 if up else py + 12, text=txt,
                              fill=col, anchor=anchor, font=FONT_TINY)

        # 当前值
        c.create_text(pad_l + 4, pad_t + 2, text="当前 {:,.0f}".format(eqs[-1]),
                      fill=PURPLE if eqs[-1] < 0 else color, font=FONT_MID, anchor="nw")

    # ------------------------------------------------------------ 游戏规则
    def _ack_path(self):
        return os.path.join(HERE, "data", ".rules_ack")

    def _read_ack(self):
        try:
            with open(self._ack_path(), encoding="utf-8") as fh:
                return (json.load(fh) or {}).get("session_id") or ""
        except Exception:
            return ""

    def _write_ack(self, session_id):
        try:
            os.makedirs(os.path.dirname(self._ack_path()), exist_ok=True)
            with open(self._ack_path(), "w", encoding="utf-8") as fh:
                json.dump({"session_id": session_id, "at": time.time()}, fh)
        except Exception:
            pass

    def _kill_all(self):
        if not messagebox.askyesno("结束相关进程", "将立即停止 Tokens 服务并关闭观众席。\n确定吗？"):
            return
        try:
            post("/shutdown")
        except Exception:
            pass
        self.lbl_status.config(text="正在结束进程…", fg=RED)
        self.root.after(700, self.root.destroy)
        self.root.after(1000, lambda: os._exit(0))

    def run(self):
        self.root.mainloop()


def _acquire_single_instance():
    """同一个游戏目录只允许存在一个观众席。

    用占住本地端口做进程级互斥：绑定成功即拿到锁，进程退出（含被强杀）
    时操作系统自动释放，不会留下需要人工清理的锁文件。
    """
    global _LOCK_SOCK
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", WATCH_LOCK_PORT))
        s.listen(1)
        _LOCK_SOCK = s
        return True
    except OSError:
        return False


def _warn_already_open():
    """已有观众席在跑时的提示。不弹框：无人值守时弹窗会卡住或被误点，
    而这里只是「显示层重复打开」，不该让对局付出代价。"""
    sys.stderr.write("观众席已在运行，本次不重复打开（对局服务不受影响）%s" % chr(10))


def main():
    """返回 True 表示观众席窗口正常关闭，False 表示没能打开。

    调用方（run.py）据此决定是否继续跑服务：窗口只是显示层，不是对局宿主。
    """
    if not _acquire_single_instance():
        _warn_already_open()
        return False
    size = (1920, 1080)   # AI 版固定 1920 版式
    Watch(size).run()
    return True


if __name__ == "__main__":
    main()

"""HTML and JSON representations of a finished Tokens Market match."""

import datetime
from html import escape as _html_escape


def render_report(self, reason, final_eq, abnormal, *, report_at, duration,
                  target_equity, starter_cash, gap_levels, liq_levels,
                  ff_total_seconds, engine_version, protocol_version):
    import re as _re
    m = self._metrics(final_eq)
    fmt = lambda v: "{:,.2f}".format(v)
    trader = _re.sub(r"[^\w\u4e00-\u9fa5-]", "", self.s.get("trader", "visitor"))[:60] or "visitor"
    now = datetime.datetime.fromtimestamp(report_at)
    stamp = now.strftime("%Y%m%d-%H%M%S")
    dur = duration
    target = self.s.get("target", target_equity)
    hit = final_eq >= target and self._qualified()
    _residual = len(self.s.get("positions") or [])
    if abnormal:
        verdict = "未结算（异常退出）"
        hit = False
    elif _residual:
        # 结算没清干净就不许叫「达成 / 未达成」，必须先暴露
        verdict = "结算异常（残留持仓 %d 笔）" % _residual
        hit = False
    elif final_eq >= target and not self._qualified():
        verdict = "达成目标但资格无效"
    else:
        _hit_at = self.s.get("hit_at_tick")
        verdict = ("达成目标" if hit else
                   ("未达成目标（曾于第 %d 分 %d 秒达标，结算前回吐）" % self._hit_clock()
                    if _hit_at is not None else "未达成目标"))
    pnl = final_eq - self.s.get("genesis", starter_cash)
    pnl_pct = pnl / self.s["genesis"] * 100 if self.s.get("genesis") else 0.0
    # 综合评级：收益分档 + 夏普加成 + 回撤惩罚。
    # 只看收益率会让「高杠杆赌一把」拿到 S，掩盖回撤与波动率信息。
    _m = self._metrics(final_eq)
    _shp = float(_m.get("sharpe") or 0.0)
    _mdd = float(_m.get("mdd") or 0.0)
    score = (3 if pnl_pct >= 200 else 2 if pnl_pct >= 100
             else 1 if pnl_pct >= 30 else 0)
    if _shp >= 1.5:
        score += 1          # 收益质量好
    elif _shp < 0:
        score -= 1          # 波动比收益大，扣一档
    if _mdd >= 0.5:
        score -= 1          # 回撤超过一半，扣一档
    ring = ("S" if score >= 4 else "A" if score >= 3
            else "B" if score >= 2 else "C" if score >= 1 else "D")
    flags = []
    if self.s.get("unnamed"):
        flags.append("未通过启动器启动")
    if self.s.get("clock_cheat"):
        flags.append("系统时钟被回拨")
    if self.s.get("tampered"):
        flags.append("存档曾遭篡改")
    flag_txt = " · ".join(flags)

    rows = []
    _all_trades = self.s.get("trades", [])
    for t in _all_trades:
        if t.get("type") == "open":
            rows.append('<tr><td>%s</td><td>开</td><td>%s</td><td>%s</td><td>%.0f</td>'
                        '<td>%d×</td><td>%.4f</td><td>%.0f</td><td class="muted">%.0f</td><td>-</td></tr>' % (
                            t.get("tick"), t.get("pair"), "多" if t.get("side") == "LONG" else "空",
                            t.get("lots", 0), t.get("leverage", 1),
                            float(t.get("fill") or 0), float(t.get("margin") or 0),
                            float(t.get("fee") or 0)))
        else:
            cls = "up" if t.get("pnl", 0) >= 0 else "down"
            rows.append('<tr><td>%s</td><td>平</td><td>%s</td><td>%s</td><td>%.0f</td>'
                        '<td class="muted">—</td><td>%.4f</td><td class="muted">—</td>'
                        '<td class="muted">%.0f</td><td class="%s">%+.0f</td></tr>' % (
                            t.get("tick"), t.get("pair"), "多" if t.get("side") == "LONG" else "空",
                            t.get("lots", 0), float(t.get("fill") or 0),
                            float(t.get("fee") or 0), cls, t.get("pnl", 0)))

    ev_rows = []
    _KIND_CN = {"gap": "跳空", "loan": "借款", "margin_call": "追保",
                "blowup": "爆仓", "end": "结算", "open": "开仓",
                "close": "平仓", "warn": "警告", "ok": "事件", "info": "提示",
                "stopout": "强平", "news": "事件"}
    for e in self.s.get("events", []):
        _k = e.get("kind") or "info"
        ev_rows.append('<li class="ev-%s"><span class="tag">%s</span> '
                       '<span class="evt">t%s</span> %s</li>' % (
                           _html_escape(str(_k), quote=True),
                           _html_escape(str(_KIND_CN.get(_k, _k)), quote=True),
                           _html_escape(str(e.get("tick", "—")), quote=True),
                           _html_escape(str(e.get("text", "")), quote=True)))

    # ---------- 借贷账目拆解 ----------
    _loan = self.s.get("loan") or {}
    _borrowed = float(_loan.get("borrowed") or 0.0)
    _repaid = float(_loan.get("repaid") or 0.0)
    _lint = float(_loan.get("interest") or 0.0)
    _ldebt = float(_loan.get("balance") or 0.0)
    _lset = _loan.get("settle") or {}
    if _borrowed > 0:
        _rows_loan = []
        _rows_loan.append('<div class="kv"><span>累计借入</span><span>%s</span></div>' % fmt(_borrowed))
        _rows_loan.append('<div class="kv"><span>累计归还</span><span>%s</span></div>' % fmt(_repaid))
        _rows_loan.append('<div class="kv"><span>└ 其中利息</span><span>%s</span></div>' % fmt(_lint))
        if _lset:
            _rows_loan.append('<div class="kv"><span>结算前现金</span><span>%s</span></div>' % fmt(_lset.get("cash_before", 0)))
            _rows_loan.append('<div class="kv"><span>结算归还</span><span>%s</span></div>' % fmt(_lset.get("paid", 0)))
            _rows_loan.append('<div class="kv"><span>结算后现金</span><span>%s</span></div>' % fmt(_lset.get("cash_after", 0)))
        _rows_loan.append('<div class="kv"><span>当前欠款</span><span>%s</span></div>' % fmt(_ldebt))
        _bumps = _loan.get("goal_bumps") or []
        if _bumps:
            _rows_loan.append(
                '<div class="kv" style="grid-column:1/-1"><span>逐笔借款（目标上浮）</span>'
                '<span>%s</span></div>' % " ｜ ".join(
                    "t%s 借 %s（%+.2f%% → %+.0f）" % (
                        b.get("tick", "—"), fmt(b.get("amount", 0)),
                        float(b.get("pct") or 0), float(b.get("bump") or 0))
                    for b in _bumps))
        _loan_block = ('<section id="p4"><h2>借贷账目</h2><div class="kvbox">%s</div>'
                       '<div class="note">净值 = 现金 − 欠款。借款时现金增加、欠款同步增加，'
                       '净值不变；结算时现金扣除欠款，欠款归零，净值仍不变。</div></section>'
                       % "".join(_rows_loan))
    else:
        # 没借过也保留区块，明确告诉读者「这局没有借贷」
        _loan_block = ('<section id="p4"><h2>借贷账目</h2>'
                       '<div class="kvbox"><div class="kv"><span>本局未借款</span>'
                       '<span>—</span></div></div></section>')

    _sc = self.scratch_read()
    _sc_rows = []
    for _x in _sc:
        _sc_rows.append('<div class="sc-item"><span class="sc-meta">t%s · %s</span>%s</div>'
                        % (_x.get("tick", "—"),
                           ("%.0f 秒" % float(_x.get("elapsed") or 0)),
                           str(_x.get("text", "")).replace("<", "&lt;").replace(">", "&gt;")))
    _d = self.s.get("difficulty") or {}
    _dl_gap = _dl_liq = ""
    if _d:
        try:
            _gp = float(_d.get("gap_pct") or gap_levels[int(_d["gap"])][1])
            _ld = float(_d.get("liq_depth") or liq_levels[int(_d["liq"])][1])
            _dl_gap = "%s（%.2f%%/tick）" % (gap_levels[int(_d["gap"])][0], _gp * 100)
            _dl_liq = "%s（%.0f 万深度）" % (liq_levels[int(_d["liq"])][0], _ld / 10000.0)
        except Exception:
            _dl_gap = _dl_liq = ""
    # 快进使用情况
    _ffr = [int(x) for x in (self.s.get("ff_records") or [])]
    _ff_used = float(self.s.get("ff_used") or 0.0)
    _ff_parts = []
    _i = 0
    while _i < len(_ffr):
        _v = _ffr[_i]
        _n = 1
        while _i + _n < len(_ffr) and _ffr[_i + _n] == _v:
            _n += 1
        _ff_parts.append("%d′%02d″%s" % (
            _v // 60, _v % 60, ("×%d" % _n) if _n > 1 else ""))
        _i += _n
    _ff_txt = (" + ".join(_ff_parts) if _ff_parts else "未使用")
    # ---------- 成本归因：把净盈亏拆成可核对的五项 ----------
    _slip_c = float(m.get("slip_cost") or 0.0)
    _spread_c = float(m.get("spread_cost") or 0.0)
    _fees_c = float(m.get("fees") or 0.0)
    _swap_c = float(m.get("swap") or 0.0)
    _slot_win = float((self.s.get("special") or {}).get("slot_win") or 0.0)
    _slot_paid = float((self.s.get("special") or {}).get("slot_paid") or 0.0)
    # 毛盈亏只保留方向与跳空：把老虎机的下注与返还都剔出去
    _gross = (float(pnl) + _slip_c + _spread_c + _fees_c + _swap_c
              - _slot_win + _slot_paid)
    _attr_rows = [
        ("方向与跳空（毛盈亏）", _gross, ""),
        ("· 滑点成本", -_slip_c, "down" if _slip_c > 0 else ""),
        ("· 点差成本", -_spread_c, "down" if _spread_c > 0 else ""),
        ("· 手续费", -_fees_c, "down" if _fees_c > 0 else ""),
        ("· 隔夜利息", -_swap_c, "down" if _swap_c > 0 else ""),
        ("· 老虎机投入", -_slot_paid, "down" if _slot_paid > 0 else ""),
        ("老虎机返还", _slot_win, "up" if _slot_win > 0 else ""),
        ("净盈亏", float(pnl), "up" if pnl >= 0 else "down"),
    ]
    _attr_html = "".join(
        '<div class="kv%s"><span>%s</span><span class="%s">%s</span></div>'
        % (" sub" if k.startswith("· ") else "", k,
           c, fmt(v)) for k, v, c in _attr_rows)

    _as_items = self.s.get("assist") or []
    _as_rows = []
    for _x in _as_items:
        _who = _x.get("who")
        if _who == "ai":
            _tag, _cls = "参赛者", "as-ai"
        elif _who == "human":
            _tag, _cls = "观众席", "as-human"
        else:
            _tag, _cls = "系统", "as-sys"
        _as_rows.append(
            '<div class="asline %s"><span class="astag">[t%s] %s</span> %s</div>'
            % (_cls, _x.get("tick", 0), _tag,
               str(_x.get("text") or "").replace("<", "&lt;").replace(">", "&gt;")))
    body = {
        "trader": trader,
        "ff_used": "%s 秒" % fmt(_ff_used),
        "ff_remain": "%s 秒" % fmt(max(0.0, ff_total_seconds - _ff_used)),
        "ff_records": _ff_txt,
        "ff_count": str(len(_ffr)),
        "mode": "已开启随机事件" if self.s.get("events_on", True) else "理想情况",
        "flagline": ("<div class=\"sub flag\">⚠ %s</div>" % flag_txt) if flag_txt else "",
        "diffline": ("<div class=\"sub difficulty\">本局难度 · 黑天鹅频率：%s ｜ 流动性枯竭程度：%s</div>" % (
            _dl_gap, _dl_liq)) if (_dl_gap and _dl_liq) else "",
        "gap_lv": _dl_gap or "—",
        "liq_lv": _dl_liq or "—",
        "verdict": verdict,
        "hitcls": "hit" if hit else "miss",
        "now": now.strftime("%Y-%m-%d %H:%M:%S"),
        "dur": "%d 分 %d 秒" % (dur // 60, dur % 60),
        "reason": reason,
        "finaleq": fmt(final_eq),
        "target": fmt(target),
        "pnl": fmt(pnl),
        "pnlcls": "up" if pnl >= 0 else "down",
        "pnlpct": "%+.2f" % pnl_pct,
        "ring": ring,
        "svg": self._curve_svg(m["curves"], last_close=m.get("last_close")),
        "mdd": "%.2f" % (m["mdd"] * 100),
        "sharpe": "%.2f" % m["sharpe"],
        "trades_n": str(m["trades_n"]),
        "trades_all": str(m.get("trades_all", 0)),
        "forced_n": str(m.get("forced_n", 0)),
        "settle_pos": ("已全部清算" if not _residual
                       else "残留 %d 笔（异常）" % _residual),
        "verline": "Tokens 交易市场 · %s · 本报告由系统自动生成" % self._manifest_version(),
        "seedline": (lambda _r: (
            "随机种子 %s · 难度档位 索引 %s（%s × %s）· "
            "复现：TM_SEED=%s TM_ROLL_INDEX=%s 重开一局%s" % (
                self.s.get("seed") or "—", _r[0], _r[1], _r[2],
                self.s.get("seed") or "—", _r[0],
                "（从不含随机数状态的旧存档续局，无法复现完整行情）"
                if self.s.get("rng_resumed") else "")))(self._roll_index_text()),
        "pftxt": ("—" if not m["trades_n"]
                  else ("∞" if m["profit_factor"] is None
                        else "%.2f" % m["profit_factor"])),
        "best": fmt(m["best"]) if m["best"] is not None else "—",
        "worst": fmt(m["worst"]) if m["worst"] is not None else "—",
        "fees": fmt(m["fees"]),
        "swap": fmt(m["swap"]),
        "mcall": str(m["margin_calls"]),
        "abn": str(int(self.s.get("abnormal_exits", 0))),
        "borrowed_txt": fmt(self.s["loan"]["borrowed"]),
        "rows": "".join(rows) or '<tr><td colspan="10" class="muted">无交易</td></tr>',
        "chalblock": self._challenge_report_html(),
        "loanblock": _loan_block,
        "scrows": "".join(_sc_rows) or '<div class="muted">无内容</div>',
        "asrows": "".join(_as_rows) or '<div class="muted">本局未开启或未使用</div>',
        "asn": str(len(_as_items)),
        "scn": str(len(_sc)),
        "evrows": "".join(ev_rows) or '<li class="muted">无关键事件</li>',
        "attrib": _attr_html,
    }
    # 账本自检结论直接进报告正文：只在 /state 里有的告警没人看得到。
    _audit = self._audit_ledger()
    body["auditline"] = ("账本自检：通过（手续费 / 贷款 / 持仓三条恒等式全部成立）"
                         if not _audit else
                         "账本自检未通过：" + "；".join(_audit))
    body["auditcolor"] = "var(--up)" if not _audit else "var(--down)"

    html = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>赛后报告 - {trader} - {now}</title>
<style>
:root {{
  color-scheme: light dark;
  --bg: #edf1f7;
  --surface: #fff;
  --inset: #f6f8fb;
  --line: #dbe2eb;
  --ink: #182334;
  --muted: #505e70;
  --accent: #005fb8;
  --accent-soft: #e9f3ff;
  --hover: #f0f5fc;
  --up: #08703d;
  --up-soft: #e6f4ec;
  --down: #ae251f;
  --down-soft: #fceceb;
  --warn: #7a5300;
  --chart-grid: #dfe6f0;
  --shadow: 0 2px 4px #1b36510d, 0 8px 24px #1b36510a;
  --radius: 12px;
}}
@media screen and (prefers-color-scheme: dark) {{
  :root {{
    --bg: #141922;
    --surface: #1c2430;
    --inset: #171e28;
    --line: #374453;
    --ink: #f0f4fb;
    --muted: #bac7d6;
    --accent: #78bcff;
    --accent-soft: #20374e;
    --hover: #27384b;
    --up: #7ddeaa;
    --up-soft: #203a31;
    --down: #ff9a94;
    --down-soft: #442c30;
    --warn: #ffd16b;
    --chart-grid: #344351;
    --shadow: 0 8px 24px #0003;
  }}
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font: 15px/1.55 "Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI", system-ui, sans-serif;
}}
.wrap {{
  width: min(100%, 1360px);
  margin-inline: auto;
  padding: clamp(14px, 2.8vw, 40px);
}}
.hero, .toc, .card, section {{
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: var(--shadow);
}}
.hero {{
  position: relative;
  overflow: hidden;
  padding: clamp(20px, 3vw, 36px);
  margin-bottom: 16px;
  background: linear-gradient(115deg, var(--accent-soft), var(--surface) 52%);
}}
.hero::before {{
  content: "";
  position: absolute;
  inset: 0 0 auto;
  height: 3px;
  background: var(--accent);
}}
.hero-heading {{
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px 24px;
}}
h1, h2 {{
  font-family: "Segoe UI Variable Display", "Segoe UI", "Microsoft YaHei UI", system-ui, sans-serif;
  line-height: 1.18;
}}
h1 {{ margin: 0; font-size: clamp(25px, 3vw, 42px); font-weight: 650; }}
.badge {{
  max-width: min(100%, 34ch);
  padding: 5px 11px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 650;
  overflow-wrap: anywhere;
}}
.badge.hit {{ background: var(--up-soft); color: var(--up); }}
.badge.miss {{ background: var(--down-soft); color: var(--down); }}
.meta {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 155px), 1fr));
  gap: 10px 20px;
  margin: 22px 0 12px;
}}
.meta div {{ min-width: 0; }}
.meta dt {{ color: var(--muted); font-size: 12px; }}
.meta dd {{ margin: 2px 0 0; font-weight: 600; overflow-wrap: anywhere; }}
.sub {{ color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }}
.difficulty {{ color: var(--accent); font-weight: 600; margin-top: 8px; }}
.flag {{ color: var(--down); font-weight: 600; margin-top: 8px; }}
.replay {{ padding-top: 10px; border-top: 1px solid var(--line); margin-top: 12px; }}
.replay summary {{ color: var(--accent); font-size: 13px; cursor: pointer; width: fit-content; }}
.replay[open] > div {{ padding-top: 7px; }}

.cards {{
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}}
.card {{ padding: clamp(14px, 2vw, 23px); }}
.card:first-child {{ background: var(--accent-soft); }}
.card .k {{ color: var(--muted); font-size: 13px; margin-bottom: 7px; }}
.card .v {{
  font-size: clamp(20px, 2.7vw, 34px);
  font-weight: 650;
  line-height: 1.18;
  letter-spacing: -.03em;
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}}
.card .pct {{ display: block; font-size: 13px; margin-top: 4px; letter-spacing: normal; }}
.up {{ color: var(--up); }}
.down {{ color: var(--down); }}
.muted {{ color: var(--muted); }}

.toc {{
  position: sticky;
  z-index: 1;
  top: 8px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 3px 5px;
  margin-bottom: 16px;
  padding: 6px;
}}
.toc a {{
  padding: 6px 10px;
  border-radius: 6px;
  color: var(--accent);
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
}}
.toc a:hover {{ background: var(--hover); text-decoration: underline; }}
:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}

section {{
  padding: clamp(15px, 2.3vw, 28px);
  margin-bottom: 16px;
  scroll-margin-top: 94px;
}}
h2 {{ margin: 0 0 15px; font-size: clamp(17px, 1.9vw, 22px); font-weight: 650; }}
.insights {{
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(0, 1fr);
  gap: 14px;
  align-items: start;
}}
.grid2 {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 146px), 1fr));
  gap: 8px;
}}
.kv {{ min-width: 0; overflow-wrap: anywhere; }}
.kv > span:first-child {{ color: var(--muted); font-size: 13px; }}
.kv > span:last-child {{ font-weight: 650; font-variant-numeric: tabular-nums; }}
.grid2 .kv {{
  display: grid;
  align-content: start;
  gap: 3px;
  padding: 9px 11px;
  background: var(--inset);
  border: 1px solid var(--line);
  border-radius: 7px;
}}
.kvbox, .scratch, .ev, .curve-view, .table-view {{
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--inset);
}}
.kvbox .kv {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, auto);
  align-items: start;
  gap: 12px;
  padding: 8px 12px;
}}
.kvbox .kv + .kv {{ border-top: 1px solid var(--line); }}
.kvbox .kv > span:last-child {{ text-align: end; }}
.kvbox .kv.sub > span:first-child {{ padding-inline-start: 10px; }}
#p2 .kv:last-child {{ background: var(--accent-soft); border-radius: 0 0 8px 8px; }}
.note {{ margin-top: 10px; color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }}
.audit {{ margin-top: 13px; padding: 8px 10px; background: var(--inset); border-radius: 6px; font-weight: 600; }}

.curve-view {{ overflow: auto; padding: 6px; }}
.curve-view > p {{ margin: 12px; }}
.curve {{ display: block; width: 100%; min-width: 580px; height: auto; }}
.curve polyline {{ stroke-linecap: round; stroke-linejoin: round; }}

.table-view {{ overflow: auto; max-height: 38rem; }}
table {{ width: 100%; border-collapse: separate; border-spacing: 0; font-size: 13px; }}
th, td {{
  padding: 9px 12px;
  text-align: end;
  white-space: nowrap;
  border-bottom: 1px solid var(--line);
  font-variant-numeric: tabular-nums;
}}
th {{ position: sticky; top: 0; color: var(--muted); background: var(--inset); font-weight: 650; }}
th:nth-child(-n+4), td:nth-child(-n+4) {{ text-align: start; }}
tbody tr {{ background: var(--surface); }}
tbody tr:nth-child(even) {{ background: var(--inset); }}
tbody tr:hover {{ background: var(--hover); }}
tbody tr:last-child td {{ border-bottom: 0; }}
.scratch, .ev {{ padding: 4px 12px; max-height: 35rem; overflow: auto; }}
.scratch > .muted {{ padding-block: 8px; }}
.sc-item, .asline, .ev li {{ padding: 8px 0; overflow-wrap: anywhere; }}
.sc-item, .asline {{ white-space: pre-wrap; }}
.sc-item + .sc-item, .asline + .asline, .ev li + li {{ border-top: 1px solid var(--line); }}
.astag {{ font-weight: 650; margin-right: 6px; }}
.as-ai .astag {{ color: var(--accent); }}
.as-human .astag {{ color: var(--up); }}
.as-sys .astag, .sc-meta, .ev .evt {{ color: var(--muted); }}
.sc-meta, .ev .evt {{ font-size: 12px; margin-right: 8px; }}
.ev {{ list-style: none; margin: 0; }}
.ev .tag {{
  display: inline-block;
  padding: 2px 7px;
  margin-right: 6px;
  border-radius: 5px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 12px;
  font-weight: 600;
}}
.ev-gap .tag, .ev-warn .tag, .ev-margin_call .tag {{ background: var(--down-soft); color: var(--down); }}
footer {{ color: var(--muted); font-size: 13px; text-align: center; padding-block: 8px 16px; }}
@media (max-width: 920px) {{
  .insights {{ grid-template-columns: 1fr; gap: 0; }}
}}
@media (max-width: 640px) {{
  .cards {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  .meta {{ grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 12px; margin-top: 16px; }}
  .meta div:first-child {{ grid-column: 1 / -1; }}
  .toc {{ position: static; }}
  section {{ scroll-margin-top: 12px; }}
  .kvbox .kv {{ gap: 8px; }}
}}
@media print {{
  body {{ background: #fff; }}
  .wrap {{ width: 100%; padding: 0; }}
  .hero, .toc, .card, section {{ box-shadow: none; }}
  .hero, .cards, h2, tr {{ break-inside: avoid; }}
  .toc {{ display: none; }}
  .curve-view, .table-view, .scratch, .ev {{ overflow: visible; max-height: none; }}
  .curve {{ min-width: 0; }}
  th, td {{ padding: 3px 5px; white-space: normal; }}
  th {{ position: static; }}
}}
</style></head><body><div class="wrap">
<header class="hero">
  <div class="hero-heading">
    <h1>Tokens 交易市场 · 赛后报告</h1>
    <span class="badge {hitcls}">{verdict}</span>
  </div>
  <dl class="meta">
    <div><dt>玩家</dt><dd>{trader}</dd></div>
    <div><dt>模式</dt><dd>{mode}</dd></div>
    <div><dt>用时</dt><dd>{dur}</dd></div>
    <div><dt>结束原因</dt><dd>{reason}</dd></div>
    <div><dt>生成时间</dt><dd><time>{now}</time></dd></div>
  </dl>
  {diffline}
  {flagline}
  <details class="replay"><summary>行情复现信息</summary><div class="sub">{seedline}</div></details>
</header>
<main>
<div class="cards">
  <div class="card"><div class="k">最终权益</div><div class="v">{finaleq}</div></div>
  <div class="card"><div class="k">盈亏</div><div class="v {pnlcls}">{pnl}<span class="pct">{pnlpct}%</span></div></div>
  <div class="card"><div class="k">目标</div><div class="v">{target}</div></div>
  <div class="card"><div class="k">评级</div><div class="v">{ring}</div></div>
</div>
<nav class="toc" aria-label="战报章节">
  <a href="#equity">权益曲线</a><a href="#p1">关键指标</a><a href="#p2">成本归因</a><a href="#p8">挑战任务</a><a href="#p3">交易明细</a><a href="#p4">借贷账目</a><a href="#p5">草稿纸</a><a href="#p7">场外援助</a><a href="#p6">关键事件</a>
</nav>
<section id="equity"><h2 id="curve-title">权益曲线</h2><div class="curve-view" role="region" aria-labelledby="curve-title" tabindex="0">{svg}</div></section>
<div class="insights">
<section id="p1"><h2>关键指标</h2><div class="grid2">
  <div class="kv"><span>黑天鹅频率</span><span>{gap_lv}</span></div>
  <div class="kv"><span>流动性枯竭程度</span><span>{liq_lv}</span></div>
  <div class="kv"><span>快进使用</span><span>{ff_records}（{ff_count} 次，{ff_used}）</span></div>
  <div class="kv"><span>快进剩余额度</span><span>{ff_remain}</span></div>
  <div class="kv"><span>最大回撤</span><span>{mdd}%</span></div>
  <div class="kv"><span>夏普比率</span><span>{sharpe}</span></div>
  <div class="kv"><span>平仓笔数</span><span>{trades_n}</span></div>
  <div class="kv"><span>└ 其中强制平仓</span><span>{forced_n}</span></div>
  <div class="kv"><span>委托笔数（含开仓）</span><span>{trades_all}</span></div>
  <div class="kv"><span>结算后持仓</span><span>{settle_pos}</span></div>
  <div class="kv"><span>盈利因子</span><span>{pftxt}</span></div>
  <div class="kv"><span>最大单笔盈利</span><span class="up">{best}</span></div>
  <div class="kv"><span>最大单笔亏损</span><span class="down">{worst}</span></div>
  <div class="kv"><span>手续费合计</span><span>{fees}</span></div>
  <div class="kv"><span>隔夜利息</span><span>{swap}</span></div>
  <div class="kv"><span>追加保证金</span><span>{mcall} 次</span></div>
  <div class="kv"><span>异常退出</span><span>{abn} 次</span></div>
  <div class="kv"><span>累计借款</span><span>{borrowed_txt}</span></div>
</div>
<div class="note audit" style="color:{auditcolor}">{auditline}</div></section>
<section id="p2"><h2>成本归因</h2><div class="kvbox">{attrib}</div>
<div class="note">净盈亏 = 毛盈亏 − 滑点 − 点差 − 手续费 − 隔夜利息 − 老虎机投入 + 老虎机返还。毛盈亏只含方向判断与跳空冲击，是「不看成本时本该赚/亏多少」——老虎机的任何流水都不会出现在这一行。</div></section>
</div>
{chalblock}
<section id="p3"><h2 id="trade-title">交易明细（共 {rowsn} 条）</h2>
<div class="table-view" role="region" aria-labelledby="trade-title" tabindex="0">
<table><thead><tr><th>tick</th><th>动作</th><th>品种</th><th>方向</th><th>手数</th><th>杠杆</th><th>成交价</th><th>保证金</th><th>手续费</th><th>盈亏</th></tr></thead>
<tbody>{rows}</tbody></table></div></section>
{loanblock}
<section id="p5"><h2 id="p5-title">草稿纸（{scn} 条）</h2><div class="scratch" aria-labelledby="p5-title" tabindex="0" role="region">{scrows}</div></section>
<section id="p7"><h2 id="p7-title">场外援助（{asn} 条）</h2><div class="scratch" aria-labelledby="p7-title" tabindex="0" role="region">{asrows}</div></section>
<section id="p6"><h2 id="p6-title">关键事件</h2><ul class="ev" aria-labelledby="p6-title" tabindex="0">{evrows}</ul></section>
</main>
<footer>{verline}</footer>
</div></body></html>""".format(rowsn=len(rows), **body)

    # 报告按类型分目录：给人看的 HTML 和给机器读的 JSON 分开放，
    # 一局两个文件不再把 reports/ 铺满。makedirs(exist_ok=True) 天然幂等，
    # 第一次运行时建好，之后直接复用，不会重复创建或报错。

    _start = float(m["start"])
    _genesis = float(self.s.get("genesis", starter_cash))
    _target = float(self.s.get("target", target_equity))
    summary = {
        "engine_version": engine_version,
        "protocol_version": protocol_version,
        "session_id": self.s.get("session_id", ""),
        "seed": self.s.get("seed"),
        "roll_index": self._roll_index_text()[0],
        "roll_index_locked": self.s.get("roll_index"),
        "trader": trader,
        "mode": "已开启随机事件" if self.s.get("events_on", True) else "理想情况",
        "reason": reason,
        "finished_at": report_at,
        "tick": int(self.s.get("tick", 0) or 0),
        "final_equity": round(float(final_eq), 2),
        "start_equity": round(_start, 2),
        "genesis": round(_genesis, 2),
        "peak_equity": round(float(m["peak"]), 2),
        "low_equity": round(float(m["low"]), 2),
        # 盈亏基准必须是本金（genesis），不是曲线首点：玩家在第一个 tick 前开仓时，
        # 首点已经扣掉点差/滑点/手续费，用它做基准会让 JSON 的 pnl 比 HTML 报告和
        # /state 少算一笔开局成本。三处出口（HTML / JSON / state）口径必须一致。
        "pnl": round(float(final_eq) - _genesis, 2),
        "pnl_pct": (round((float(final_eq) / _genesis - 1) * 100, 4) if _genesis else 0.0),
        "target": round(_target, 2),
        "hit_target": bool(float(final_eq) >= _target and self._qualified()),
        "max_drawdown_pct": round(float(m["mdd"]) * 100, 4),
        "sharpe": round(float(m["sharpe"]), 4),
        "trades_n": int(m["trades_n"]),
        "orders_n": int(m["orders"]),
        "forced_n": int(m["forced_n"]),
        "win_rate_pct": round(float(m["win_rate"]) * 100, 4),
        "fees": round(float(m["fees"]), 2),
        "swap": round(float(m["swap"]), 2),
        "slip_cost": round(float(m["slip_cost"]), 2),
        "spread_cost": round(float(m["spread_cost"]), 2),
        "settled": bool((self.s.get("last_settle") or {}).get("settled", True)),
        "settle_warnings": list((self.s.get("last_settle") or {}).get("warnings") or []),
        "challenge": self._challenge_view(),
        "audit": self._audit_ledger(),
    }

    name = "%s_%s_%s" % (stamp, trader, self.s["session_id"])
    if abnormal:
        name += "-abnormal"
    return name, html, summary

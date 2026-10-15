"""方向 A（趋势择时持有）的 HTML 报告。"""

from __future__ import annotations

import datetime as dt
import html
import json

from .report import CSS, JS_EQUITY, JS_HELPERS

# 资金曲线只画 4 条：参照 + 三个最常见的"教科书默认参数"，避免按结果挑选
CHART = ["buy_hold", "sma200", "cross50_200", "mom252"]


def _p(x, sign=True):
    return "—" if x is None else (f"{x:+.1%}" if sign else f"{x:.1%}")


def build(out: dict, cfg: dict, generated: dt.datetime) -> str:
    bars, rules = out["bars"], out["rules"]
    lim = out["dd_limits"]
    split = out["split"]

    rows = []
    for key, r in rules.items():
        s, h = r["stats"], r["half"]
        budget = "".join(f"<td>{k:.0%}</td><td>{_p(st['cagr'])}</td>" for k, st in r["budget"])
        ref = " class='ref'" if key == "buy_hold" else ""
        rows.append(
            f"<tr{ref}><th scope='row'>{html.escape(r['label'])}<br><span class='muted'>{r['family']}</span></th>"
            f"<td>{_p(s['cagr'])}</td><td>{_p(s['max_dd'], False)}</td><td>{s['calmar']:.2f}</td>"
            f"<td>{s['trades_per_year']:.1f}</td><td>{s['exposure']:.0%}</td>"
            f"<td>{_p(h[0]['cagr'])} / {_p(h[0]['max_dd'], False)}</td><td>{_p(h[1]['cagr'])} / {_p(h[1]['max_dd'], False)}</td>"
            f"{budget}</tr>")

    periods = cfg.get("report", {}).get("periods", [])
    per_head = "".join(f"<th>{html.escape(p['name'])}</th>" for p in periods)
    per_rows = "".join(
        f"<tr><th scope='row'>{html.escape(r['label'])}</th>" + "".join(f"<td>{_p(v)}</td>" for v in r["period"]) + "</tr>"
        for r in rules.values())

    budget_head = "".join(f"<th>回撤≤{x:.0%} 仓位</th><th>年化</th>" for x in lim)
    data = {
        "dates": [b.date.isoformat() for b in bars],
        "series": [{"name": rules[k]["label"], "equity": [round(v) for v in rules[k]["result"].equity]} for k in CHART],
        "capital": cfg["account"]["capital"],
    }
    return TEMPLATE.format(
        css=CSS, js_helpers=JS_HELPERS, js_equity=JS_EQUITY,
        start=bars[0].date, end=bars[-1].date, n=len(bars), split=split,
        generated=generated.strftime("%Y-%m-%d %H:%M"),
        spread=cfg["broker"]["spread"], rows="".join(rows), budget_head=budget_head,
        per_head=per_head, per_rows=per_rows, data=json.dumps(data, ensure_ascii=False),
    )


TEMPLATE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>趋势择时回测</title>
<style>
{css}</style></head>
<body><main>
<h1>趋势择时持有：回测报告</h1>
<p class="muted">招商银行纸黄金 · {start} ~ {end}（{n} 个交易日，各规则都在指标就绪后同时开始）· 生成于 {generated}</p>

<div class="box"><b>方法</b><ul>
<li>每条规则每天收盘给出目标仓位（0 或 100%，波动率控仓规则介于两者之间），次日开盘按招行买入价/卖出价调仓</li>
<li>点差 {spread} 元/克按金价等比例缩放；空仓资金不计利息（实际放活期/货基还能多 1~1.5%/年）</li>
<li>"前半段 / 后半段"以 {split} 为界分别计算，用来看规则是否只在某一段有效</li>
<li>"回撤≤x% 仓位"：把规则的仓位乘以一个系数，使历史最大回撤不超过 x%，对应的年化收益按本金计算。<b>这是用历史回撤反推的，未来回撤可能更大</b></li>
</ul></div>

<h2>规则对比</h2>
<div class="scroll"><table class="data">
<thead><tr><th>规则</th><th>年化</th><th>最大回撤</th><th>收益/回撤</th><th>交易次数/年</th><th>平均仓位</th>
<th>前半段 年化/回撤</th><th>后半段 年化/回撤</th>{budget_head}</tr></thead>
<tbody>{rows}</tbody></table></div>
<p class="muted">收益/回撤 = 年化 ÷ 最大回撤，越高越好。</p>

<h2>资金曲线（满仓版本）</h2>
<p class="muted">只画一直持有和三条最常见的默认参数规则，避免按回测结果挑选。</p>
<div class="legend" id="eqLegend"></div>
<div class="chart" id="eq"><div class="tip"></div></div>

<h2>分阶段收益</h2>
<div class="scroll"><table class="data"><thead><tr><th>规则</th>{per_head}</tr></thead><tbody>{per_rows}</tbody></table></div>
</main>
<script>
const D = {data};
{js_helpers}{js_equity}</script>
</body></html>
"""

"""生成自包含的 HTML 回测报告（无外部依赖，支持深色模式）。"""

from __future__ import annotations

import datetime as dt
import html
import json

NAMES = {"pullback": "均线回踩", "breakout": "突破跟随", "rsi_rebound": "RSI 回调反弹", "buy_hold": "买入持有"}


def _pct(x: float, sign: bool = True) -> str:
    return f"{x:+.1%}" if sign else f"{x:.1%}"


def _num(x: float, d: int = 1, sign: bool = False) -> str:
    return f"{x:+,.{d}f}" if sign else f"{x:,.{d}f}"


def _pf(x: float) -> str:
    return "∞" if x == float("inf") else f"{x:.2f}"


def build(out: dict, cfg: dict, generated: dt.datetime) -> str:
    strategies = out["strategies"]
    bh = out["buy_hold"]
    bars = bh["result"].bars
    acct, dd, broker = cfg["account"], cfg["drawdown"], cfg["broker"]

    # ---- 汇总表 ----
    rows = []
    for name, d in strategies.items():
        s, rnd, g = d["stats"], d["random"], d["grid_summary"]
        rows.append(f"""<tr><th scope="row"><span class="sw s{list(strategies).index(name) + 1}"></span>{NAMES[name]}</th>
<td>{_pct(s['return'])}</td><td>{_pct(s['cagr'])}</td><td>{_pct(s['max_dd'], False)}</td>
<td>{s['trades']}（{s['trades_per_year']:.1f}/年）</td><td>{_pct(s['win_rate'], False)}</td>
<td>{_num(s['avg_pnl_g'], 1, True)}</td><td>{_pf(s['profit_factor'])}</td>
<td>{_pct(rnd['mean'])}</td><td>{rnd['beat']:.0%}</td><td>{g['profitable']:.0%}（{g['n']} 组）</td></tr>""")
    s = bh["stats"]
    rows.append(f"""<tr class="ref"><th scope="row">{NAMES['buy_hold']}（参照）</th>
<td>{_pct(s['return'])}</td><td>{_pct(s['cagr'])}</td><td>{_pct(s['max_dd'], False)}</td>
<td>—</td><td>—</td><td>{_num(bh['result'].trades[0].pnl_per_gram, 1, True)}</td><td>—</td><td>—</td><td>—</td><td>—</td></tr>""")

    # ---- 分年度 ----
    years = sorted(bh["yearly"])
    yr_rows = []
    for name, d in list(strategies.items()) + [("buy_hold", bh)]:
        cells = "".join(f"<td>{_pct(d['yearly'].get(y, 0.0))}</td>" for y in years)
        yr_rows.append(f"<tr><th scope='row'>{NAMES[name]}</th>{cells}</tr>")
    yr_head = "".join(f"<th scope='col'>{y}{'*' if y in (years[0], years[-1]) else ''}</th>" for y in years)

    # ---- 分阶段 ----
    periods = out.get("periods", [])
    per_head = "".join(f"<th scope='col'>{html.escape(p['name'])}</th>" for p in periods)
    per_rows = []
    for name, d in list(strategies.items()) + [("buy_hold", bh)]:
        cells = "".join(f"<td>{'—' if v is None else _pct(v)}</td>" for v in d.get("period", []))
        per_rows.append(f"<tr><th scope='row'>{NAMES[name]}</th>{cells}</tr>")
    period_block = "" if not periods else (
        "<h2>分阶段收益</h2><div class='scroll'><table class='data'><thead><tr><th>策略</th>"
        f"{per_head}</tr></thead><tbody>{''.join(per_rows)}</tbody></table></div>"
        "<p class='muted'>— 表示回测数据没有覆盖这一阶段。</p>")

    # ---- 每个策略的详情 ----
    sections = []
    for name, d in strategies.items():
        params = ", ".join(f"{k}={v}" for k, v in d["params"].items() if k != "description")
        trades = "".join(
            f"<tr><td>{t.entry_date}</td><td>{t.exit_date}</td><td>{t.hold_days}</td><td>{t.grams}</td>"
            f"<td>{t.entry_mid:.1f}</td><td>{t.exit_mid:.1f}</td>"
            f"<td class='{'pos' if t.pnl > 0 else 'neg'}'>{t.pnl_per_gram:+.1f}</td>"
            f"<td class='{'pos' if t.pnl > 0 else 'neg'}'>{t.pnl:+,.0f}</td>"
            f"<td>{html.escape(t.exit_reason)}</td><td class='muted'>{html.escape(t.reason)}</td></tr>"
            for t in d["result"].trades)
        gkeys = list(d["grid"][0]["params"])
        grid_rows = "".join(
            "<tr>" + "".join(f"<td>{g['params'][k]}</td>" for k in gkeys)
            + f"<td class='{'pos' if g['return'] > 0 else 'neg'}'>{_pct(g['return'])}</td>"
            f"<td>{_pct(g['max_dd'], False)}</td><td>{g['trades']}</td><td>{_pct(g['win_rate'], False)}</td></tr>"
            for g in sorted(d["grid"], key=lambda g: -g["return"]))
        r = d["random"]
        sections.append(f"""
<section class="strat" id="s-{name}">
  <h3>{NAMES[name]}</h3>
  <p class="muted">{html.escape(d['description'])}<br><code>{html.escape(params)}</code></p>
  <p>随机入场对照（同样的止损止盈、相近的交易次数，跑 200 次）：平均 {_pct(r['mean'])}，
     10%~90% 区间 {_pct(r['p10'])} ~ {_pct(r['p90'])}；本策略跑赢其中 <b>{r['beat']:.0%}</b>。</p>
  <details><summary>逐笔交易（{len(d['result'].trades)} 笔）</summary>
  <div class="scroll"><table class="data">
    <thead><tr><th>买入日</th><th>卖出日</th><th>天数</th><th>克数</th><th>买入中间价</th><th>卖出中间价</th>
    <th>每克净盈亏</th><th>盈亏(元)</th><th>离场原因</th><th>入场原因</th></tr></thead>
    <tbody>{trades}</tbody></table></div></details>
  <details><summary>参数稳健性（{len(d['grid'])} 组参数，按收益排序）</summary>
  <div class="scroll"><table class="data">
    <thead><tr>{''.join(f'<th>{k}</th>' for k in gkeys)}<th>总收益</th><th>最大回撤</th><th>交易数</th><th>胜率</th></tr></thead>
    <tbody>{grid_rows}</tbody></table></div></details>
</section>""")

    # ---- 图表数据 ----
    chart = {
        "dates": [b.date.isoformat() for b in bars],
        "close": [round(b.close, 2) for b in bars],
        "series": [{"key": n, "name": NAMES[n], "equity": [round(v) for v in d["result"].equity]}
                   for n, d in strategies.items()],
        "trades": {n: [{"in": t.entry_date.isoformat(), "out": t.exit_date.isoformat(),
                        "pi": round(t.entry_mid, 1), "po": round(t.exit_mid, 1),
                        "g": round(t.pnl_per_gram, 1), "y": round(t.pnl), "why": t.exit_reason}
                       for t in d["result"].trades] for n, d in strategies.items()},
        "capital": acct["capital"],
    }

    return TEMPLATE.format(
        css=CSS, js_helpers=JS_HELPERS, js_equity=JS_EQUITY,
        start=bars[0].date, end=bars[-1].date, n=len(bars),
        generated=generated.strftime("%Y-%m-%d %H:%M"),
        capital=f"{acct['capital']:,.0f}", risk=_pct(acct["risk_per_trade"], False),
        reduce=_pct(dd["reduce_at"], False), halt=_pct(dd["halt_at"], False), halt_days=dd["halt_days"],
        spread=broker["spread"], premium=broker["premium"], broker=html.escape(broker["name"]),
        scaling=(f"点差、最小止损、溢价按 当时金价 ÷ {broker['ref_price']:g} 等比例缩放（保持今天的百分比）"
                 if broker.get("scale_with_price") else "点差、最小止损为固定金额，不随金价缩放"),
        source=("由小时线合成的招行时段（" + html.escape(cfg["data"].get("session", "")) + "）日线"
                if cfg["data"].get("source") == "session" else "全天日线（包含招行休市时段）"),
        period_block=period_block,
        summary="".join(rows), yr_head=yr_head, yr_rows="".join(yr_rows),
        sections="".join(sections),
        tabs="".join(f'<button type="button" data-k="{n}"{" aria-pressed=true" if i == 0 else ""}>{NAMES[n]}</button>'
                     for i, n in enumerate(strategies)),
        data=json.dumps(chart, ensure_ascii=False),
    )

CSS = """:root { --surface:#fcfcfb; --raised:#f4f3f0; --t1:#0b0b0b; --t2:#52514e; --t3:#7a7974; --grid:#e8e7e3; --border:#e0dfda;
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100; --pos:#006300; --neg:#b42318; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --surface:#1a1a19; --raised:#232322; --t1:#f0efec; --t2:#c3c2b7;
  --t3:#8f8e86; --grid:#2c2c2a; --border:#383835; --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --pos:#4cc06a; --neg:#ff7a6e; } }
:root[data-theme="dark"] { --surface:#1a1a19; --raised:#232322; --t1:#f0efec; --t2:#c3c2b7; --t3:#8f8e86; --grid:#2c2c2a;
  --border:#383835; --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --pos:#4cc06a; --neg:#ff7a6e; }
* { box-sizing:border-box; }
body { margin:0; background:var(--surface); color:var(--t1); font:14px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",system-ui,sans-serif; }
main { max-width:1080px; margin:0 auto; padding:28px 16px 48px; }
h1 { font-size:22px; margin:0 0 4px; } h2 { font-size:17px; margin:32px 0 8px; } h3 { font-size:15px; margin:0 0 4px; }
.muted { color:var(--t3); } code { font-size:12px; color:var(--t2); word-break:break-all; }
.box { background:var(--raised); border-radius:10px; padding:12px 14px; color:var(--t2); }
.box li { margin:2px 0; }
.scroll { overflow-x:auto; }
table.data { border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; font-size:13px; }
table.data th, table.data td { border-bottom:1px solid var(--border); padding:6px 8px; text-align:right; white-space:nowrap; }
table.data th:first-child, table.data td:first-child { text-align:left; }
table.data thead th { color:var(--t2); font-weight:600; }
tr.ref { color:var(--t3); }
.pos { color:var(--pos); } .neg { color:var(--neg); }
.sw { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:6px; vertical-align:baseline; }
.s1 { background:var(--s1); } .s2 { background:var(--s2); } .s3 { background:var(--s3); } .s4 { background:var(--s4); }
.chart { position:relative; } svg { display:block; width:100%; height:auto; overflow:visible; }
svg text { font-size:11px; fill:var(--t3); }
.legend { display:flex; flex-wrap:wrap; gap:16px; color:var(--t2); font-size:13px; margin:4px 0 6px; }
.tip { position:absolute; pointer-events:none; background:var(--surface); border:1px solid var(--border); border-radius:8px;
  padding:8px 10px; font-size:12px; box-shadow:0 4px 14px rgba(0,0,0,.12); opacity:0; white-space:nowrap; z-index:2; }
.tip td { padding:0 8px 0 0; } .tip td:last-child { text-align:right; font-variant-numeric:tabular-nums; }
.tabs { display:flex; gap:6px; flex-wrap:wrap; margin:6px 0; }
.tabs button { border:1px solid var(--border); background:var(--surface); color:var(--t2); border-radius:999px; padding:4px 12px; font:inherit; cursor:pointer; }
.tabs button[aria-pressed=true] { background:var(--t1); color:var(--surface); border-color:var(--t1); }
section.strat { border-top:1px solid var(--border); padding-top:16px; margin-top:20px; }
details { margin:8px 0; } summary { cursor:pointer; color:var(--t2); }
"""

JS_HELPERS = """const NS = "http://www.w3.org/2000/svg";
const el = (t, a, p) => { const e = document.createElementNS(NS, t); for (const k in a) e.setAttribute(k, a[k]); p && p.appendChild(e); return e; };
const fmt = (v, d=0) => v.toLocaleString("zh-CN", {minimumFractionDigits:d, maximumFractionDigits:d});
const W = 1040, H = 320, M = {t:12, r:16, b:28, l:64};
const N = D.dates.length;
const X = i => M.l + (W - M.l - M.r) * i / (N - 1);
const idx = Object.fromEntries(D.dates.map((d, i) => [d, i]));

function axes(svg, lo, hi, step, f) {
  const Y = v => M.t + (hi - v) / (hi - lo) * (H - M.t - M.b);
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
    el("line", {x1:M.l, x2:W-M.r, y1:Y(v), y2:Y(v), stroke:"var(--grid)"}, svg);
    el("text", {x:M.l-8, y:Y(v)+4, "text-anchor":"end"}, svg).textContent = f(v);
  }
  let lastYear = "";
  D.dates.forEach((d, i) => { const y = d.slice(0, 4);
    if (y !== lastYear && i > 0) { el("text", {x:X(i), y:H-8, "text-anchor":"middle"}, svg).textContent = y; } lastYear = y; });
  return Y;
}
function niceStep(range) { const raw = range / 5, p = Math.pow(10, Math.floor(Math.log10(raw))); return [1,2,2.5,5,10].map(m => m*p).find(s => s >= raw); }
function tipAt(box, tip, e, html) {
  tip.innerHTML = html; tip.style.opacity = 1;
  const r = box.getBoundingClientRect(); let x = e.clientX - r.left + 14;
  if (x + tip.offsetWidth > r.width) x = e.clientX - r.left - tip.offsetWidth - 14;
  tip.style.left = x + "px"; tip.style.top = Math.max(0, e.clientY - r.top - 40) + "px";
}

"""


# 资金曲线（多条，带十字线提示）：需要 D.dates、D.series[{name, equity}]、D.capital，以及 #eq / #eqLegend
JS_EQUITY = """// ---- 资金曲线 ----
(function () {
  const box = document.getElementById("eq"), tip = box.querySelector(".tip");
  const all = D.series.flatMap(s => s.equity);
  let lo = Math.min(...all), hi = Math.max(...all); const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
  const svg = el("svg", {viewBox:`0 0 ${W} ${H}`, role:"img", "aria-label":"各策略资金曲线"}); box.prepend(svg);
  const Y = axes(svg, lo, hi, niceStep(hi - lo), v => fmt(v));
  el("line", {x1:M.l, x2:W-M.r, y1:Y(D.capital), y2:Y(D.capital), stroke:"var(--t3)", "stroke-dasharray":"3 3"}, svg);
  const leg = document.getElementById("eqLegend");
  D.series.forEach((s, k) => {
    el("path", {d: s.equity.map((v, i) => (i ? "L" : "M") + X(i).toFixed(1) + "," + Y(v).toFixed(1)).join(""),
      fill:"none", stroke:`var(--s${k+1})`, "stroke-width":2, "stroke-linejoin":"round"}, svg);
    leg.insertAdjacentHTML("beforeend", `<span><i class="sw s${k+1}"></i>${s.name}</span>`);
  });
  leg.insertAdjacentHTML("beforeend", `<span class="muted">- - 初始本金</span>`);
  const cross = el("line", {y1:M.t, y2:H-M.b, stroke:"var(--t3)", opacity:0}, svg);
  const dots = D.series.map((s, k) => el("circle", {r:4, fill:`var(--s${k+1})`, stroke:"var(--surface)", "stroke-width":2, opacity:0}, svg));
  const hit = el("rect", {x:M.l, y:M.t, width:W-M.l-M.r, height:H-M.t-M.b, fill:"transparent"}, svg);
  hit.addEventListener("mousemove", e => {
    const r = svg.getBoundingClientRect(), px = (e.clientX - r.left) / r.width * W;
    const i = Math.max(0, Math.min(N - 1, Math.round((px - M.l) / (W - M.l - M.r) * (N - 1))));
    cross.setAttribute("x1", X(i)); cross.setAttribute("x2", X(i)); cross.setAttribute("opacity", 1);
    D.series.forEach((s, k) => { dots[k].setAttribute("cx", X(i)); dots[k].setAttribute("cy", Y(s.equity[i])); dots[k].setAttribute("opacity", 1); });
    tipAt(box, tip, e, `<b>${D.dates[i]}</b><table>` + D.series.map((s, k) =>
      `<tr><td><i class="sw s${k+1}"></i>${s.name}</td><td>${fmt(s.equity[i])}</td></tr>`).join("") + `</table>`);
  });
  hit.addEventListener("mouseleave", () => { tip.style.opacity = 0; cross.setAttribute("opacity", 0); dots.forEach(d => d.setAttribute("opacity", 0)); });
})();

"""

TEMPLATE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>纸黄金回测报告</title>
<style>
{css}</style></head>
<body><main>
<h1>纸黄金短线策略回测报告</h1>
<p class="muted">{broker} · 数据 {start} ~ {end}（{n} 个交易日）· 生成于 {generated}</p>

<div class="box"><b>回测假设</b><ul>
<li>本金 {capital} 元；每笔最多亏总资金 {risk}（含点差），按此计算买入克数（1 克为单位）</li>
<li>回撤达 {reduce} 每笔风险减半；达 {halt} 暂停开仓 {halt_days} 个交易日</li>
<li>点差 {spread} 元/克（买卖各承担一半）；招行相对国际换算价溢价 {premium} 元/克；{scaling}</li>
<li>价格 = Twelve Data XAU/USD × USD/CNY ÷ 31.1035，使用{source}；收盘出信号、次日开盘成交；跳空按开盘价止损；同日碰到止损止盈按止损算</li>
<li>只做多</li>
</ul></div>

<h2>策略对比</h2>
<div class="scroll"><table class="data">
<thead><tr><th>策略</th><th>总收益</th><th>年化</th><th>最大回撤</th><th>交易次数</th><th>胜率</th>
<th>平均每克净盈亏</th><th>盈亏比</th><th>随机入场平均</th><th>跑赢随机</th><th>参数组合盈利比例</th></tr></thead>
<tbody>{summary}</tbody></table></div>
<p class="muted">盈亏比 = 总盈利 ÷ 总亏损。"跑赢随机"越接近 100% 说明入场信号越有价值；"参数组合盈利比例"越高说明结果不依赖某一组凑巧的参数。</p>

<h2>资金曲线</h2>
<div class="legend" id="eqLegend"></div>
<div class="chart" id="eq"><div class="tip"></div></div>

<h2>分年度收益</h2>
<div class="scroll"><table class="data"><thead><tr><th>策略</th>{yr_head}</tr></thead><tbody>{yr_rows}</tbody></table></div>
<p class="muted">* 首尾年份不完整。</p>
{period_block}

<h2>价格与交易点</h2>
<div class="tabs" id="tabs">{tabs}</div>
<div class="legend"><span>— 招行中间价（元/克）</span><span>▲ 买入</span><span>● 盈利卖出</span><span>○ 亏损卖出</span></div>
<div class="chart" id="px"><div class="tip"></div></div>

<h2>策略详情</h2>
{sections}
</main>
<script>
const D = {data};
{js_helpers}{js_equity}// ---- 价格与交易点 ----
(function () {{
  const box = document.getElementById("px"), tip = box.querySelector(".tip");
  let lo = Math.min(...D.close), hi = Math.max(...D.close); const pad = (hi - lo) * 0.05; lo -= pad; hi += pad;
  const svg = el("svg", {{viewBox:`0 0 ${{W}} ${{H}}`, role:"img", "aria-label":"价格走势与交易点"}}); box.prepend(svg);
  const Y = axes(svg, lo, hi, niceStep(hi - lo), v => fmt(v));
  el("path", {{d: D.close.map((v, i) => (i ? "L" : "M") + X(i).toFixed(1) + "," + Y(v).toFixed(1)).join(""),
    fill:"none", stroke:"var(--t3)", "stroke-width":1.5}}, svg);
  const layer = el("g", {{}}, svg);
  function draw(key) {{
    layer.replaceChildren();
    const k = D.series.findIndex(s => s.key === key) + 1, col = `var(--s${{k}})`;
    D.trades[key].forEach(t => {{
      const a = idx[t.in], b = idx[t.out], win = t.g > 0;
      el("line", {{x1:X(a), y1:Y(t.pi), x2:X(b), y2:Y(t.po), stroke:col, "stroke-width":2}}, layer);
      const x = X(a), y = Y(t.pi) + 12;
      el("path", {{d:`M${{x}},${{y-7}} L${{x-5}},${{y+2}} L${{x+5}},${{y+2}} Z`, fill:col}}, layer);
      el("circle", {{cx:X(b), cy:Y(t.po), r:4.5, fill: win ? col : "var(--surface)", stroke:col, "stroke-width":2}}, layer);
      const hit = el("rect", {{x:Math.min(X(a), X(b)) - 8, y:Math.min(Y(t.pi), Y(t.po)) - 16, width:Math.abs(X(b) - X(a)) + 16,
        height:Math.abs(Y(t.po) - Y(t.pi)) + 32, fill:"transparent"}}, layer);
      hit.addEventListener("mousemove", e => tipAt(box, tip, e, `<b>${{t.in}} → ${{t.out}}</b><table>
        <tr><td>买入中间价</td><td>${{fmt(t.pi, 1)}}</td></tr><tr><td>卖出中间价</td><td>${{fmt(t.po, 1)}}</td></tr>
        <tr><td>每克净盈亏</td><td>${{t.g > 0 ? "+" : ""}}${{fmt(t.g, 1)}}</td></tr><tr><td>盈亏</td><td>${{t.y > 0 ? "+" : ""}}${{fmt(t.y)}} 元</td></tr>
        <tr><td>离场</td><td>${{t.why}}</td></tr></table>`));
      hit.addEventListener("mouseleave", () => tip.style.opacity = 0);
    }});
  }}
  const tabs = document.getElementById("tabs");
  tabs.addEventListener("click", e => {{
    const b = e.target.closest("button"); if (!b) return;
    tabs.querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", x === b));
    draw(b.dataset.k);
  }});
  draw(D.series[0].key);
}})();
</script>
</body></html>
"""

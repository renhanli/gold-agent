# 纸黄金短线交易助手（gold_agent）

招商银行纸黄金的短线交易辅助工具。它负责算信号、提醒和复盘，**不会替你下单**：下单由你在招行 App 里手动完成。

## 当前进度：第 1 阶段（回测）

只用 Python 3.11+ 标准库，不需要安装依赖。

```bash
python -m gold_agent backtest      # 回测全部策略，生成 reports/backtest.html
python -m gold_agent trend         # 方向 A：趋势择时持有（均线/交叉/通道/动量/波动率控仓），生成 reports/trend.html
python -m gold_agent signal        # 用最新数据看今天各策略有没有买入信号
python -m gold_agent update-data   # 下载 2010 年起日线 + 2020 年起小时线（需要 TWELVE_DATA_API_KEY，约 15 次请求）
python -m gold_agent backtest --source session   # 用招行交易时段（9:30-24:00）合成的日线回测
python -m unittest discover -s tests
```

所有参数都在 `config.toml`：本金、每笔风险、回撤风控、点差、招行溢价，以及各策略的参数。

## 目录结构

| 路径 | 作用 |
|---|---|
| `config.toml` | 账户、风控、招行参数、策略参数 |
| `data/` | 金价日线、招行时段日线（由小时线合成）、美元兑人民币，来自 Twelve Data |
| `gold_agent/data.py` | 读取数据，换算成招行中间价（人民币/克） |
| `gold_agent/indicators.py` | 均线、RSI、ATR 等指标 |
| `gold_agent/strategy.py` | 买入规则：均线回踩、突破跟随、RSI 回调反弹，以及随机入场对照组 |
| `gold_agent/backtest.py` | 回测引擎：点差、跳空止损、按风险计算克数、回撤后减仓和暂停 |
| `gold_agent/research.py` | 多策略对比、随机入场对照、参数稳健性扫描 |
| `gold_agent/allocation.py` | 趋势择时持有：按目标仓位调仓、规则清单、前后半段稳定性、按回撤上限缩放仓位 |
| `gold_agent/report.py` / `trend_report.py` | 生成 HTML 报告 |

## 回测假设

- 价格：XAU/USD × USD/CNY ÷ 31.1035，再加上招行溢价（2026-10-14 实测为 2.2 元/克）
- 点差 5 元/克：买入价 = 中间价 + 2.5，卖出价 = 中间价 − 2.5。回测多年数据时，点差、最小止损和溢价按"当时金价 ÷ 894"等比例缩放（`broker.scale_with_price`）
- 当天收盘出信号，第二天开盘成交；开盘就跳空跌破止损时，按开盘价止损
- 同一天既碰到止损又碰到止盈时，按止损算（偏保守）
- 每笔最多亏总资金的 1%；回撤达 3% 时每笔风险减半；回撤达 5% 时暂停开仓 20 个交易日
- 全天日线的最高价和最低价包含招行休市时段（0:00–9:30）的行情；用 `--source session` 可以改用小时线合成的招行时段日线（2020 年起）
- 报告按市场阶段拆分收益（2013-2015 熊市、2016-2019 震荡等），阶段划分在 `config.toml` 的 `[[report.periods]]`

## 路线图

1. **回测**（当前）：验证扣除点差后策略是否有优势
2. **模拟盘**：每天定时检查信号，通过 PushPlus 或 Server 酱推送到微信，同时记录虚拟持仓
3. **实盘辅助**：企业微信双向消息（回报成交、跟踪止盈止损）、宏观过滤、事件日历、LLM 每日简报；部署到 GCP Cloud Run

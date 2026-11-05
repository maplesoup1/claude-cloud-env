# quant-daytrader

美股日内短线量化框架：事件驱动，回测和实盘共用同一个引擎，券商用 Alpaca（默认模拟盘）。

> ⚠️ 仅供学习研究，不构成投资建议。默认连接 **paper trading**。至少跑几周模拟盘、确认回测和模拟盘的成交大致对得上之后，再考虑小资金实盘。

## 架构

```
Alpaca WebSocket 1分钟K线 ─┐
历史1分钟数据(回测) ───────┴─► Engine.on_minute_bar
                                  ├─ broker.on_clock / 收盘前强平 / 单日亏损熔断
                                  ├─ broker.on_minute_bar      (回测时在这里模拟成交)
                                  └─ BarAggregator 1m→5m ─► Strategy.on_bar ─► Signal
                                                                   └─► RiskManager.evaluate ─► broker.submit_bracket
```

| 模块 | 作用 |
|---|---|
| `daytrader/engine.py` | 核心事件循环，回测和实盘共用；JSONL 交易日志 |
| `daytrader/strategy/orb.py` | 开盘区间突破（ORB）策略 |
| `daytrader/risk.py` | 按风险计算仓位、最大持仓数、单日亏损熔断、收盘前强平 |
| `daytrader/broker/sim.py` | 回测撮合：下一根K线开盘价成交 + 滑点，同一根K线内止损优先，跳空按开盘价成交 |
| `daytrader/broker/alpaca.py` | Alpaca 括号单（止损和止盈挂在券商端，程序崩溃也有效） |
| `daytrader/live.py` | 实盘/模拟盘：交易日历、半天交易日、预热、重启后对账、看门狗、断流报警 |
| `daytrader/data.py` | Alpaca 历史分钟数据（parquet 缓存）+ 合成数据（只用于测试） |

## 安装

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 填入 Alpaca Paper 账户的 API key
```

去 https://app.alpaca.markets 注册账号，切换到 Paper 账户，生成 API Keys。

## 使用

```bash
python -m pytest                                    # 跑测试
python -m daytrader backtest --source synthetic     # 不需要 key，只测通流程
python -m daytrader backtest --start 2024-01-01 --end 2025-12-31 --slippage-bps 2 4 8   # 真实数据 + 滑点压力测试
python -m daytrader status                          # 账户、持仓、挂单
python -m daytrader paper                           # 跑今天的模拟盘（开盘前启动，收盘后自动退出）
python -m daytrader kill                            # 紧急：撤销所有挂单并平掉所有仓位
```

### 每天自动跑模拟盘（Linux/macOS 的 cron，服务器时区按美东设置）

```cron
CRON_TZ=America/New_York
20 9 * * 1-5  cd /path/to/quant-daytrader && .venv/bin/python -m daytrader paper >> logs/cron.log 2>&1
```

节假日程序会自动退出；半天交易日会把强平时间提前到收盘前 15 分钟。建议放在一台常开的机器或 VPS 上跑。

## 安全设计

- **防重复下单**：`client_order_id` 由「策略-标的-日期-时间-方向」确定性生成，同一个信号重复提交会被券商拒绝；重启时会读取当天已有的订单，已经交易过的标的当天不再开仓。
- **券商端止损**：用括号单，止损和止盈在 Alpaca 服务器上执行，不依赖本程序一直在线。
- **三道平仓保险**：15:45 看门狗定时强平（不依赖行情推送）、单日亏损超过 2% 时强平并停止当天交易、`kill` 命令手动一键清仓。
- **默认模拟盘**：只有把 `config.yaml` 的 `live.paper` 改成 `false` 才会接真钱。

## 防未来函数

- 信号只在 5 分钟 K 线收盘后产生，在下一根 1 分钟 K 线的开盘价成交。
- `tests/test_core.py::test_no_edge_on_random_walk`：在没有趋势的随机游走数据上，策略的期望收益必须接近 0（t 统计量 < 2.5）。如果这个测试失败，说明引擎在偷看未来数据。

## 已知局限 / 下一步

- 免费的 IEX 行情只覆盖约 2–3% 的成交量，K 线和全市场（SIP）数据有差异，成交量过滤也会偏小。正式研究建议用 SIP 数据（付费）。
- 回测没有模拟部分成交和排队；目前只适合流动性很好的标的。
- PDT 规则：保证金账户低于 $25k 时日内交易次数受限（规则正在修改中，以券商实际执行为准）。模拟盘不受此限制。
- 可以加的东西：更多策略（VWAP 回归、跳空）、walk-forward 参数优化、模拟盘和回测的成交对比报告。

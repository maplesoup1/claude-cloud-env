# quant-daytrader

美股日内短线量化框架：事件驱动，回测和实盘共用同一个引擎，券商用 Alpaca（默认模拟盘），支持**一个进程同时跑多个策略**。

> ⚠️ 仅供学习研究，不构成投资建议。默认连接 **paper trading**。至少跑几周模拟盘，确认回测和模拟盘的成交大致对得上之后，再考虑小资金实盘。

## 架构

```
Alpaca WebSocket（一条连接）──► 按标的分发 ──► Engine[orb]  ─► AlpacaBroker(模拟盘账户 A)
历史1分钟数据（回测）                      ├─► Engine[vwap] ─► AlpacaBroker(模拟盘账户 B)
                                           └─► Engine[momo] ─► AlpacaBroker(模拟盘账户 C)

Engine.on_minute_bar：收盘前强平 / 单日亏损熔断 → 模拟撮合（仅回测）→ 1m→N分钟K线
                       → Strategy.on_bar(bar, ctx) → Signal（括号单）/ Exit（市价平仓）→ RiskManager → Broker
```

| 模块 | 作用 |
|---|---|
| `daytrader/engine.py` | 核心事件循环，回测和实盘共用；每个策略实例一份 JSONL 交易日志 |
| `daytrader/strategy/` | 策略。新增策略只需加一个文件，用 `@register` 注册后自动发现 |
| `daytrader/indicators.py` | VWAP（含标准差带）、跳空、前收盘、ATR、RSI、EMA，全部只用已完成的 K 线计算 |
| `daytrader/risk.py` | 按风险计算仓位，限制单个持仓和总持仓规模，检查最大持仓数、止损和止盈方向、止损过近，拒绝过期信号，单日亏损熔断，收盘前强平 |
| `daytrader/sessions.py` | 交易日历（节假日、半天交易日） |
| `daytrader/broker/sim.py` | 回测撮合：在下一根K线开盘价成交并计滑点；同一根K线内止损和止盈都触发时按止损算；跳空越过止损按开盘价成交 |
| `daytrader/broker/alpaca.py` | Alpaca 括号单，止损和止盈挂在券商端；所有操作只针对本策略自己的标的 |
| `daytrader/live.py` | 多策略实盘：校验配置冲突、交易日历和半天交易日、预热、重启对账、成交回报写入日志、看门狗 |

## 安装

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 策略一览

| 配置 | 策略 | 交易时段 | 思路 | 标的 |
|---|---|---|---|---|
| `configs/orb.yaml` | `orb` 开盘区间突破 | 9:45–11:30 | 动量：放量突破开盘 15 分钟区间，并且站在 VWAP 正确一侧 | 8 只大盘股和 ETF |
| `configs/vwap.yaml` | `vwap_reversion` VWAP 均值回归 | 10:00–15:00 | 反转：价格偏离 VWAP 2σ、RSI 极端、出现反转K线，并过滤趋势日和大盘大跌（大涨） | 8 只低波动大盘股和 ETF |
| `configs/momo.yaml` | `intraday_momentum` 尾盘动量 | 15:30–15:58 | 学术研究中的“日内动量”：前一日收盘到 15:30 的涨跌方向延续到收盘 | SPY、QQQ |
| `configs/gap.yaml` | `gap_fade` 跳空回补（备选） | 9:45–11:30 | 1–4% 的跳空先失败（跌回开盘区间和 VWAP 另一侧），再做回补 | 14 只大盘个股 |

**推荐同时跑 ORB + VWAP + 尾盘动量**：三者分别是早盘动量、午盘反转和尾盘动量，交易时段和逻辑都不同，相关性低。`gap_fade` 和 ORB 在跳空日经常对同一只股票同时发出同方向信号（独立审查测得约 15% 重叠），所以作为备选，或者换成与 ORB 不重叠的标的再用。

```bash
python -m daytrader -c configs/orb.yaml -c configs/vwap.yaml -c configs/momo.yaml backtest --start 2024-01-01 --end 2025-12-31 --slippage-bps 2 4 8
python -m daytrader -c configs/orb.yaml -c configs/vwap.yaml -c configs/momo.yaml paper
```

> 合成数据只能用来验证代码流程是否跑通，不能说明策略是否赚钱：合成数据里人为加了趋势日，会偏向突破类策略、惩罚回归类策略。是否有优势只能看真实数据回测和模拟盘结果。

## 同时跑多个策略

**推荐每个策略用一个独立的 Alpaca 模拟盘账户**（在 Alpaca 后台新建模拟盘账户，分别生成 key）。这样资金、持仓和单日亏损熔断互不影响，也能单独统计每个策略的绩效。在每个策略的配置文件里用 `account_env` 指定读取哪组 key：

```yaml
account_env: ALPACA_ORB    # 读取 .env 中的 ALPACA_ORB_API_KEY / ALPACA_ORB_SECRET_KEY
```

几个策略共用一个账户也可以，但前提是它们**不能交易相同的标的**，否则启动时会直接报错退出。共用账户时，资金和单日亏损熔断是整个账户共享的。

## 使用

```bash
python -m pytest                                              # 测试（含通用防未来函数测试）
python -m daytrader list                                      # 列出所有策略及参数
python -m daytrader -c configs/orb.yaml backtest --source synthetic          # 不需要 key，只测通流程
python -m daytrader -c configs/orb.yaml backtest --start 2024-01-01 --end 2025-12-31 --slippage-bps 2 4 8
python -m daytrader -c configs/a.yaml -c configs/b.yaml backtest              # 多策略回测，输出组合表现和相关性
python -m daytrader -c configs/a.yaml -c configs/b.yaml paper                 # 多策略模拟盘
python -m daytrader -c ... status                             # 查看各账户、持仓、挂单
python -m daytrader -c ... flatten                            # 只平掉各策略自己的标的（cron 安全网用）
python -m daytrader -c ... kill                               # 紧急：撤销各账户所有挂单并平掉所有仓位
```

## 防隔夜持仓（多重保险）

1. 引擎每根 K 线和看门狗每 15 秒都会检查：过了强平时间还有持仓或挂单，就**反复重试**平仓，直到全部平掉；单个标的平仓失败不会影响其他标的。
2. 进程在开盘期间退出（崩溃、Ctrl-C、`kill`/SIGTERM、行情连接出错）时，会先平掉所有仓位。
   - 每个策略各有自己的处理线程和看门狗，一个策略的 API 调用卡住不会耽误其他策略平仓。
   - 所有 HTTP 请求都有 10 秒超时。
   - 已经发出的平仓单在 20 秒内不会重复提交；平仓失败的重试和通知都做了限频。
3. 括号单的止损和止盈腿是**当日有效**的，收盘后就失效。所以要再用 cron 加一道和主进程**相互独立**的安全网：

```cron
CRON_TZ=America/New_York
20 9 * * 1-5   cd /path/to/quant-daytrader && .venv/bin/python -m daytrader -c configs/orb.yaml -c configs/vwap.yaml -c configs/momo.yaml paper >> logs/cron.log 2>&1
59 12,15 * * 1-5  cd /path/to/quant-daytrader && .venv/bin/python -m daytrader -c configs/orb.yaml -c configs/vwap.yaml -c configs/momo.yaml flatten --if-close-within 2 >> logs/cron.log 2>&1
```

`--if-close-within 2` 表示只在距离收盘不到 2 分钟时才平仓。这样同一条 cron 在半天交易日的 12:59 和平常日的 15:59 都会生效，其他时间什么都不做。

4. 回测中，到日终仍未平掉的仓位会按最后价格强制平仓（记为 `session_end`），绝不带到第二天。

## 交易日历

实盘和回测都使用 Alpaca 的交易日历：节假日不交易；半天交易日（13:00 收盘）把强平时间提前到收盘前 15 分钟，并忽略收盘后的 K 线。

回测默认用 SIP 历史数据：Alpaca 免费套餐可以拿到 15 分钟以前的 SIP 数据。实盘默认用免费的 IEX 实时数据。

## 防未来函数

`tests/test_lookahead.py` 会对 `configs/` 下**每一个**配置自动运行两项检查：

1. **截断一致性**：在多个时间点把之后的数据全部删掉重新回测，截断点之前的所有信号和成交必须和完整回测完全一致。
2. **随机游走无优势**：在没有趋势的随机数据上，平均 R 的 t 统计量必须小于 2.5。

## 已知局限

- 免费的 IEX 实时数据只覆盖约 2–3% 的成交量，成交量过滤在实盘时会偏小。
- 回测没有模拟部分成交和排队，只适合流动性很好的标的。
- PDT 规则：保证金账户低于 $25k 时日内交易次数受限（规则正在修改中，以券商实际执行为准）。模拟盘建议每个账户资金设在 $30k 以上。

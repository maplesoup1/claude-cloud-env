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
2. 进程在开盘期间退出（崩溃、Ctrl-C、行情连接出错）时，会先平掉所有仓位。
3. 括号单的止损和止盈腿是**当日有效**的，收盘后就失效。所以要再用 cron 加一道和主进程**相互独立**的安全网：

```cron
CRON_TZ=America/New_York
20 9 * * 1-5   cd /path/to/quant-daytrader && .venv/bin/python -m daytrader -c configs/orb.yaml -c configs/vwap.yaml -c configs/momo.yaml paper >> logs/cron.log 2>&1
59 15 * * 1-5  cd /path/to/quant-daytrader && .venv/bin/python -m daytrader -c configs/orb.yaml -c configs/vwap.yaml -c configs/momo.yaml flatten >> logs/cron.log 2>&1
```

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

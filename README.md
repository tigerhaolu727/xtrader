# xtrader

Quantitative research toolkit focused on Bitget market/account data ingestion and local analytics.

## Bitget exchange client

核心能力：

- `xtrader.exchanges.bitget.BitgetClient` 实现账户余额、合约持仓、历史 K 线获取。
- 使用 `docs/03-delivery/specs/XTR-001.md` 定义的抽象与 `xtrader.common.models` 数据结构，方便后续扩展其他交易所。

快速示例：

```bash
export BITGET_API_KEY=xxx
export BITGET_API_SECRET=xxx
export BITGET_PASSPHRASE=xxx
python examples/bitget_client_demo.py
```

你也可以直接编辑项目根目录的 `.env` 文件（已提供空白模板），再运行 `python -m dotenv.main set ...` 或依赖 `python-dotenv` 自动加载。若需通过本地代理访问 Bitget，可额外填写：

```
BITGET_HTTP_PROXY=http://127.0.0.1:9090
BITGET_HTTPS_PROXY=http://127.0.0.1:9090
```

这些值会在集成测试和 demo 中自动注入 `httpx`。

要验证真实 API 通讯，可在配置好凭证后运行：

```bash
PYTHONPATH=src pytest tests/integration/test_bitget_client_live.py
```
若未设置凭证，该测试会自动跳过。

## Offline Report Viewer

离线查看器使用本地文件目录，不依赖本地服务：

```bash
python scripts/offline_report_viewer.py init
```

初始化后打开：

- `reports/backtests/viewer/offline_report_viewer.html`

在页面中选择单个 Run 目录（包含 `run_manifest.json`）即可加载报告数据。

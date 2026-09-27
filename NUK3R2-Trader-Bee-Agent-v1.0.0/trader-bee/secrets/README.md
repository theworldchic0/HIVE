# secrets/ — never committed, never pasted into chat

- `agent_wallet.key` — the Trader Bee's OWN private key. Created by `python trader.py wallet-new`
  (the key is generated on this machine and written here; only the public address is ever printed).
- `ARMED` — written by `python trader.py arm` (a human act). Delete it (or run `disarm`) to stop
  live trading instantly.

API keys are read from `<Hive root>/.env` or the terminal's `module/.env` (ONEINCH_API_KEY,
COINGECKO_API_KEY). Nothing in this folder is ever printed, logged or sent anywhere.

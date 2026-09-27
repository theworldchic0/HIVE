# Implementation

Connect to the Hive event bus using events such as:
- research.watchlist.created
- research.watchlist.updated
- fib.structure.created
- fib.reaction.detected
- fib.data_error
- fib.learning.proposal

Use the Hive secret/config layer for API keys. Never hard-code credentials.

The Fib Agent should not receive trading-wallet permissions.

Store raw observations before producing comparisons. Do not optimize against a single token or tiny sample.

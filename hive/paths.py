"""Where the Hive lives on disk. Override the data dir with HIVE_DATA (tests use a temp dir)."""
import os
from pathlib import Path

HIVE_ROOT = Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    p = Path(os.environ.get("HIVE_DATA") or (HIVE_ROOT / "hive_data"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def sub(*parts: str) -> Path:
    p = data_dir().joinpath(*parts)
    p.mkdir(parents=True, exist_ok=True)
    return p


QUEEN_DIR = HIVE_ROOT / "NUK3R2-Queen-Bee-Agent-v1.2.0" / "queen-bee"
BLUEPRINT_DIR = HIVE_ROOT / "NUK3R2-Bottom-Blueprint-Agent-v1.2.0-Hive-Update" / "bottom-blueprint-agent"
MARKET_DIRECTION_DIR = HIVE_ROOT / "NUK3R2-Market-Direction-Agent-v1.1.0-Hive-Update" / "market-direction-agent"
FIB_DIR = HIVE_ROOT / "NUK3R2_Fib_Agent_v0.1.0" / "NUK3R2_Fib_Agent_v0.1.0"
TRADER_DIR = HIVE_ROOT / "NUK3R2-Trader-Bee-Agent-v1.0.0" / "trader-bee"
MODULE_DIR = HIVE_ROOT / "module"

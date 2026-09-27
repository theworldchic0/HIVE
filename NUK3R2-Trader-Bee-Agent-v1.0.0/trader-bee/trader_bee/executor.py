"""Bridge to the Node executor (executor/exec.mjs). JSON in on stdin, one JSON object out on stdout.

The Node side is adapted from the trading terminal's engine (route-scan.mjs quote race,
arm.mjs limit orders, wallets.mjs key handling). Python never touches a private key.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from hive.paths import sub

from .config import KEY_FILE, ROOT

EXEC = ROOT / "executor" / "exec.mjs"


class ExecutorError(RuntimeError):
    pass


# Tests swap this for a fake: runner(cmd, payload, timeout) -> dict
runner = None


def call(cmd: str, payload: dict | None = None, timeout: float = 240) -> dict:
    if runner is not None:
        return runner(cmd, payload or {}, timeout)
    node = shutil.which("node")
    if not node:
        raise ExecutorError("Node.js is not installed (needed for quotes and on-chain execution)")
    if not (ROOT / "executor" / "node_modules").exists():
        raise ExecutorError("executor dependencies missing: run `npm install` inside trader-bee/executor")
    env = {**os.environ, "TRADER_BEE_KEY_FILE": str(KEY_FILE), "TRADER_BEE_JOURNAL": str(sub("trader_bee") / "exec-journal.jsonl")}
    try:
        p = subprocess.run([node, str(EXEC), cmd], input=json.dumps(payload or {}), capture_output=True, text=True,
                           timeout=timeout, env=env, cwd=str(ROOT / "executor"))
    except subprocess.TimeoutExpired as e:
        raise ExecutorError(f"executor '{cmd}' timed out after {timeout}s") from e
    lines = [ln for ln in p.stdout.strip().splitlines() if ln.strip().startswith("{")]
    if not lines:
        raise ExecutorError(f"executor '{cmd}' returned no JSON (exit {p.returncode}): {p.stderr.strip()[-400:]}")
    out = json.loads(lines[-1])
    if not out.get("ok") and out.get("fatal"):
        raise ExecutorError(out.get("error") or "executor error")
    return out

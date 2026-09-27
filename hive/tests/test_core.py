import json
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "NUK3R2-Trader-Bee-Agent-v1.0.0" / "trader-bee"))

EXAMPLE = Path(__file__).resolve().parents[1] / "contracts" / "examples" / "research.verdict.example.json"


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HIVE_DATA", str(tmp_path / "hive"))
    monkeypatch.setenv("QUEEN_DATA", str(tmp_path / "queen"))


def test_example_verdict_is_valid():
    from hive import contracts
    for v in json.loads(EXAMPLE.read_text()):
        assert contracts.errors_for("research.verdict", v) == []


def test_contract_rejects_bad_asset_id_and_ticker_identity():
    from hive import contracts
    v = json.loads(EXAMPLE.read_text())[0]
    bad = {**v, "asset_id": "base:" + "0x" + "0" * 40}
    assert any("asset_id must equal" in e for e in contracts.errors_for("research.verdict", bad))
    assert contracts.errors_for("research.verdict", {**v, "contract": "BRETT"})  # a ticker is never an identity
    assert contracts.errors_for("made.up", {}) != []


def test_bus_cursor_at_least_once_and_torn_line():
    from hive import bus
    v = json.loads(EXAMPLE.read_text())[0]
    bus.publish("research.verdict", "research_agent", v)
    with open(bus.events_file(), "a") as f:
        f.write('{"partial": ')  # a writer mid-append
    got = bus.consume("c1")
    assert len(got) == 1
    assert bus.consume("c1")  # not acked -> delivered again
    bus.ack("c1", got[0][0])
    assert bus.consume("c1") == []
    assert bus.consume("c2") and bus.cursor("c2") == 0  # consumers are independent


def test_net_cache_retry_and_failure(monkeypatch):
    from hive import net
    calls = []

    def t(url, h, b, to):
        calls.append(url)
        return (503, b"x") if len(calls) == 1 else (200, b'{"a": 1}')
    monkeypatch.setattr(net, "transport", t)
    monkeypatch.setattr(net.time, "sleep", lambda s: None)
    net._cache.clear()
    assert net.fetch_json("https://x.test/a", ttl_s=60) == {"a": 1}
    assert net.fetch_json("https://x.test/a", ttl_s=60) == {"a": 1}
    assert len(calls) == 2  # one retry, then served from cache
    monkeypatch.setattr(net, "transport", lambda *a: (404, b"nope"))
    with pytest.raises(net.NetError):
        net.fetch_json("https://x.test/b")


def test_poison_guard():
    from hive import marketdata
    rows = [{"p": 1.0}, {"p": 1.1}, {"p": 0.95}, {"p": 50.0}]
    assert [r["p"] for r in marketdata.guard(rows, "p")] == [1.0, 1.1, 0.95]


def test_secrets_ignore_placeholders(monkeypatch):
    from hive import secrets
    monkeypatch.setenv("ONEINCH_API_KEY", "PASTE_YOUR_1INCH_API_KEY_HERE")
    assert secrets.get("ONEINCH_API_KEY") is None


def _serve():
    from http.server import ThreadingHTTPServer
    from hive.ui.server import Handler
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def _req(port, path, body=None, headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None,
                                 headers=headers or {}, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}") if "json" in r.headers.get("Content-Type", "") else r.read()
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_ui_read_and_csrf_guards(monkeypatch, tmp_path):
    from trader_bee import config
    monkeypatch.setattr(config, "KEY_FILE", tmp_path / "k")
    monkeypatch.setattr(config, "ARM_FILE", tmp_path / "ARMED")
    httpd, port = _serve()
    try:
        code, state = _req(port, "/api/hive")
        assert code == 200 and state["trader"]["ok"] and state["blueprint"]["ok"]
        assert state["trader"]["effective_mode"] == "paper"
        # no custom header -> forbidden (a web page can't forge this without a CORS preflight)
        assert _req(port, "/api/trader/pause", {}, {"Content-Type": "application/json"})[0] == 403
        assert _req(port, "/api/trader/pause", {}, {"Content-Type": "text/plain", "X-Hive": "1"})[0] == 403
        code, c = _req(port, "/api/trader/pause", {"reason": "t"}, {"Content-Type": "application/json", "X-Hive": "1"})
        assert code == 200 and c["paused"] is True
        assert _req(port, "/api/trader/approve", {"id": "nope"}, {"Content-Type": "application/json", "X-Hive": "1"})[0] == 409
        assert _req(port, "/api/trader/arm", {}, {"Content-Type": "application/json", "X-Hive": "1"})[0] == 404  # arming is CLI-only
        assert _req(port, "/api/hive", headers={"Host": "evil.example"})[0] == 403  # DNS-rebinding guard
    finally:
        httpd.shutdown()

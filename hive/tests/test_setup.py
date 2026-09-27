import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


@pytest.fixture
def kw(tmp_path, monkeypatch):
    """keys + wizard wired to temp files and a fake network; scripted answers."""
    monkeypatch.setenv("HIVE_DATA", str(tmp_path / "hive"))
    from hive import keys, setup_wizard
    menv, renv = tmp_path / "module.env", tmp_path / "root.env"
    menv.write_text("ONEINCH_API_KEY=PASTE_YOUR_1INCH_API_KEY_HERE\n# keep this comment\n")
    for s in keys.SPECS:
        monkeypatch.setattr(s, "file", renv if s.name == "X_BEARER_TOKEN" else menv)
    (tmp_path / "SETUP-STATE.md").write_text("# SETUP-STATE\n## Steps\n(nothing recorded yet — run SETUP-CLAUDE.md Step 0)\n")
    monkeypatch.setattr(keys, "HIVE_ROOT", tmp_path)
    good = {"GOOD1INCH": 200, "GOODCGKEY1": 200}

    def http(url, method, headers, body):
        if "1inch" in url:
            return good.get(headers["Authorization"].split()[-1], 401), b"{}"
        if "coingecko" in url:
            k = headers.get("x-cg-demo-api-key") or headers.get("x-cg-pro-api-key")
            return (200, b"{}") if (k == "GOODCGKEY1" and "x-cg-demo-api-key" in headers) else (400, b"{}")
        if "alchemy" in url:
            return 200, json.dumps({"result": "0x2105" if body["method"] == "eth_chainId" else "0x10"}).encode()
        raise OSError("offline")
    monkeypatch.setattr(keys, "http", http)
    answers, secrets_ = [], []
    out = []
    monkeypatch.setattr(setup_wizard, "ask", lambda p="": answers.pop(0) if answers else "")
    monkeypatch.setattr(setup_wizard, "ask_secret", lambda p="": secrets_.pop(0))
    monkeypatch.setattr(setup_wizard, "say", lambda *a: out.append(" ".join(map(str, a))))
    monkeypatch.setattr(setup_wizard, "_trader_steps", lambda: None)

    class K:
        pass
    k = K()
    k.keys, k.wiz, k.menv, k.renv, k.answers, k.secrets, k.out, k.root = keys, setup_wizard, menv, renv, answers, secrets_, out, tmp_path
    return k


def test_full_walkthrough(kw):
    # 1inch: bad key -> retry -> good ; alchemy good ; coingecko (auto demo) ; rest SKIP ; base rpc: accept alchemy offer
    kw.secrets += ["BADKEY123", "GOOD1INCH", "ALCHEMYKEY123", "GOODCGKEY1", "SKIP", "SKIP", "SKIP", "SKIP", "SKIP"]
    kw.answers += ["R", "", ""]  # retry after reject ; accept alchemy-as-base-rpc ; (spare)
    assert kw.wiz.run() == 0
    env = kw.keys.parse_env(kw.menv)
    assert env["ONEINCH_API_KEY"] == "GOOD1INCH"
    assert env["ALCHEMY_API_KEY"] == "ALCHEMYKEY123"
    assert env["COINGECKO_API_KEY"] == "GOODCGKEY1" and env["COINGECKO_API_PLAN"] == "demo"
    assert env["BASE_RPC_URL"] == "https://base-mainnet.g.alchemy.com/v2/ALCHEMYKEY123"
    assert "BADKEY123" not in kw.menv.read_text()  # a rejected key is never saved silently
    assert "# keep this comment" in kw.menv.read_text()
    rec = kw.keys.record()
    assert rec["ONEINCH_API_KEY"]["status"] == "DONE" and rec["CODEX_API_KEY"]["status"] == "SKIPPED"
    ss = (kw.root / "SETUP-STATE.md").read_text()
    assert "HIVE KEYS · ONEINCH_API_KEY · DONE" in ss and "nothing recorded yet" not in ss
    assert not any("GOOD1INCH" in line or "ALCHEMYKEY123" in line for line in kw.out)  # never printed
    assert kw.keys.undecided() == [kw.keys.BY_NAME["ROBINHOOD_RPC_URL"]] or kw.keys.undecided() == []


def test_lowercase_skip_is_not_a_skip(kw):
    kw.secrets += ["skip", "SKIP"]
    kw.wiz._one(kw.keys.BY_NAME["CODEX_API_KEY"], 1, 1)
    assert kw.keys.record()["CODEX_API_KEY"]["status"] == "SKIPPED"
    assert any("capitals" in line for line in kw.out)


def test_unverifiable_saved_as_unverified(kw):
    kw.secrets += ["ELFAKEY123456"]
    kw.wiz._one(kw.keys.BY_NAME["ELFA_API_KEY"], 1, 1)
    assert kw.keys.record()["ELFA_API_KEY"]["status"] == "UNVERIFIED"
    assert kw.keys.parse_env(kw.menv)["ELFA_API_KEY"] == "ELFAKEY123456"


def test_x_token_goes_to_root_env(kw):
    kw.secrets += ["XTOKEN1234567"]
    kw.wiz._one(kw.keys.BY_NAME["X_BEARER_TOKEN"], 1, 1)
    assert kw.keys.parse_env(kw.renv)["X_BEARER_TOKEN"] == "XTOKEN1234567"


def test_keep_existing_and_only_missing(kw):
    kw.menv.write_text("ONEINCH_API_KEY=GOOD1INCH\n")
    assert kw.keys.BY_NAME["ONEINCH_API_KEY"] not in kw.keys.undecided()
    kw.answers += [""]
    kw.wiz._one(kw.keys.BY_NAME["ONEINCH_API_KEY"], 1, 1)  # Enter keeps it
    assert kw.keys.parse_env(kw.menv)["ONEINCH_API_KEY"] == "GOOD1INCH"


def test_keep_anyway_recorded_unverified(kw):
    kw.secrets += ["WRONGKEY99"]
    kw.answers += ["K"]
    kw.wiz._one(kw.keys.BY_NAME["ONEINCH_API_KEY"], 1, 1)
    assert kw.keys.record()["ONEINCH_API_KEY"]["status"] == "UNVERIFIED"


def test_write_key_refuses_newlines(kw):
    with pytest.raises(ValueError):
        kw.keys.write_key(kw.menv, "ONEINCH_API_KEY", "abc\nEVIL=1")


def test_mask_never_reveals():
    from hive import keys
    assert keys.mask("abcdefghijklmnop") == "abcd…op (16 chars)"
    assert "SECRETKEY" not in keys.mask("https://base-mainnet.g.alchemy.com/v2/SECRETKEYSECRETKEY123")

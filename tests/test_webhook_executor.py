"""Tests for PickMyTrade webhook executor."""

import json
import math
import os
import tempfile
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from unittest.mock import patch

import pytest

from runners.webhook_executor import WebhookExecutor, POINT_VALUES


# ── Fixtures ──────────────────────────────────────────────────────

def make_config(
    api_url="http://127.0.0.1:19999/webhook",
    primary_enabled=True,
    primary_multiplier=1.0,
    mirrors=None,
):
    """Create a temp config file and return its path."""
    config = {
        "api_url": api_url,
        "retry_max": 1,
        "retry_delay_sec": 0.01,
        "contract_months": {
            "ES": "ESM6", "NQ": "NQM6", "MES": "MESM6", "MNQ": "MNQM6",
        },
        "strategy_groups": {
            "ict_v10": {
                "primary_account": {
                    "name": "test_primary",
                    "token": "tok_primary",
                    "account_id": "acct_primary",
                    "qty_multiplier": primary_multiplier,
                    "enabled": primary_enabled,
                },
                "mirror_accounts": mirrors or [],
            }
        },
    }
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(config, f)
    return path


@pytest.fixture
def single_account_config():
    path = make_config()
    yield path
    os.unlink(path)


@pytest.fixture
def multi_account_config():
    mirrors = [
        {"name": "mirror_1", "token": "tok_m1", "account_id": "acct_m1",
         "qty_multiplier": 1.0, "enabled": True},
        {"name": "mirror_2", "token": "tok_m2", "account_id": "acct_m2",
         "qty_multiplier": 0.5, "enabled": True},
    ]
    path = make_config(mirrors=mirrors)
    yield path
    os.unlink(path)


@pytest.fixture
def disabled_mirror_config():
    mirrors = [
        {"name": "disabled_1", "token": "tok_d1", "account_id": "acct_d1",
         "qty_multiplier": 1.0, "enabled": False},
    ]
    path = make_config(mirrors=mirrors)
    yield path
    os.unlink(path)


# ── Mock HTTP Server ──────────────────────────────────────────────

class EchoHandler(BaseHTTPRequestHandler):
    """Captures webhook payloads for assertion."""
    received = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        EchoHandler.received.append(json.loads(body))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def log_message(self, format, *args):
        pass  # Suppress server logs during tests


@pytest.fixture
def echo_server():
    """Start a local HTTP server that captures webhook payloads."""
    EchoHandler.received = []
    server = HTTPServer(("127.0.0.1", 19999), EchoHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()


# ── Tests ─────────────────────────────────────────────────────────

class TestInit:
    def test_load_config(self, single_account_config):
        ex = WebhookExecutor(single_account_config, "ict_v10")
        assert ex.get_account_count() == 1
        assert ex.primary["name"] == "test_primary"

    def test_multi_account(self, multi_account_config):
        ex = WebhookExecutor(multi_account_config, "ict_v10")
        assert ex.get_account_count() == 3

    def test_disabled_mirror_not_counted(self, disabled_mirror_config):
        ex = WebhookExecutor(disabled_mirror_config, "ict_v10")
        assert ex.get_account_count() == 1  # primary only

    def test_missing_config_raises(self):
        with pytest.raises(FileNotFoundError):
            WebhookExecutor("/nonexistent/path.json", "ict_v10")

    def test_missing_strategy_group_raises(self, single_account_config):
        with pytest.raises(ValueError, match="not found"):
            WebhookExecutor(single_account_config, "nonexistent_group")


class TestDollarSl:
    def test_es_dollar_sl(self, single_account_config):
        ex = WebhookExecutor(single_account_config, "ict_v10")
        # ES: 2 points risk * $50/point = $100
        sl = ex._calculate_dollar_sl("ES", entry_price=6100.0, stop_price=6098.0)
        assert sl == 100.0

    def test_nq_dollar_sl(self, single_account_config):
        ex = WebhookExecutor(single_account_config, "ict_v10")
        # NQ: 10 points risk * $20/point = $200
        sl = ex._calculate_dollar_sl("NQ", entry_price=22000.0, stop_price=21990.0)
        assert sl == 200.0

    def test_mes_dollar_sl(self, single_account_config):
        ex = WebhookExecutor(single_account_config, "ict_v10")
        # MES: 4 points risk * $5/point = $20
        sl = ex._calculate_dollar_sl("MES", entry_price=6100.0, stop_price=6096.0)
        assert sl == 20.0

    def test_mnq_dollar_sl(self, single_account_config):
        ex = WebhookExecutor(single_account_config, "ict_v10")
        # MNQ: 15 points risk * $2/point = $30
        sl = ex._calculate_dollar_sl("MNQ", entry_price=22000.0, stop_price=21985.0)
        assert sl == 30.0

    def test_short_dollar_sl(self, single_account_config):
        ex = WebhookExecutor(single_account_config, "ict_v10")
        # Short: stop above entry, same calculation
        sl = ex._calculate_dollar_sl("ES", entry_price=6100.0, stop_price=6103.0)
        assert sl == 150.0  # 3 points * $50

    def test_unknown_symbol_raises(self, single_account_config):
        ex = WebhookExecutor(single_account_config, "ict_v10")
        with pytest.raises(ValueError, match="No point value"):
            ex._calculate_dollar_sl("ZZ", 100.0, 99.0)


class TestSymbolMapping:
    def test_es_maps_to_contract_month(self, single_account_config):
        ex = WebhookExecutor(single_account_config, "ict_v10")
        assert ex._get_pmt_symbol("ES") == "ESM6"
        assert ex._get_pmt_symbol("NQ") == "NQM6"

    def test_unknown_symbol_passthrough(self, single_account_config):
        ex = WebhookExecutor(single_account_config, "ict_v10")
        assert ex._get_pmt_symbol("XYZ") == "XYZ"


class TestOpenPosition:
    def test_payload_format(self, single_account_config, echo_server):
        ex = WebhookExecutor(single_account_config, "ict_v10")
        results = ex.open_position(
            symbol="ES", direction="LONG", contracts=3,
            stop_price=6098.0, entry_price=6100.0,
            paper_trade_id="PAPER_ES_1",
        )

        assert results["test_primary"]["success"]
        payload = EchoHandler.received[0]
        assert payload["symbol"] == "ESM6"
        assert payload["data"] == "buy"
        assert payload["quantity"] == 3
        assert payload["token"] == "tok_primary"
        assert payload["account_id"] == "acct_primary"
        # dollar_sl = 2pts * $50 = $100
        assert payload["advance_tp_sl"][0]["dollar_sl"] == 100.0
        assert payload["advance_tp_sl"][0]["dollar_tp"] == 0
        assert payload["advance_tp_sl"][0]["trail"] == 0

    def test_short_direction(self, single_account_config, echo_server):
        ex = WebhookExecutor(single_account_config, "ict_v10")
        ex.open_position(
            symbol="NQ", direction="SHORT", contracts=2,
            stop_price=22010.0, entry_price=22000.0,
            paper_trade_id="PAPER_NQ_1",
        )

        payload = EchoHandler.received[0]
        assert payload["data"] == "sell"
        assert payload["quantity"] == 2

    def test_qty_multiplier(self, echo_server):
        path = make_config(primary_multiplier=0.5)
        try:
            ex = WebhookExecutor(path, "ict_v10")
            ex.open_position(
                symbol="ES", direction="LONG", contracts=3,
                stop_price=6098.0, entry_price=6100.0,
            )
            payload = EchoHandler.received[0]
            # floor(3 * 0.5) = 1
            assert payload["quantity"] == 1
        finally:
            os.unlink(path)


class TestPartialClose:
    def test_payload_format(self, single_account_config, echo_server):
        ex = WebhookExecutor(single_account_config, "ict_v10")
        results = ex.partial_close(
            symbol="ES", direction="LONG", contracts=1,
            paper_trade_id="PAPER_ES_1",
        )

        assert results["test_primary"]["success"]
        payload = EchoHandler.received[0]
        assert payload["data"] == "sell"  # opposing direction for close
        assert payload["quantity"] == 1
        assert payload["symbol"] == "ESM6"

    def test_short_partial_close(self, single_account_config, echo_server):
        ex = WebhookExecutor(single_account_config, "ict_v10")
        ex.partial_close(symbol="NQ", direction="SHORT", contracts=1)
        payload = EchoHandler.received[0]
        assert payload["data"] == "buy"  # opposing direction


class TestUpdateStop:
    def test_payload_format(self, single_account_config, echo_server):
        ex = WebhookExecutor(single_account_config, "ict_v10")
        results = ex.update_stop(
            symbol="ES", direction="LONG",
            new_stop_price=6105.0, entry_price=6100.0,
            paper_trade_id="PAPER_ES_1",
        )

        assert results["test_primary"]["success"]
        payload = EchoHandler.received[0]
        assert payload["data"] == "buy"
        assert payload["update_sl"] is True
        # dollar_sl = 5pts * $50 = $250
        assert payload["dollar_sl"] == 250.0

    def test_breakeven_stop(self, single_account_config, echo_server):
        ex = WebhookExecutor(single_account_config, "ict_v10")
        ex.update_stop(
            symbol="ES", direction="LONG",
            new_stop_price=6100.0, entry_price=6100.0,
        )
        payload = EchoHandler.received[0]
        assert payload["dollar_sl"] == 0.0  # breakeven = zero dollar_sl


class TestClosePosition:
    def test_payload_format(self, single_account_config, echo_server):
        ex = WebhookExecutor(single_account_config, "ict_v10")
        results = ex.close_position(
            symbol="ES", direction="LONG",
            paper_trade_id="PAPER_ES_1",
        )

        assert results["test_primary"]["success"]
        payload = EchoHandler.received[0]
        assert payload["data"] == "close"
        assert payload["symbol"] == "ESM6"


class TestCloseAll:
    def test_with_symbol(self, single_account_config, echo_server):
        ex = WebhookExecutor(single_account_config, "ict_v10")
        ex.close_all(symbol="ES")
        payload = EchoHandler.received[0]
        assert payload["data"] == "close"
        assert payload["symbol"] == "ESM6"

    def test_without_symbol(self, single_account_config, echo_server):
        ex = WebhookExecutor(single_account_config, "ict_v10")
        ex.close_all()
        payload = EchoHandler.received[0]
        assert payload["data"] == "close"
        assert "symbol" not in payload


class TestMultipleAccounts:
    def test_fires_all_accounts(self, multi_account_config, echo_server):
        ex = WebhookExecutor(multi_account_config, "ict_v10")
        results = ex.open_position(
            symbol="ES", direction="LONG", contracts=3,
            stop_price=6098.0, entry_price=6100.0,
        )

        assert len(results) == 3
        assert all(r["success"] for r in results.values())
        # 3 accounts = 3 payloads received
        assert len(EchoHandler.received) == 3

    def test_mirror_qty_multiplier(self, multi_account_config, echo_server):
        ex = WebhookExecutor(multi_account_config, "ict_v10")
        ex.open_position(
            symbol="ES", direction="LONG", contracts=3,
            stop_price=6098.0, entry_price=6100.0,
        )

        # Find mirror_2's payload (0.5 multiplier)
        m2_payloads = [p for p in EchoHandler.received if p["token"] == "tok_m2"]
        assert len(m2_payloads) == 1
        assert m2_payloads[0]["quantity"] == 1  # floor(3 * 0.5)

    def test_primary_has_multiple_accounts_field(self, multi_account_config, echo_server):
        ex = WebhookExecutor(multi_account_config, "ict_v10")
        ex.close_position(symbol="ES", direction="LONG")

        primary_payloads = [p for p in EchoHandler.received if p["token"] == "tok_primary"]
        assert len(primary_payloads) == 1
        assert "multiple_accounts" in primary_payloads[0]
        assert len(primary_payloads[0]["multiple_accounts"]) == 2


class TestDisabledAccounts:
    def test_disabled_primary_skipped(self, echo_server):
        path = make_config(primary_enabled=False)
        try:
            ex = WebhookExecutor(path, "ict_v10")
            assert ex.get_account_count() == 0
            results = ex.close_position(symbol="ES", direction="LONG")
            assert len(results) == 0
            assert len(EchoHandler.received) == 0
        finally:
            os.unlink(path)

    def test_disabled_mirror_skipped(self, disabled_mirror_config, echo_server):
        ex = WebhookExecutor(disabled_mirror_config, "ict_v10")
        results = ex.close_position(symbol="ES", direction="LONG")
        # Only primary fires, disabled mirror skipped
        assert len(results) == 1
        assert "test_primary" in results


class _ReusableHTTPServer(HTTPServer):
    """HTTPServer with SO_REUSEADDR for reliable test port binding on Windows."""
    allow_reuse_address = True


class TestRetry:
    def test_retries_on_server_error(self, single_account_config):
        """Verify retry behavior when server returns 500."""
        import time
        call_count = 0

        class FailOnceHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                nonlocal call_count
                length = int(self.headers.get("Content-Length", 0))
                self.rfile.read(length)
                call_count += 1
                if call_count == 1:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b"error")
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'{"status":"ok"}')

            def log_message(self, format, *args):
                pass

        server = _ReusableHTTPServer(("127.0.0.1", 19998), FailOnceHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.2)

        path = make_config(api_url="http://127.0.0.1:19998/webhook")
        try:
            ex = WebhookExecutor(path, "ict_v10")
            results = ex.close_position(symbol="ES", direction="LONG")
            assert results["test_primary"]["success"]
            assert call_count == 2  # 1 fail + 1 success
        finally:
            os.unlink(path)
            server.shutdown()

    def test_no_retry_on_4xx(self, single_account_config):
        """Verify 4xx errors are not retried (once server is reached)."""
        import time
        call_count = 0

        class BadRequestHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                nonlocal call_count
                length = int(self.headers.get("Content-Length", 0))
                self.rfile.read(length)
                call_count += 1
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"bad request")

            def log_message(self, format, *args):
                pass

        server = _ReusableHTTPServer(("127.0.0.1", 19997), BadRequestHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.2)

        path = make_config(api_url="http://127.0.0.1:19997/webhook")
        try:
            ex = WebhookExecutor(path, "ict_v10")
            results = ex.close_position(symbol="ES", direction="LONG")
            assert not results["test_primary"]["success"]
            assert results["test_primary"]["status_code"] == 400
            assert call_count == 1  # No retry on 4xx
        finally:
            os.unlink(path)
            server.shutdown()

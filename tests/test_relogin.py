"""Auto re-login on baostock session expiry (unit, no network)."""

from ashare_mcp.providers.baostock import BaostockProvider


class FakeSession:
    def __init__(self):
        self.ensure_calls = 0
        self.relogin_calls = 0

    def ensure_login(self):
        self.ensure_calls += 1

    def relogin(self):
        self.relogin_calls += 1


class FakeRS:
    def __init__(self, error_code="0", error_msg="success", fields=None, rows=None):
        self.error_code = error_code
        self.error_msg = error_msg
        self.fields = fields or ["code"]
        self._rows = list(rows or [])
        self._i = -1

    def next(self):
        self._i += 1
        return self._i < len(self._rows)

    def get_row_data(self):
        return self._rows[self._i]


def test_retries_once_on_auth_error():
    sess = FakeSession()
    p = BaostockProvider(session=sess)

    calls = {"n": 0}

    def fn(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeRS(error_code="10001001", error_msg="you don't login.")
        return FakeRS(fields=["code"], rows=[["sh.600519"]])

    out = p._q(fn)
    assert out["count"] == 1
    assert calls["n"] == 2            # query was retried
    assert sess.relogin_calls == 1    # session was refreshed once


def test_no_retry_on_success():
    sess = FakeSession()
    p = BaostockProvider(session=sess)
    out = p._q(lambda **k: FakeRS(fields=["code"], rows=[["sh.600519"]]))
    assert out["count"] == 1
    assert sess.relogin_calls == 0


def test_non_auth_error_not_retried():
    """A non-auth baostock error should surface immediately, not trigger relogin."""
    import pytest

    sess = FakeSession()
    p = BaostockProvider(session=sess)
    calls = {"n": 0}

    def fn(**kwargs):
        calls["n"] += 1
        return FakeRS(error_code="10002007", error_msg="网络接收错误")

    with pytest.raises(RuntimeError):
        p._q(fn)
    assert calls["n"] == 1
    assert sess.relogin_calls == 0

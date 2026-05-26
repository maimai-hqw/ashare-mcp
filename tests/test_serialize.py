import pytest

from ashare_mcp.serialize import rs_to_payload


class FakeRS:
    """Mimics a baostock ResultData forward cursor."""

    def __init__(self, fields, rows, error_code="0", error_msg="success"):
        self.fields = fields
        self._rows = list(rows)
        self.error_code = error_code
        self.error_msg = error_msg
        self._i = -1

    def next(self):
        self._i += 1
        return self._i < len(self._rows)

    def get_row_data(self):
        return self._rows[self._i]


def test_rs_to_payload_basic():
    rs = FakeRS(
        fields=["code", "code_name", "ipoDate"],
        rows=[["sh.600519", "贵州茅台", "2001-08-27"]],
    )
    out = rs_to_payload(rs)
    assert out == {
        "count": 1,
        "fields": ["code", "code_name", "ipoDate"],
        "data": [{"code": "sh.600519", "code_name": "贵州茅台", "ipoDate": "2001-08-27"}],
    }


def test_rs_to_payload_empty():
    out = rs_to_payload(FakeRS(fields=["code"], rows=[]))
    assert out == {"count": 0, "fields": ["code"], "data": []}


def test_rs_to_payload_raises_on_error():
    rs = FakeRS(fields=[], rows=[], error_code="10001", error_msg="网络错误")
    with pytest.raises(RuntimeError, match="10001"):
        rs_to_payload(rs)

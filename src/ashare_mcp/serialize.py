"""Normalize a baostock ResultData object into a JSON-serializable payload.

Every baostock ``query_*`` call returns a ResultData with ``error_code`` /
``error_msg`` / ``fields`` and a forward cursor (``next()`` + ``get_row_data()``).
``rs_to_payload`` drains the cursor once, checks for errors, and returns a
uniform shape so every tool in the server presents data the same way:

    {"count": int, "fields": [str, ...], "data": [{field: value, ...}, ...]}
"""

from __future__ import annotations

from typing import Any, Dict, List, Protocol


class ResultData(Protocol):
    error_code: str
    error_msg: str
    fields: List[str]

    def next(self) -> bool: ...
    def get_row_data(self) -> List[Any]: ...


def rs_to_payload(rs: ResultData) -> Dict[str, Any]:
    """Drain ``rs`` into ``{count, fields, data}``; raise on a baostock error."""
    if rs.error_code != "0":
        raise RuntimeError(f"baostock 查询失败 (error_code={rs.error_code}): {rs.error_msg}")

    fields = list(rs.fields)
    rows: List[Dict[str, Any]] = []
    while (rs.error_code == "0") and rs.next():
        rows.append(dict(zip(fields, rs.get_row_data())))

    return {"count": len(rows), "fields": fields, "data": rows}

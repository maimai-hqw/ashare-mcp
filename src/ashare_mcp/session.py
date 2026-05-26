"""baostock session lifecycle: login once, reuse, logout on shutdown.

baostock keeps a single process-global session and is not thread-safe, so the
server serializes all calls (see ``server.py``). ``ensure_login`` is therefore
only ever entered by one thread at a time and a plain flag is sufficient.
"""

from __future__ import annotations

import contextlib
import logging
import os

import baostock as bs

logger = logging.getLogger("ashare-mcp")


@contextlib.contextmanager
def silence_stdout():
    """Swallow baostock's stdout chatter ('login success!', etc.).

    Under stdio transport, stdout is the JSON-RPC channel — baostock's prints
    would corrupt it. The MCP transport captured ``sys.stdout.buffer`` at
    startup, so reassigning the ``sys.stdout`` *name* to devnull here silences
    baostock's ``print()`` without affecting protocol writes. baostock calls are
    serialized by the server lock, so this global redirect is race-free in
    practice.
    """
    with open(os.devnull, "w") as devnull, contextlib.redirect_stdout(devnull):
        yield


class BaostockSession:
    def __init__(self) -> None:
        self._logged_in = False

    def ensure_login(self) -> None:
        if self._logged_in:
            return
        with silence_stdout():
            lg = bs.login()
        if lg.error_code != "0":
            raise RuntimeError(
                f"baostock 登录失败 (error_code={lg.error_code}): {lg.error_msg}"
            )
        self._logged_in = True
        logger.info("baostock logged in")

    def relogin(self) -> None:
        """Force a fresh login (call after the session expired server-side)."""
        self._logged_in = False
        self.ensure_login()

    def logout(self) -> None:
        if not self._logged_in:
            return
        try:
            with silence_stdout():
                bs.logout()
        finally:
            self._logged_in = False
        logger.info("baostock logged out")

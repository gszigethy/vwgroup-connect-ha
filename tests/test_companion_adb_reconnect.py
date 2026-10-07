# Copyright 2026 Prash Balan (@its-me-prash) — GNU AGPL v3.0-or-later
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A broken ADB socket is dropped, so the next read reconnects.

adb-shell keeps ``available`` True after the socket breaks, so before this the
transport looked connected forever and every poll failed with "Broken pipe"
until Home Assistant restarted.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.vag_connect.companion.transport import (
    CompanionTransportError,
    NetworkAdbTransport,
)


def _transport(device) -> NetworkAdbTransport:
    t = NetworkAdbTransport("phone", 5555, "/k")
    t._device = device
    return t


@pytest.mark.asyncio
async def test_broken_pipe_drops_the_device_and_raises_the_channel_error() -> None:
    device = MagicMock()
    device.available = True
    device.shell.side_effect = BrokenPipeError(32, "Broken pipe")
    t = _transport(device)
    with pytest.raises(CompanionTransportError, match="BrokenPipeError"):
        await t.shell("echo")
    device.close.assert_called_once()
    assert t.connected is False


@pytest.mark.asyncio
async def test_the_next_read_reconnects() -> None:
    device = MagicMock()
    device.shell.side_effect = BrokenPipeError(32, "Broken pipe")
    t = _transport(device)
    with pytest.raises(CompanionTransportError):
        await t.shell("echo")
    fresh = MagicMock()
    fresh.available = True
    fresh.shell.return_value = "ok"

    def _connect(_timeout_s: float) -> None:
        t._device = fresh

    t._connect_blocking = _connect  # type: ignore[method-assign]
    if not t.connected:
        await t.connect()
    assert await t.shell("echo") == "ok"


@pytest.mark.asyncio
async def test_a_working_shell_is_untouched() -> None:
    device = MagicMock()
    device.available = True
    device.shell.return_value = "out"
    t = _transport(device)
    assert await t.shell("echo") == "out"
    device.close.assert_not_called()
    assert t.connected is True

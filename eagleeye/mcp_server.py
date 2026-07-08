"""Compatibility shim — use ``eagleeye.servers.mcp.server`` in new code."""

import sys

from eagleeye.servers.mcp import server as _server

sys.modules[__name__] = _server

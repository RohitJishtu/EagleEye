"""Compatibility shim — use ``eagleeye.integrations.anthropic.client`` in new code."""

import sys

from eagleeye.integrations.anthropic import client as _client

sys.modules[__name__] = _client

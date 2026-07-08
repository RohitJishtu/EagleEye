"""Compatibility shim — use ``eagleeye.integrations.github.client`` in new code."""

import sys

from eagleeye.integrations.github import client as _client

sys.modules[__name__] = _client

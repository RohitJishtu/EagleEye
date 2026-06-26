"""Compatibility shim — use ``eagleeye.storage.history`` in new code."""

import sys

from eagleeye.storage import history as _history

sys.modules[__name__] = _history

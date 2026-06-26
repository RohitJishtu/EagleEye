"""Compatibility shim — use ``eagleeye.core.config`` in new code."""

import sys

from eagleeye.core import config as _config

sys.modules[__name__] = _config

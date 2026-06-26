"""Compatibility shim — use ``eagleeye.presentation.html.dashboard`` in new code."""

import sys

from eagleeye.presentation.html import dashboard as _dashboard

sys.modules[__name__] = _dashboard

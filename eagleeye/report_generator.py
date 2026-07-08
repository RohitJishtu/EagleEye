"""Compatibility shim — use ``eagleeye.presentation.html.report`` in new code."""

import sys

from eagleeye.presentation.html import report as _report

sys.modules[__name__] = _report

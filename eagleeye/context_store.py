"""Compatibility shim — use ``eagleeye.storage.context`` in new code."""

import sys

from eagleeye.storage import context as _context

sys.modules[__name__] = _context

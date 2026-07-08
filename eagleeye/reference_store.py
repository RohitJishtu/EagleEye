"""Compatibility shim — use ``eagleeye.storage.reference`` in new code."""

import sys

from eagleeye.storage import reference as _reference

sys.modules[__name__] = _reference

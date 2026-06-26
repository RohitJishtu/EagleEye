"""Compatibility shim — use ``eagleeye.storage.catalog`` in new code."""

import sys

from eagleeye.storage import catalog as _catalog

sys.modules[__name__] = _catalog

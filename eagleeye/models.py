"""Compatibility shim — use ``eagleeye.core.models`` in new code."""

import sys

from eagleeye.core import models as _models

sys.modules[__name__] = _models

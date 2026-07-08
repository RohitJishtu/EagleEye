"""Compatibility shim — use ``eagleeye.core.prompt_loader`` in new code."""

import sys

from eagleeye.core import prompt_loader as _prompt_loader

sys.modules[__name__] = _prompt_loader

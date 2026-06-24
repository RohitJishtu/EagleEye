"""Load and parameterize system prompts from ~/.eagleeye/prompts.yml."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


class PromptLibrary:
    """Load and manage parameterized prompts from YAML files.

    Looks for prompts in this order:
    1. User overrides: ~/.eagleeye/prompts/ (custom user edits)
    2. Source code: eagleeye/core/prompts/ (public, versioned defaults)
    """

    def __init__(self, prompts_dir: Optional[Path] = None):
        """Initialize prompt library.

        Args:
            prompts_dir: Directory containing prompts. Defaults to source code path.
        """
        if prompts_dir is None:
            # Try user override directory first
            user_dir = Path.home() / ".eagleeye" / "prompts"
            if user_dir.exists():
                prompts_dir = user_dir
            else:
                # Fall back to source code (public, versioned)
                prompts_dir = Path(__file__).parent / "prompts"

        self.prompts_dir = prompts_dir
        self._params = {}
        self._prompts = {}
        self._load()

    def _load(self) -> None:
        """Load all YAML files from prompts directory."""
        if not self.prompts_dir.exists():
            logger.warning(f"Prompts directory not found: {self.prompts_dir}")
            return

        # Load parameters
        params_file = self.prompts_dir / "parameters.yml"
        if params_file.exists():
            try:
                with open(params_file) as f:
                    self._params = yaml.safe_load(f) or {}
                logger.debug(f"Loaded parameters from {params_file}")
            except Exception as e:
                logger.error(f"Failed to load parameters: {e}")

        # Load all prompt YAML files recursively
        for yaml_file in self.prompts_dir.rglob("*.yml"):
            if yaml_file.name == "parameters.yml":
                continue  # Already loaded
            try:
                with open(yaml_file) as f:
                    data = yaml.safe_load(f) or {}
                # Store by relative path (e.g., "pr_review", "agents/pr", "utils/bug_scanner")
                rel_path = yaml_file.relative_to(self.prompts_dir)
                key = str(rel_path.with_suffix("")).replace("/", ".")
                self._prompts[key] = data
                logger.debug(f"Loaded prompt from {yaml_file} (key: {key})")
            except Exception as e:
                logger.error(f"Failed to load {yaml_file}: {e}")

    def _substitute_params(self, text: str, overrides: Optional[dict] = None) -> str:
        """Substitute {{PARAM}} placeholders with values from parameters.yml.

        Args:
            text: Text containing {{PARAM}} placeholders
            overrides: Dict of parameter overrides (takes precedence)

        Returns:
            Text with placeholders substituted
        """
        params = self._params.copy()
        if overrides:
            params.update(overrides)

        for key, value in params.items():
            text = text.replace(f"{{{{{key}}}}}", str(value))

        return text

    def get_prompt(
        self,
        path: str,
        overrides: Optional[dict] = None,
    ) -> str:
        """Get a prompt by path (e.g., 'pr_review', 'agents.pr', 'utils.bug_scanner').

        Args:
            path: Dot-separated path to prompt YAML key
            overrides: Dict of parameter overrides

        Returns:
            Parameterized prompt text (system_prompt field)
        """
        if path not in self._prompts:
            logger.warning(f"Prompt not found: {path}. Available: {list(self._prompts.keys())}")
            return ""

        prompt_data = self._prompts[path]
        if not isinstance(prompt_data, dict):
            logger.warning(f"Prompt data is not a dict: {path}")
            return ""

        system_prompt = prompt_data.get("system_prompt", "")
        if not isinstance(system_prompt, str):
            logger.warning(f"system_prompt not found or not a string in {path}")
            return ""

        # Substitute parameters
        return self._substitute_params(system_prompt, overrides)

    def get_max_findings(self, agent: Optional[str] = None) -> int:
        """Get max findings limit for an agent (or global).

        Args:
            agent: Agent name (pr, schema, lineage, reference, arch_drift) or None for global

        Returns:
            Max findings integer
        """
        if agent:
            # Try agent-specific limit
            limit = (
                self._data.get("prompts", {})
                .get("agents", {})
                .get(agent, {})
                .get("max_findings")
            )
            if limit:
                return int(limit) if isinstance(limit, (int, str)) else 8
        else:
            # Try global limit
            limit = self._data.get("parameters", {}).get("max_file_comments")
            if limit:
                return int(limit) if isinstance(limit, (int, str)) else 8

        return 8  # default fallback

    def get_all_parameters(self, overrides: Optional[dict] = None) -> dict:
        """Get all parameters (merged with overrides).

        Args:
            overrides: Dict of parameter overrides

        Returns:
            Dict of all parameters
        """
        params = self._params.copy()
        if overrides:
            params.update(overrides)
        return params

    def list_prompts(self) -> list[str]:
        """List all available prompt keys.

        Returns:
            Sorted list of prompt keys (e.g., ['pr_review', 'agents.pr', 'synthesis', ...])
        """
        return sorted(self._prompts.keys())


# Global singleton (lazy-loaded)
_LIBRARY: Optional[PromptLibrary] = None


def load_library(prompts_file: Optional[Path] = None) -> PromptLibrary:
    """Load or return cached prompt library."""
    global _LIBRARY
    if _LIBRARY is None:
        _LIBRARY = PromptLibrary(prompts_file)
    return _LIBRARY


def get_prompt(path: str, overrides: Optional[dict] = None) -> str:
    """Convenience function: get a prompt by path.

    Args:
        path: Dot-separated path (e.g., 'pr_review', 'agents.pr')
        overrides: Parameter overrides

    Returns:
        Parameterized prompt text
    """
    library = load_library()
    return library.get_prompt(path, overrides)


def get_max_findings(agent: Optional[str] = None) -> int:
    """Convenience function: get max findings limit.

    Args:
        agent: Agent name or None for global

    Returns:
        Max findings integer
    """
    library = load_library()
    return library.get_max_findings(agent)

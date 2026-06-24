"""MCP tool registration — import submodules so @mcp.tool decorators run."""

from . import audit, github, misc, review

__all__ = ["audit", "github", "misc", "review"]

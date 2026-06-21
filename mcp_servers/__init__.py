"""
MCP Tool Servers — PRD §8.2.

Four servers exposed in this package:

  opensanctions        — screen_entity  (Fund UBO or BLE counterparty, real free API)
  audit_history        — get_audit_history  (Fund- or BLE-scoped, internal)
  entity_relationships — get_ubo_chain, get_shared_counterparties  (internal)
  ubo_provider         — get_ubo_data  (mocked vendor interface)

Each server module exposes:
  TOOLS: list[dict]           MCP / Anthropic tool_use compatible definitions
  call_tool(name, params)     dispatch called by the agent orchestration layer

ToolResult is the uniform return type for every call_tool() invocation.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    tool_name: str
    params: dict[str, Any]
    result: dict[str, Any]
    is_mock: bool
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

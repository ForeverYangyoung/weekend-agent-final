"""假后台（Mock）与 Tool 注册表。

DryRun / Executor / Compensator 都通过这里调用，而不是在节点里写「假装成功」。
"""

from backend.tools.errors import ToolError
from backend.tools.registry import ToolContext, invoke
from backend.tools.plan_mapping import plan_to_dry_run_calls

__all__ = [
    "ToolError",
    "ToolContext",
    "invoke",
    "plan_to_dry_run_calls",
]

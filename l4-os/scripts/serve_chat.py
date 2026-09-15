"""LoopX Chat 服务桥（供 AiosShell 拉起）。

在共享运行空间起 serve_chat(8767)，使 Personal Workspace 写路径
(/api/*) 与 serve-status(8766) 看到同一个 registry。
路径解析见 l2-memory/scripts/paths.py（环境变量 > config.json["paths"] > 默认）。

依赖：pip install loopx（第三方开源项目，Apache-2.0）；
opencode / OpenScience 可经 MEMCORE_OPENCODE_EXE / MEMCORE_OPENSCIENCE_JS 配置。
"""
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "l2-memory" / "scripts"))

import paths as _paths  # noqa: E402
from loopx.chat_server import serve_chat  # noqa: E402
from loopx.chat_endpoints import AgentEndpointRegistry  # noqa: E402

ROOT = Path(_paths.ROOT)

# Register the two engine ACP endpoints (idempotent upsert). serve_chat loads
# them from the same registry path at startup.
_endpoints = AgentEndpointRegistry(ROOT / ".loopx-runtime" / "chat")
_ENDPOINTS = [
    {
        "agent_id": "opencode",
        "display_name": "OpenCode",
        "adapter_kind": "acp",
        "transport": "stdio",
        "location": "local",
        "trust_scope": "read_only",
        "enabled": True,
        "command": [_paths.OPENCODE_EXE or "opencode", "acp"],
    },
    {
        "agent_id": "openscience",
        "display_name": "OpenScience",
        "adapter_kind": "acp",
        "transport": "stdio",
        "location": "local",
        "trust_scope": "read_only",
        "enabled": True,
        "command": [_paths.NODE_EXE or "node", _paths.OPENSCIENCE_JS or "openscience", "acp"],
    },
]
for _definition in _ENDPOINTS:
    _endpoints.upsert(_definition)

serve_chat(
    host="127.0.0.1",
    port=8767,
    registry_path=ROOT / ".loopx" / "registry.json",
    runtime_root_override=str(ROOT / ".loopx-runtime"),
    scan_roots=[ROOT],
    open_browser=False,
    verbose=True,
)

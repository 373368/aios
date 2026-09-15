"""LoopX Chat 服务桥（供 AiosShell 拉起）。

在共享 D 盘运行时起 serve_chat(8767)，使 Personal Workspace 写路径
(/api/*) 与 serve-status(8766) 看到同一个 ai-os-goal / registry。
"""
from pathlib import Path
from loopx.chat_server import serve_chat
from loopx.chat_endpoints import AgentEndpointRegistry

# Register the two engine ACP endpoints (idempotent upsert). serve_chat loads
# them from the same registry path at startup.
_endpoints = AgentEndpointRegistry(Path(r"D:\AI OS\.loopx-runtime") / "chat")
_ENDPOINTS = [
    {
        "agent_id": "opencode",
        "display_name": "OpenCode",
        "adapter_kind": "acp",
        "transport": "stdio",
        "location": "local",
        "trust_scope": "read_only",
        "enabled": True,
        "command": [r"C:\Program Files\nodejs\node_global\node_modules\opencode-ai\bin\opencode.exe", "acp"],
    },
    {
        "agent_id": "openscience",
        "display_name": "OpenScience",
        "adapter_kind": "acp",
        "transport": "stdio",
        "location": "local",
        "trust_scope": "read_only",
        "enabled": True,
        "command": ["node", r"C:\Program Files\nodejs\node_global\node_modules\@synsci\openscience\bin\openscience", "acp"],
    },
]
for _definition in _ENDPOINTS:
    _endpoints.upsert(_definition)

serve_chat(
    host="127.0.0.1",
    port=8767,
    registry_path=Path(r"D:\AI OS\.loopx\registry.json"),
    runtime_root_override=r"D:\AI OS\.loopx-runtime",
    scan_roots=[Path(r"D:\AI OS")],
    open_browser=False,
    verbose=True,
)

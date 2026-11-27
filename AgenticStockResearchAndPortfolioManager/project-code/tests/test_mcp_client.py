"""mcp_client: the server process must inherit the app's environment (OLLAMA_HOST, API keys named in settings)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mcp_client import McpServer  # noqa: E402

SERVER = '''
import os
from mcp.server.mcpserver import MCPServer
mcp = MCPServer("envcheck")

@mcp.tool()
def read_env(name: str) -> str:
    """Return one environment variable."""
    return os.environ.get(name, "<missing>")

if __name__ == "__main__":
    mcp.run("stdio")
'''


def test_server_process_inherits_the_apps_environment(monkeypatch, tmp_path):
    script = tmp_path / "mcp_envcheck.py"
    script.write_text(SERVER)
    monkeypatch.setenv("OLLAMA_HOST", "http://example.invalid:11434")
    with McpServer("envcheck", str(script)) as s:
        assert s.call("read_env", {"name": "OLLAMA_HOST"}) == "http://example.invalid:11434"

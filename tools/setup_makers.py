"""Gives the maker agents their tools: writes .mcp.json into each maker's working folder on this machine."""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SERVERS = {
    "foundry-deck": "foundry.tools.deck_server",
    "foundry-visual": "foundry.tools.graphic_server",
}


def main(agents_dir: str) -> None:
    for agent, module in SERVERS.items():
        folder = Path(agents_dir) / agent
        folder.mkdir(parents=True, exist_ok=True)
        config = {"mcpServers": {agent: {"command": "uv", "args": ["--directory", str(REPO), "run", "python", "-m", module]}}}
        (folder / ".mcp.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
        print(f"{agent}: {folder / '.mcp.json'}")


if __name__ == "__main__":
    main(sys.argv[1])

"""Gives the maker agents their tools: writes .mcp.json into each maker's working folder on this machine."""

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG_TOOL = "foundry.tools.log_server"
LOG_SERVER = "foundry-log"
# Each maker gets the tool that makes its files and the log tool. The brief agent and the reviewer get no tool, so the reviewer is handed its inputs in a message.
SERVERS = {
    "foundry-deck": ["foundry.tools.deck_server", LOG_TOOL],
    "foundry-visual": ["foundry.tools.graphic_server", LOG_TOOL],
}
# The databases the desk writes, with the names it uses when the environment names none.
DATABASES = {"FOUNDRY_LOG_DB": "foundry-log.db", "FOUNDRY_JOBS_DB": "foundry-jobs.db", "FOUNDRY_WORK_DB": "foundry-work.db"}


def _server(module: str) -> dict:
    server = {"command": "uv", "args": ["--directory", str(REPO), "run", "python", "-m", module]}
    if module == LOG_TOOL:
        # It starts from the repository folder, so a path relative to wherever this ran would point at nothing.
        server["env"] = {name: str(Path(os.environ.get(name) or default).resolve()) for name, default in DATABASES.items()}
    return server


def main(agents_dir: str) -> None:
    for agent, modules in SERVERS.items():
        folder = Path(agents_dir) / agent
        folder.mkdir(parents=True, exist_ok=True)
        config = {"mcpServers": {(LOG_SERVER if module == LOG_TOOL else agent): _server(module) for module in modules}}
        (folder / ".mcp.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
        print(f"{agent}: {folder / '.mcp.json'}")


if __name__ == "__main__":
    main(sys.argv[1])

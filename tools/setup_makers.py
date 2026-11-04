"""Gives the maker agents their tools: writes .mcp.json into each maker's working folder on this machine."""

import json
import os
import sys
from pathlib import Path

from foundry.tools.image_server import images_on

REPO = Path(__file__).resolve().parent.parent
LOG_TOOL = "foundry.tools.log_server"
DATA_TOOL = "foundry.tools.data_server"
DOC_TOOL = "foundry.tools.doc_server"
IMAGE_TOOL = "foundry.tools.image_server"
# The tools both makers share read what the desk writes, and the name each goes by in a maker's tool list. A maker's own tool goes by the maker's name.
SHARED = {LOG_TOOL: "foundry-log", DATA_TOOL: "foundry-data"}
NAMES = {**SHARED, DOC_TOOL: "foundry-doc", IMAGE_TOOL: "foundry-image"}
# Each maker gets the tool that makes its files, the data tool and the log tool. The deck maker also writes the copy. The brief agent and the reviewer get no tool, so the reviewer is handed its inputs in a message.
SERVERS = {
    "foundry-deck": ["foundry.tools.deck_server", DOC_TOOL, DATA_TOOL, LOG_TOOL],
    "foundry-visual": ["foundry.tools.graphic_server", DATA_TOOL, LOG_TOOL],
}
# The places the desk writes, with the names it uses when the environment names none: its databases, and the folder it keeps files sent as answers in.
DATABASES = {"FOUNDRY_LOG_DB": "foundry-log.db", "FOUNDRY_JOBS_DB": "foundry-jobs.db", "FOUNDRY_WORK_DB": "foundry-work.db", "FOUNDRY_INPUTS_DIR": "foundry-inputs"}
# What the picture tool needs from the environment, when there is one. Neither is a secret: the sign-in is the machine's own Google login.
IMAGE_SETTINGS = ("GOOGLE_CLOUD_PROJECT", "FOUNDRY_IMAGE_MODEL")


def _env(module: str, brand_dir: str) -> dict[str, str]:
    env = {}
    if module in SHARED:
        # Both read what the desk writes, and start from the repository folder, so a path relative to wherever this ran would point at nothing.
        env |= {name: str(Path(os.environ.get(name) or default).resolve()) for name, default in DATABASES.items()}
    if module in (DOC_TOOL, IMAGE_TOOL) and images_on():
        # The copy says no pictures were drawn unless it is told they can be.
        env["FOUNDRY_IMAGES"] = "on"
    if module == IMAGE_TOOL:
        env |= {name: os.environ[name] for name in IMAGE_SETTINGS if os.environ.get(name)}
    if brand_dir:
        # A client's own makers are pinned to its brand folder, so none of their tools open another client's kit, logo or picture.
        env["FOUNDRY_BRAND_DIR"] = brand_dir
    return env


def _server(module: str, brand_dir: str) -> dict:
    server = {"command": "uv", "args": ["--directory", str(REPO), "run", "python", "-m", module]}
    if env := _env(module, brand_dir):
        server["env"] = env
    return server


def main(agents_dir: str, ending: str = "", brand_dir: str = "") -> None:
    """With an ending, such as -phatakha, writes the folders of that client's own makers, whose names carry it. With none, the shared makers' folders."""
    for agent, modules in SERVERS.items():
        folder = Path(agents_dir) / f"{agent}{ending}"
        folder.mkdir(parents=True, exist_ok=True)
        modules = [*modules, IMAGE_TOOL] if images_on() else modules
        config = {"mcpServers": {NAMES.get(module, agent): _server(module, brand_dir) for module in modules}}
        (folder / ".mcp.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
        print(f"{folder.name}: {folder / '.mcp.json'}")


if __name__ == "__main__":
    main(*sys.argv[1:])

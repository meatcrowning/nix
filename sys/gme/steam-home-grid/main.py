"""Read host-local game metadata without putting the user's library in Nix."""
import json
from pathlib import Path
import decky


class Plugin:
    async def library_metadata(self):
        path = Path(decky.DECKY_USER_HOME) / '.local/share/games/library-details.json'
        try:
            data = json.loads(path.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

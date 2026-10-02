"""Read host-local game metadata without putting the user's library in Nix."""
import asyncio
import json
import os
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

    async def rom_import(self, action, request):
        if action not in ('systems', 'browse', 'search', 'prepare', 'record', 'finish'):
            raise ValueError('Unknown import action')
        home = Path(decky.DECKY_USER_HOME)
        executable = Path('/etc/profiles/per-user') / home.name / 'bin/games'
        env = {**os.environ, 'HOME': str(home), 'XDG_DATA_HOME': str(home / '.local/share'),
               'XDG_CONFIG_HOME': str(home / '.config'), 'XDG_CACHE_HOME': str(home / '.cache')}
        process = await asyncio.create_subprocess_exec(
            str(executable), 'rom', action, env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(json.dumps(request).encode()), 180)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            process.kill()
            await process.wait()
            raise
        try:
            result = json.loads(stdout)
        except ValueError:
            raise RuntimeError('ROM import failed; check the Games installation.') from None
        if process.returncode or 'error' in result:
            raise RuntimeError(result.get('error', 'ROM import failed'))
        return result

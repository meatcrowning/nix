"""Read-only discovery endpoints on Comfy's existing loopback listener."""
import asyncio
import os
from pathlib import Path
import sys
from aiohttp import web
import folder_paths
from server import PromptServer

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE), str(HERE.parent / 'pylib')]
from catalogue_index import CatalogueIndex

_index = CatalogueIndex(os.environ.get('PAINTER_MODELS', '/home/lam/models'),
                        folder_paths.get_output_directory(),
                        Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'painter' / 'server-thumbnails')


@PromptServer.instance.routes.get('/painter/catalogue/models')
async def models(request):
    return web.json_response(await asyncio.to_thread(_index.models, request.query.get('since', '')))


@PromptServer.instance.routes.get('/painter/catalogue/outputs')
async def outputs(request):
    return web.json_response(await asyncio.to_thread(_index.outputs, request.query.get('since', '')))


@PromptServer.instance.routes.get('/painter/catalogue/thumbnail')
async def thumbnail(request):
    try:
        path = await asyncio.to_thread(_index.thumbnail, request.query.get('path', ''), request.query.get('stamp', ''))
    except (OSError, ValueError):
        raise web.HTTPNotFound(text='Output unavailable or changed')
    return web.FileResponse(path, headers={'Cache-Control': 'private, max-age=86400'})


NODE_CLASS_MAPPINGS = {}

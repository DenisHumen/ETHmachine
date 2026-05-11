"""Files browser + download handlers."""
from __future__ import annotations

from aiohttp import web

from web.browsers import files as files_browser
from web.core.templating import render


def _path_segments(rel: str) -> list[dict]:
    """Build cumulative breadcrumb segments."""
    out = []
    if not rel:
        return out
    parts = rel.replace("\\", "/").strip("/").split("/")
    cum = ""
    for p in parts:
        cum = (cum + "/" + p).strip("/")
        out.append({"name": p, "cum": cum})
    return out


async def files_index(request: web.Request) -> web.Response:
    root = request.query.get("root", "result")
    if root not in files_browser.ROOTS:
        root = "result"
    rel = request.query.get("path", "") or ""
    try:
        listing = files_browser.list_dir(root, rel)
    except (PermissionError, ValueError):
        return web.HTTPFound("/files?root=result")
    except IsADirectoryError:
        return web.HTTPFound(f"/files?root={root}")
    return render(request, "files.html",
                  roots=list(files_browser.ROOTS.keys()),
                  active_root=root,
                  active_path=rel,
                  path_segments=_path_segments(rel),
                  entries=listing["entries"])


async def files_download(request: web.Request) -> web.StreamResponse:
    root = request.query.get("root", "")
    rel = request.query.get("path", "")
    try:
        target = files_browser.file_for_download(root, rel)
    except (PermissionError, ValueError):
        return web.Response(status=403, text="forbidden")
    except FileNotFoundError:
        return web.Response(status=404, text="not found")
    return web.FileResponse(target, headers={
        "Content-Disposition": f'attachment; filename="{target.name}"',
    })

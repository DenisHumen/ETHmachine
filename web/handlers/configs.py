"""Config editor handlers."""
from __future__ import annotations

from aiohttp import web

from web.core import auth
from web.browsers import configs as config_editor
from web.storage import database as db
from web.core.templating import render


async def configs_index(request: web.Request) -> web.Response:
    return render(request, "configs.html",
                  files=config_editor.list_config_files(),
                  recent_changes=[dict(r) for r in db.recent_config_changes(20)],
                  active_file=None)


async def configs_edit(request: web.Request) -> web.Response:
    rel = request.query.get("path", "")
    try:
        content = config_editor.read_config(rel)
    except (PermissionError, FileNotFoundError, ValueError) as e:
        return render(request, "configs.html",
                      files=config_editor.list_config_files(),
                      recent_changes=[dict(r) for r in db.recent_config_changes(20)],
                      active_file=None,
                      error=str(e))
    rel_norm = rel.replace("\\", "/")
    flag = next((f["restart_required"] for f in config_editor.list_config_files()
                 if f["rel"] == rel_norm), False)
    return render(request, "configs.html",
                  active_file=rel_norm,
                  content=content,
                  restart_required=flag,
                  message=request.query.get("msg"),
                  last_diff=request.query.get("diff", ""))


async def configs_save(request: web.Request) -> web.Response:
    user = request.get("user")
    sid = request.get("session_id")
    if not user or not sid:
        return web.Response(status=401)
    if user["role"] not in ("root", "admin"):
        return web.Response(status=403, text="forbidden (read-only role)")
    data = await request.post()
    if not auth.csrf_check(sid, data.get("csrf", "")):
        return web.Response(status=403, text="csrf")
    rel = (data.get("path") or "").strip()
    new_content = data.get("content")
    if new_content is None:
        return web.Response(status=400, text="missing content")
    # normalize Windows-style \r\n that browsers send
    new_content = str(new_content).replace("\r\n", "\n")
    try:
        result = config_editor.write_config(rel, new_content)
    except (PermissionError, FileNotFoundError, ValueError) as e:
        return render(request, "configs.html",
                      active_file=rel,
                      content=new_content,
                      restart_required=False,
                      error=str(e))
    if result["changed"]:
        db.record_config_change(int(user["id"]), rel, result["diff"],
                                 bool(result["restart_required"]))
        db.audit("config_save", target=rel, user_id=int(user["id"]),
                 metadata={"restart_required": result["restart_required"],
                           "old_size": result["old_size"],
                           "new_size": result["new_size"]})
    msg = "Сохранено" + (" — нужен перезапуск" if result["restart_required"] else "")
    # render directly with diff so user sees feedback without query-string size issues
    return render(request, "configs.html",
                  active_file=rel,
                  content=new_content,
                  restart_required=result["restart_required"],
                  message=msg,
                  last_diff=result["diff"] or "")

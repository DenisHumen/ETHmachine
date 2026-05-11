"""Database browser handlers."""
from __future__ import annotations

from aiohttp import web

from web.browsers import databases as db_browser
from web.core.templating import render


async def databases_index(request: web.Request) -> web.Response:
    return render(request, "databases.html",
                  databases=db_browser.list_databases(),
                  active_db=None, active_table=None)


async def database_view(request: web.Request) -> web.Response:
    name = request.match_info["db"]
    try:
        tables = db_browser.list_tables(name)
    except (FileNotFoundError, ValueError):
        return web.HTTPFound("/databases")
    return render(request, "databases.html",
                  databases=db_browser.list_databases(),
                  active_db=name, tables=tables, active_table=None)


async def table_view(request: web.Request) -> web.Response:
    name = request.match_info["db"]
    table = request.match_info["table"]
    try:
        info = db_browser.table_info(name, table)
    except (FileNotFoundError, ValueError):
        return web.HTTPFound(f"/databases/{name}")
    try:
        limit = int(request.query.get("limit", "100"))
    except ValueError:
        limit = 100
    try:
        offset = int(request.query.get("offset", "0"))
    except ValueError:
        offset = 0
    cols, rows = db_browser.fetch_rows(name, table, limit=limit, offset=offset)
    return render(request, "databases.html",
                  databases=db_browser.list_databases(),
                  active_db=name, active_table=table,
                  columns=cols, rows=rows,
                  count=info["count"], limit=limit, offset=offset)

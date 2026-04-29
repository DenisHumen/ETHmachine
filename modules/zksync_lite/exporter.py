"""Excel экспорт результатов проверки zkSync Lite."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from modules.simple_logger import logger
from modules.zksync_lite.database import get_all_results

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESULT_DIR = PROJECT_ROOT / "result" / "zksync_lite"


_HEADER_FILL = PatternFill("solid", fgColor="4F81BD")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_ALT_FILL = PatternFill("solid", fgColor="EAF1FB")


def _autosize(ws) -> None:
    for col_idx, col in enumerate(ws.columns, start=1):
        max_len = 0
        for cell in col:
            try:
                v = "" if cell.value is None else str(cell.value)
            except Exception:
                v = ""
            if len(v) > max_len:
                max_len = len(v)
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max_len + 2, 60)


def _write_summary(ws, rows: List[Dict[str, Any]]) -> None:
    headers = [
        "wallet_address", "account_name", "status",
        "is_active", "account_id", "account_type", "pubkey_hash", "nonce",
        "eth_balance", "tokens_count", "nfts_count",
        "all_tokens", "attempts", "completed_at", "error_message",
    ]
    ws.append(headers)
    for c in ws[1]:
        c.fill = _HEADER_FILL
        c.font = _HEADER_FONT
        c.alignment = Alignment(horizontal="center", vertical="center")

    for i, r in enumerate(rows, start=2):
        balances: Dict[str, Dict[str, Any]] = r.get("balances") or {}
        tokens_repr = "; ".join(
            f"{sym}={info.get('amount', '?')}" for sym, info in balances.items()
        )
        ws.append([
            r.get("wallet_address"),
            r.get("account_name") or "",
            r.get("status"),
            "yes" if r.get("is_active") else "no",
            r.get("account_id"),
            r.get("account_type") or "",
            r.get("pubkey_hash") or "",
            r.get("nonce"),
            r.get("eth_balance") or "",
            r.get("tokens_count") or 0,
            r.get("nfts_count") or 0,
            tokens_repr,
            r.get("attempts") or 0,
            r.get("completed_at") or "",
            r.get("error_message") or "",
        ])
        if i % 2 == 0:
            for c in ws[i]:
                c.fill = _ALT_FILL
    ws.freeze_panes = "A2"
    _autosize(ws)


def _write_tokens(ws, rows: List[Dict[str, Any]]) -> None:
    headers = ["wallet_address", "account_name", "symbol",
               "amount", "raw_amount", "decimals"]
    ws.append(headers)
    for c in ws[1]:
        c.fill = _HEADER_FILL
        c.font = _HEADER_FONT
        c.alignment = Alignment(horizontal="center", vertical="center")

    line_idx = 2
    for r in rows:
        balances: Dict[str, Dict[str, Any]] = r.get("balances") or {}
        if not balances:
            continue
        for sym, info in balances.items():
            ws.append([
                r.get("wallet_address"),
                r.get("account_name") or "",
                sym,
                info.get("amount"),
                info.get("raw"),
                info.get("decimals"),
            ])
            if line_idx % 2 == 0:
                for c in ws[line_idx]:
                    c.fill = _ALT_FILL
            line_idx += 1
    ws.freeze_panes = "A2"
    _autosize(ws)


def _write_nfts(ws, rows: List[Dict[str, Any]]) -> None:
    headers = ["wallet_address", "account_name", "nft_id",
               "symbol", "address", "creator_address", "content_hash"]
    ws.append(headers)
    for c in ws[1]:
        c.fill = _HEADER_FILL
        c.font = _HEADER_FONT
        c.alignment = Alignment(horizontal="center", vertical="center")

    line_idx = 2
    for r in rows:
        nfts: Dict[str, Dict[str, Any]] = r.get("nfts") or {}
        if not nfts:
            continue
        for nft_id, n in nfts.items():
            ws.append([
                r.get("wallet_address"),
                r.get("account_name") or "",
                nft_id,
                n.get("symbol") or "",
                n.get("address") or "",
                n.get("creator_address") or "",
                n.get("content_hash") or "",
            ])
            if line_idx % 2 == 0:
                for c in ws[line_idx]:
                    c.fill = _ALT_FILL
            line_idx += 1
    ws.freeze_panes = "A2"
    _autosize(ws)


def export_results_xlsx(target_path: Optional[Path] = None) -> Optional[Path]:
    rows = get_all_results()
    if not rows:
        logger.warning("zkSync Lite: нет данных для экспорта")
        return None

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    if target_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        target_path = RESULT_DIR / f"zksync_lite_{ts}.xlsx"

    wb = Workbook()
    ws_sum = wb.active
    ws_sum.title = "summary"
    _write_summary(ws_sum, rows)

    ws_tokens = wb.create_sheet("tokens")
    _write_tokens(ws_tokens, rows)

    ws_nfts = wb.create_sheet("nfts")
    _write_nfts(ws_nfts, rows)

    wb.save(str(target_path))
    return target_path


__all__ = ["export_results_xlsx", "RESULT_DIR"]

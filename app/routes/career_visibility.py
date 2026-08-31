"""Dashboard routes for career radar and resume visibility guard."""

import asyncio

from fastapi import APIRouter

from app.hh_mobile_transport import MobileAPIError
from app.instances import bot
from app.mobile_career import fetch_career_radar
from app.mobile_visibility import fetch_resume_visibility


router = APIRouter()


def _account(idx: int):
    return bot._get_apply_acc(idx) if idx >= 0 else None


@router.get("/api/account/{idx}/career_radar")
async def api_career_radar(idx: int):
    acc = _account(idx)
    if not acc:
        return {"ok": False, "error": "Аккаунт не найден"}
    try:
        return await asyncio.get_event_loop().run_in_executor(
            None, fetch_career_radar, acc)
    except MobileAPIError as exc:
        return {"ok": False, "error": f"HH API: {exc.status_code}"}


@router.get("/api/account/{idx}/resume_visibility")
async def api_resume_visibility(idx: int):
    acc = _account(idx)
    if not acc:
        return {"ok": False, "error": "Аккаунт не найден"}
    try:
        return await asyncio.get_event_loop().run_in_executor(
            None, fetch_resume_visibility, acc, acc.get("resume_hash", ""))
    except MobileAPIError as exc:
        return {"ok": False, "error": f"HH API: {exc.status_code}"}

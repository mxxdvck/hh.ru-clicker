"""Dashboard endpoints for HH's native server-side auto-response feature."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request

from app.instances import bot
from app import mobile_auto_response
from app.hh_mobile_transport import MobileAPIError


router = APIRouter()


def _account(idx: int) -> dict | None:
    return bot._get_apply_acc(idx)


def _error(exc: Exception) -> dict:
    if isinstance(exc, MobileAPIError):
        return {
            "ok": False,
            "error": f"HH API: HTTP {exc.status_code}",
            "http_status": exc.status_code,
        }
    return {"ok": False, "error": str(exc) or type(exc).__name__}


@router.get("/api/account/{idx}/auto_response")
async def api_auto_response_status(idx: int):
    acc = _account(idx)
    if not acc:
        return {"ok": False, "error": "Аккаунт не найден"}
    loop = asyncio.get_running_loop()
    try:
        rules = await loop.run_in_executor(None, mobile_auto_response.fetch_rules, acc)
        statistics = {}
        for rule in rules:
            rule_id = str(rule.get("auto_response_id") or rule.get("id") or "")
            if rule_id:
                statistics[rule_id] = await loop.run_in_executor(
                    None, mobile_auto_response.fetch_statistics, acc, rule_id,
                )
        return {"ok": True, "rules": rules, "statistics": statistics}
    except Exception as exc:
        return _error(exc)


@router.post("/api/account/{idx}/auto_response")
async def api_auto_response_create(idx: int, request: Request):
    acc = _account(idx)
    if not acc:
        return {"ok": False, "error": "Аккаунт не найден"}
    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "error": "Некорректный JSON"}
    if body.get("confirm") is not True:
        return {"ok": False, "error": "Требуется явное подтверждение"}
    resume_id = str(body.get("resume_id") or acc.get("resume_hash") or "").strip()
    try:
        result = await asyncio.get_running_loop().run_in_executor(
            None, mobile_auto_response.create_rule, acc, resume_id, body.get("filters"),
        )
        return {"ok": True, "rule": result}
    except Exception as exc:
        return _error(exc)


@router.put("/api/account/{idx}/auto_response/{rule_id}")
async def api_auto_response_update(idx: int, rule_id: str, request: Request):
    acc = _account(idx)
    if not acc:
        return {"ok": False, "error": "Аккаунт не найден"}
    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "error": "Некорректный JSON"}
    if body.get("confirm") is not True:
        return {"ok": False, "error": "Требуется явное подтверждение"}
    if not isinstance(body.get("enabled"), bool):
        return {"ok": False, "error": "Поле enabled обязательно"}
    resume_id = str(body.get("resume_id") or acc.get("resume_hash") or "").strip()

    def update():
        return mobile_auto_response.update_rule(
            acc, rule_id, resume_id, enabled=body["enabled"],
            filters=body.get("filters"),
        )

    try:
        result = await asyncio.get_running_loop().run_in_executor(None, update)
        return {"ok": True, "rule": result}
    except Exception as exc:
        return _error(exc)

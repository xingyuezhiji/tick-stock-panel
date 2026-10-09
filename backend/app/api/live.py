"""Live trading console API.

V1 exposes a manual trading console backed by paper trading only. QMT/PTrade
are visible as disabled broker adapters.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.strategy import live
from app.strategy import paper
from app.strategy.live_brokers import broker_summaries

router = APIRouter(prefix="/api/live", tags=["live"])


def _data_dir(request: Request) -> Path:
    return request.app.state.repo.store.data_dir


def _engine(request: Request):
    engine = getattr(request.app.state, "strategy_engine", None)
    if engine is None:
        raise HTTPException(status_code=404, detail="策略引擎未初始化")
    return engine


def _handle_value_error(e: ValueError) -> HTTPException:
    status_code = 404 if "unknown strategy" in str(e) else 400
    return HTTPException(status_code=status_code, detail=str(e))


class BuySelectedRequest(BaseModel):
    strategy_id: str
    symbols: list[str] = Field(default_factory=list)
    account: str = paper.DEFAULT_ACCOUNT_ID
    broker: str = "paper"
    as_of: date | None = None
    asset_type: str = "stock"
    timeframe: str = "1d"
    top_n: int | None = Field(default=None, ge=1)
    buffer_n: int | None = Field(default=None, ge=1)
    size_mode: Literal["fixed_amount"] = "fixed_amount"
    amount_per_symbol: float = Field(default=10000, gt=0)
    order_type: Literal["market", "next_open", "close"] = "next_open"


class SellOutOfBufferRequest(BaseModel):
    strategy_id: str
    symbols: list[str] = Field(default_factory=list)
    account: str = paper.DEFAULT_ACCOUNT_ID
    broker: str = "paper"
    as_of: date | None = None
    asset_type: str = "stock"
    timeframe: str = "1d"
    top_n: int | None = Field(default=None, ge=1)
    buffer_n: int | None = Field(default=None, ge=1)
    order_type: Literal["market", "next_open", "close"] = "next_open"


@router.get("/brokers")
def brokers():
    return {"brokers": broker_summaries()}


@router.get("/strategy-pool")
def strategy_pool(
    request: Request,
    strategy_id: str = Query(...),
    account: str = Query(paper.DEFAULT_ACCOUNT_ID),
    broker: str = Query("paper"),
    as_of: date | None = Query(None),
    asset_type: str = Query("stock"),
    timeframe: str = Query("1d"),
    top_n: int | None = Query(None, ge=1),
    buffer_n: int | None = Query(None, ge=1),
):
    # broker 当前只影响前端展示可用性; pool 构建仍可在禁用 broker 下只读预览。
    del broker
    try:
        return live.build_strategy_pool(
            request.app.state.repo,
            _engine(request),
            strategy_id=strategy_id,
            account_id=account,
            as_of=as_of,
            asset_type=asset_type,
            timeframe=timeframe,
            top_n=top_n,
            buffer_n=buffer_n,
        )
    except ValueError as e:
        raise _handle_value_error(e) from e


@router.post("/orders/buy-selected")
def buy_selected(request: Request, body: BuySelectedRequest):
    try:
        return live.buy_selected(
            _data_dir(request),
            request.app.state.repo,
            _engine(request),
            body.model_dump(),
        )
    except ValueError as e:
        raise _handle_value_error(e) from e


@router.post("/orders/sell-out-of-buffer")
def sell_out_of_buffer(request: Request, body: SellOutOfBufferRequest):
    try:
        return live.sell_out_of_buffer(
            _data_dir(request),
            request.app.state.repo,
            _engine(request),
            body.model_dump(),
        )
    except ValueError as e:
        raise _handle_value_error(e) from e

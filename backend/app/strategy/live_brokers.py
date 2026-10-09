"""Live trading broker boundary.

V1 deliberately routes executable orders to the existing paper trading ledger.
Real brokers are explicit disabled adapters until account binding and risk
controls are added.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Protocol

from app.strategy import paper

OrderSide = Literal["buy", "sell"]
OrderType = Literal["market", "next_open", "close"]


class LiveBroker(Protocol):
    id: str
    label: str
    enabled: bool

    def create_order(
        self,
        data_dir: Path,
        *,
        account_id: str,
        symbol: str,
        side: OrderSide,
        qty: int | None = None,
        amount: float | None = None,
        order_type: OrderType = "next_open",
        asset_type: str = "stock",
        ref_price: float | None = None,
    ) -> tuple[dict | None, str | None]:
        ...


class PaperBroker:
    id = "paper"
    label = "模拟盘"
    enabled = True

    def create_order(
        self,
        data_dir: Path,
        *,
        account_id: str,
        symbol: str,
        side: OrderSide,
        qty: int | None = None,
        amount: float | None = None,
        order_type: OrderType = "next_open",
        asset_type: str = "stock",
        ref_price: float | None = None,
    ) -> tuple[dict | None, str | None]:
        return paper.create_order(
            data_dir,
            symbol,
            side,
            account_id=account_id,
            qty=qty,
            amount=amount,
            order_type=order_type,
            asset_type=asset_type,
            ref_price=ref_price,
            source="live",
        )


class DisabledBroker:
    enabled = False

    def __init__(self, broker_id: str, label: str, message: str) -> None:
        self.id = broker_id
        self.label = label
        self.message = message

    def create_order(self, data_dir: Path, **kwargs) -> tuple[dict | None, str | None]:
        return None, self.message


BROKERS: dict[str, LiveBroker] = {
    "paper": PaperBroker(),
    "qmt": DisabledBroker("qmt", "QMT", "QMT broker 未配置，当前版本不会发送真实委托"),
    "ptrade": DisabledBroker("ptrade", "PTrade", "PTrade broker 未配置，当前版本不会发送真实委托"),
}


def broker_summaries() -> list[dict]:
    return [
        {"id": broker.id, "label": broker.label, "enabled": broker.enabled}
        for broker in BROKERS.values()
    ]


def get_broker(broker_id: str) -> LiveBroker:
    return BROKERS.get(broker_id) or BROKERS["paper"]

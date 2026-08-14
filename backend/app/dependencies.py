"""Shared FastAPI dependencies."""

from __future__ import annotations

from app.services.dal_gateway import DalGateway, get_gateway
from app.services.store import StoreProtocol, get_store


async def store_dependency() -> StoreProtocol:
    return get_store()


async def gateway_dependency() -> DalGateway:
    return get_gateway()

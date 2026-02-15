from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Callable
from urllib.request import Request, urlopen

from .models import utcnow
from .normalization import parse_timestamp

DEFAULT_INFO_URL = "https://api.hyperliquid.xyz/info"
DEFAULT_TIMEOUT_SECONDS = 12.0
DEFAULT_USER_AGENT = "news-agent/0.1 (+https://example.com/news-agent)"

PostJSON = Callable[[str, dict[str, Any], float], Any]


@dataclass(slots=True)
class HyperliquidPosition:
    wallet: str
    symbol: str
    side: str
    size: float
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    last_updated: datetime


@dataclass(slots=True)
class HyperliquidTrade:
    wallet: str
    trade_id: str
    symbol: str
    side: str
    size: float
    price: float
    fee: float
    timestamp: datetime
    entry_price: float
    exit_price: float
    realized_pnl: float
    cumulative_pnl: float


@dataclass(slots=True)
class WalletPerformance:
    wallet: str
    trade_count: int
    total_realized_pnl: float
    cumulative_fees: float
    win_rate: float
    latest_trade_time: datetime


@dataclass(slots=True)
class PositionHistoryRow:
    wallet: str
    timestamp: datetime
    trade_id: str
    symbol: str
    fill_side: str
    fill_size: float
    fill_price: float
    fee: float
    position_side: str
    position_size: float
    avg_entry_price: float
    realized_pnl: float
    cumulative_realized_pnl: float
    cumulative_fees: float


class HyperliquidInfoClient:
    def __init__(
        self,
        info_url: str = DEFAULT_INFO_URL,
        http_post_json: PostJSON | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.info_url = info_url
        self.http_post_json = http_post_json or _default_post_json
        self.timeout_seconds = timeout_seconds

    def user_fills(self, wallet: str, limit: int = 200) -> list[dict[str, Any]]:
        response = self._query({"type": "userFills", "user": wallet})
        fills = [item for item in _as_list(response) if isinstance(item, dict)]
        fills.sort(key=_fill_sort_key, reverse=True)
        return fills[: max(limit, 0)]

    def open_orders(self, wallet: str) -> list[dict[str, Any]]:
        response = self._query({"type": "openOrders", "user": wallet})
        return [item for item in _as_list(response) if isinstance(item, dict)]

    def frontend_open_orders(self, wallet: str) -> list[dict[str, Any]]:
        response = self._query({"type": "frontendOpenOrders", "user": wallet})
        return [item for item in _as_list(response) if isinstance(item, dict)]

    def clearinghouse_state(self, wallet: str) -> dict[str, Any]:
        response = self._query({"type": "clearinghouseState", "user": wallet})
        if isinstance(response, dict):
            return response
        return {}

    def _query(self, payload: dict[str, Any]) -> Any:
        try:
            return self.http_post_json(self.info_url, payload, self.timeout_seconds)
        except (OSError, ValueError):
            return []


def normalize_positions(wallet: str, state: dict[str, Any]) -> list[HyperliquidPosition]:
    positions_raw = state.get("assetPositions") or state.get("positions") or []
    positions: list[HyperliquidPosition] = []

    last_updated = _state_timestamp(state)
    for item in positions_raw:
        if not isinstance(item, dict):
            continue
        position = item.get("position", item)
        if not isinstance(position, dict):
            continue

        symbol = str(position.get("coin") or position.get("symbol") or position.get("asset") or "").upper()
        if not symbol:
            continue

        signed_size = _safe_float(position.get("szi"), position.get("size"), position.get("sz"), default=0.0)
        if signed_size == 0:
            continue

        entry_price = _safe_float(position.get("entryPx"), position.get("entry_price"), default=0.0)
        mark_price = _safe_float(
            position.get("markPx"),
            position.get("mark_price"),
            position.get("oraclePx"),
            default=0.0,
        )
        if mark_price == 0:
            position_value = _safe_float(position.get("positionValue"), default=0.0)
            if position_value > 0 and abs(signed_size) > 0:
                mark_price = position_value / abs(signed_size)

        unrealized = _safe_float(position.get("unrealizedPnl"), position.get("unrealized_pnl"), default=0.0)
        side = "long" if signed_size > 0 else "short"
        positions.append(
            HyperliquidPosition(
                wallet=wallet,
                symbol=symbol,
                side=side,
                size=abs(signed_size),
                entry_price=entry_price,
                mark_price=mark_price,
                unrealized_pnl=unrealized,
                last_updated=last_updated,
            )
        )

    return positions


def aggregate_trade_history(wallet: str, fills: list[dict[str, Any]]) -> tuple[list[HyperliquidTrade], WalletPerformance]:
    normalized = [_normalize_fill(wallet, fill) for fill in fills]
    normalized = [fill for fill in normalized if fill is not None]
    normalized.sort(key=lambda fill: fill.timestamp)

    states: dict[str, _PositionState] = {}
    trades: list[HyperliquidTrade] = []
    cumulative_pnl = 0.0
    realized_hits = 0

    for fill in normalized:
        state = states.setdefault(fill.symbol, _PositionState())
        realized, entry_price, exit_price = state.apply_fill(fill.side, fill.size, fill.price)
        realized -= fill.fee
        cumulative_pnl += realized
        if realized > 0:
            realized_hits += 1

        trades.append(
            HyperliquidTrade(
                wallet=wallet,
                trade_id=fill.trade_id,
                symbol=fill.symbol,
                side=fill.side,
                size=fill.size,
                price=fill.price,
                fee=fill.fee,
                timestamp=fill.timestamp,
                entry_price=entry_price,
                exit_price=exit_price,
                realized_pnl=realized,
                cumulative_pnl=cumulative_pnl,
            )
        )

    trade_count = len(trades)
    latest_trade_time = trades[-1].timestamp if trades else utcnow()
    total_realized = sum(trade.realized_pnl for trade in trades)
    total_fees = sum(trade.fee for trade in trades)
    win_rate = (realized_hits / trade_count) if trade_count else 0.0
    performance = WalletPerformance(
        wallet=wallet,
        trade_count=trade_count,
        total_realized_pnl=total_realized,
        cumulative_fees=total_fees,
        win_rate=win_rate,
        latest_trade_time=latest_trade_time,
    )
    return trades, performance


def reconstruct_position_history(wallet: str, fills: list[dict[str, Any]]) -> list[PositionHistoryRow]:
    normalized = [_normalize_fill(wallet, fill) for fill in fills]
    normalized = [fill for fill in normalized if fill is not None]
    normalized.sort(key=lambda fill: fill.timestamp)

    states: dict[str, _PositionState] = {}
    rows: list[PositionHistoryRow] = []
    cumulative_realized_pnl = 0.0
    cumulative_fees = 0.0

    for fill in normalized:
        state = states.setdefault(fill.symbol, _PositionState())
        realized, _, _ = state.apply_fill(fill.side, fill.size, fill.price)
        realized_after_fee = realized - fill.fee

        cumulative_realized_pnl += realized_after_fee
        cumulative_fees += fill.fee
        signed_size = state.signed_size

        if signed_size > 0:
            position_side = "long"
        elif signed_size < 0:
            position_side = "short"
        else:
            position_side = "flat"

        rows.append(
            PositionHistoryRow(
                wallet=wallet,
                timestamp=fill.timestamp,
                trade_id=fill.trade_id,
                symbol=fill.symbol,
                fill_side=fill.side,
                fill_size=fill.size,
                fill_price=fill.price,
                fee=fill.fee,
                position_side=position_side,
                position_size=abs(signed_size),
                avg_entry_price=state.average_entry,
                realized_pnl=realized_after_fee,
                cumulative_realized_pnl=cumulative_realized_pnl,
                cumulative_fees=cumulative_fees,
            )
        )

    return rows


def _default_post_json(url: str, payload: dict[str, Any], timeout_seconds: float) -> Any:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": DEFAULT_USER_AGENT,
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        response_bytes = response.read()
        encoding = response.headers.get_content_charset() or "utf-8"
    return json.loads(response_bytes.decode(encoding, errors="replace"))


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("fills", "orders", "data", "result"):
            data = value.get(key)
            if isinstance(data, list):
                return data
    return []


def _fill_sort_key(fill: dict[str, Any]) -> datetime:
    for key in ("time", "timestamp", "ts"):
        value = fill.get(key)
        if value is None:
            continue
        try:
            return parse_timestamp(value)
        except (TypeError, ValueError):
            continue
    return datetime.fromtimestamp(0, tz=timezone.utc)


def _state_timestamp(state: dict[str, Any]) -> datetime:
    for key in ("time", "timestamp", "lastUpdated", "updatedAt"):
        value = state.get(key)
        if value is None:
            continue
        try:
            return parse_timestamp(value)
        except (TypeError, ValueError):
            continue
    return utcnow()


def _safe_float(*values: Any, default: float = 0.0) -> float:
    for value in values:
        if value is None:
            continue
        try:
            return float(str(value))
        except (TypeError, ValueError):
            continue
    return default


@dataclass(slots=True)
class _NormalizedFill:
    trade_id: str
    symbol: str
    side: str
    size: float
    price: float
    fee: float
    timestamp: datetime


def _normalize_fill(wallet: str, fill: dict[str, Any]) -> _NormalizedFill | None:
    symbol = str(fill.get("coin") or fill.get("symbol") or fill.get("asset") or "").upper()
    if not symbol:
        return None

    trade_id = str(fill.get("tid") or fill.get("tradeId") or fill.get("hash") or fill.get("oid") or "")
    if not trade_id:
        trade_id = f"{wallet}:{symbol}:{fill.get('time') or fill.get('timestamp') or '0'}"

    side_raw = str(fill.get("side") or fill.get("dir") or "").lower()
    if "sell" in side_raw or "short" in side_raw:
        side = "sell"
    elif "buy" in side_raw or "long" in side_raw:
        side = "buy"
    else:
        size_guess = _safe_float(fill.get("sz"), fill.get("size"), fill.get("sizeDelta"), default=0.0)
        side = "buy" if size_guess >= 0 else "sell"

    size = abs(_safe_float(fill.get("sz"), fill.get("size"), fill.get("sizeDelta"), default=0.0))
    if size == 0:
        return None

    price = _safe_float(fill.get("px"), fill.get("price"), fill.get("avgPx"), default=0.0)
    if price <= 0:
        return None

    fee = abs(_safe_float(fill.get("fee"), fill.get("feePaid"), default=0.0))
    timestamp = _fill_sort_key(fill)
    return _NormalizedFill(
        trade_id=trade_id,
        symbol=symbol,
        side=side,
        size=size,
        price=price,
        fee=fee,
        timestamp=timestamp,
    )


@dataclass(slots=True)
class _PositionState:
    signed_size: float = 0.0
    average_entry: float = 0.0

    def apply_fill(self, side: str, size: float, price: float) -> tuple[float, float, float]:
        signed_change = size if side == "buy" else -size
        previous_size = self.signed_size
        previous_entry = self.average_entry

        realized = 0.0
        entry_price = previous_entry if previous_entry > 0 else price
        exit_price = 0.0

        if previous_size == 0 or (previous_size > 0 and signed_change > 0) or (previous_size < 0 and signed_change < 0):
            new_size = previous_size + signed_change
            if previous_size == 0:
                self.average_entry = price
            elif abs(new_size) > 0:
                weighted = (abs(previous_size) * previous_entry) + (abs(signed_change) * price)
                self.average_entry = weighted / abs(new_size)
            self.signed_size = new_size
            return realized, self.average_entry, exit_price

        closing_size = min(abs(previous_size), abs(signed_change))
        direction = 1.0 if previous_size > 0 else -1.0
        realized = closing_size * (price - previous_entry) * direction
        exit_price = price

        new_size = previous_size + signed_change
        if new_size == 0:
            self.signed_size = 0.0
            self.average_entry = 0.0
        elif (previous_size > 0 and new_size < 0) or (previous_size < 0 and new_size > 0):
            self.signed_size = new_size
            self.average_entry = price
            entry_price = price
        else:
            self.signed_size = new_size
            self.average_entry = previous_entry
        return realized, entry_price, exit_price

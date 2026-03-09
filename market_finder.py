"""
╔══════════════════════════════════════════════════════════════╗
║   POLYMARKET TELEGRAM BOT — MARKET FINDER v3.0              ║
╚══════════════════════════════════════════════════════════════╝
Finds BTC UP/DOWN markets + any custom Polymarket event.
Supports search, trending, and direct slug/ID lookup.
"""

import time
import math
import json
import requests
from dataclasses import dataclass, field
from typing import Optional
from config import GAMMA_API, CLOB_HOST, trading_config


# ── General Market (any Polymarket event) ────────────

@dataclass
class PolymarketEvent:
    """Any Polymarket event/market."""
    condition_id: str
    question: str
    slug: str
    outcomes: list[str]
    token_ids: list[str]
    prices: list[float]
    end_time: float
    active: bool
    accepting_orders: bool
    liquidity: float
    volume: float = 0.0
    category: str = ""
    image: str = ""

    @property
    def is_tradeable(self) -> bool:
        return self.active and self.accepting_orders

    @property
    def is_expired(self) -> bool:
        return self.end_time > 0 and time.time() > self.end_time

    @property
    def minutes_until_close(self) -> float:
        if self.end_time <= 0:
            return 999999
        return max(0, (self.end_time - time.time()) / 60)

    @property
    def outcome_summary(self) -> str:
        """e.g., 'Yes: $0.65 | No: $0.35'"""
        parts = []
        for i, outcome in enumerate(self.outcomes):
            price = self.prices[i] if i < len(self.prices) else 0
            parts.append(f"{outcome}: ${price:.2f}")
        return " | ".join(parts)

    def get_token_for_outcome(self, outcome_index: int) -> Optional[str]:
        if 0 <= outcome_index < len(self.token_ids):
            return self.token_ids[outcome_index]
        return None

    def get_price_for_outcome(self, outcome_index: int) -> float:
        if 0 <= outcome_index < len(self.prices):
            return self.prices[outcome_index]
        return 0.0


# ── BTC UP/DOWN Market ───────────────────────────────

@dataclass
class BTCMarket:
    """A Polymarket BTC UP/DOWN market."""
    condition_id: str
    question: str
    slug: str
    token_id_up: str
    token_id_down: str
    price_up: float
    price_down: float
    end_time: float
    active: bool
    accepting_orders: bool
    order_min_size: int
    liquidity: float
    timeframe: str = "15m"

    @property
    def minutes_until_close(self) -> float:
        return max(0, (self.end_time - time.time()) / 60)

    @property
    def is_tradeable(self) -> bool:
        return self.active and self.accepting_orders and not self.is_expired

    @property
    def is_expired(self) -> bool:
        return time.time() > self.end_time


class MarketFinder:
    """Finds BTC UP/DOWN markets + any custom Polymarket event."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})
        self._cache: dict[str, tuple[BTCMarket, float]] = {}
        self._cache_ttl: float = 30
        # Store currently selected custom market
        self.custom_market: Optional[PolymarketEvent] = None

    # ── General Market Discovery ─────────────────────

    def search_markets(self, query: str, limit: int = 8) -> list[PolymarketEvent]:
        """Search for any market on Polymarket using client-side keyword filter."""
        try:
            # Fetch a large pool of active markets sorted by liquidity
            all_markets = []
            for offset in [0, 100]:
                resp = self.session.get(
                    f"{GAMMA_API}/markets",
                    params={
                        "limit": 100,
                        "offset": offset,
                        "active": "true",
                        "closed": "false",
                        "order": "liquidityNum",
                        "ascending": "false",
                    },
                    timeout=15,
                )
                if resp.status_code != 200:
                    break
                batch = resp.json()
                if not isinstance(batch, list):
                    break
                all_markets.extend(batch)
                if len(batch) < 100:
                    break

            # Filter by keyword in question text
            query_lower = query.lower()
            keywords = query_lower.split()
            matching = []
            for data in all_markets:
                question = data.get("question", "").lower()
                slug = data.get("slug", "").lower()
                # All keywords must match
                if all(kw in question or kw in slug for kw in keywords):
                    event = self._parse_event(data)
                    if event and event.is_tradeable:
                        matching.append(event)

            return matching[:limit]
        except Exception as e:
            print(f"Search error: {e}")
            return []

    def get_trending_markets(self, limit: int = 8) -> list[PolymarketEvent]:
        """Get trending/popular markets."""
        try:
            resp = self.session.get(
                f"{GAMMA_API}/markets",
                params={
                    "limit": limit,
                    "active": "true",
                    "closed": "false",
                    "order": "liquidityNum",
                    "ascending": "false",
                },
                timeout=15,
            )
            if resp.status_code != 200:
                return []

            markets_data = resp.json()
            if not isinstance(markets_data, list):
                return []

            results = []
            for data in markets_data:
                event = self._parse_event(data)
                if event and event.is_tradeable:
                    results.append(event)
            return results[:limit]
        except Exception:
            return []

    def get_market_by_slug(self, slug: str) -> Optional[PolymarketEvent]:
        """Get a specific market by its slug."""
        try:
            resp = self.session.get(
                f"{GAMMA_API}/markets/slug/{slug}",
                timeout=10,
            )
            if resp.status_code != 200:
                return None

            text = resp.text.strip()
            if text == "null" or not text:
                return None

            data = resp.json()
            return self._parse_event(data)
        except Exception:
            return None

    def get_market_by_condition(self, condition_id: str) -> Optional[PolymarketEvent]:
        """Get a market by condition ID."""
        try:
            resp = self.session.get(
                f"{GAMMA_API}/markets",
                params={"condition_id": condition_id},
                timeout=10,
            )
            if resp.status_code != 200:
                return None

            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                return self._parse_event(data[0])
            elif isinstance(data, dict):
                return self._parse_event(data)
            return None
        except Exception:
            return None

    def _parse_event(self, data: dict) -> Optional[PolymarketEvent]:
        """Parse any Gamma API response into PolymarketEvent."""
        try:
            clob_ids_raw = data.get("clobTokenIds", "[]")
            if isinstance(clob_ids_raw, str):
                clob_ids = json.loads(clob_ids_raw)
            else:
                clob_ids = clob_ids_raw

            if not clob_ids:
                return None

            outcomes_raw = data.get("outcomes", '["Yes", "No"]')
            if isinstance(outcomes_raw, str):
                outcomes = json.loads(outcomes_raw)
            else:
                outcomes = outcomes_raw

            prices_raw = data.get("outcomePrices", '[]')
            if isinstance(prices_raw, str):
                prices_list = json.loads(prices_raw)
            else:
                prices_list = prices_raw
            prices = [float(p) for p in prices_list] if prices_list else []

            end_time = 0.0
            end_date_str = data.get("endDate", "")
            if end_date_str:
                from datetime import datetime, timezone
                try:
                    dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                    end_time = dt.timestamp()
                except Exception:
                    pass

            return PolymarketEvent(
                condition_id=data.get("conditionId", ""),
                question=data.get("question", "Unknown"),
                slug=data.get("slug", ""),
                outcomes=outcomes,
                token_ids=clob_ids,
                prices=prices,
                end_time=end_time,
                active=data.get("active", False),
                accepting_orders=data.get("acceptingOrders", False),
                liquidity=float(data.get("liquidityNum", 0)),
                volume=float(data.get("volumeNum", 0)),
                category=data.get("category", ""),
                image=data.get("image", ""),
            )
        except Exception:
            return None

    # ── BTC UP/DOWN Market Discovery ─────────────────

    def _get_boundaries(self, timeframe: str) -> list[int]:
        interval_sec = trading_config.get_interval_seconds(timeframe)
        now = time.time()
        current = math.floor(now / interval_sec) * interval_sec
        return [
            current - interval_sec,
            current,
            current + interval_sec,
            current + interval_sec * 2,
        ]

    def _parse_btc_market(self, data: dict, timeframe: str = "15m") -> Optional[BTCMarket]:
        try:
            clob_ids_raw = data.get("clobTokenIds", "[]")
            if isinstance(clob_ids_raw, str):
                clob_ids = json.loads(clob_ids_raw)
            else:
                clob_ids = clob_ids_raw

            if len(clob_ids) < 2:
                return None

            outcomes_raw = data.get("outcomes", '["Up", "Down"]')
            if isinstance(outcomes_raw, str):
                outcomes = json.loads(outcomes_raw)
            else:
                outcomes = outcomes_raw

            token_id_up = ""
            token_id_down = ""
            for i, outcome in enumerate(outcomes):
                if i >= len(clob_ids):
                    break
                if outcome.lower() in ("up", "yes"):
                    token_id_up = clob_ids[i]
                elif outcome.lower() in ("down", "no"):
                    token_id_down = clob_ids[i]

            if not token_id_up or not token_id_down:
                return None

            prices_raw = data.get("outcomePrices", '["0.5", "0.5"]')
            if isinstance(prices_raw, str):
                prices = json.loads(prices_raw)
            else:
                prices = prices_raw

            price_up = float(prices[0]) if len(prices) > 0 else 0.5
            price_down = float(prices[1]) if len(prices) > 1 else 0.5

            end_date_str = data.get("endDate", "")
            end_time = 0.0
            if end_date_str:
                from datetime import datetime, timezone
                try:
                    dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                    end_time = dt.timestamp()
                except Exception:
                    pass

            if end_time == 0.0:
                slug = data.get("slug", "")
                parts = slug.split("-")
                for p in parts:
                    if p.isdigit() and len(p) >= 10:
                        interval_sec = trading_config.get_interval_seconds(timeframe)
                        end_time = float(p) + interval_sec
                        break

            return BTCMarket(
                condition_id=data.get("conditionId", ""),
                question=data.get("question", "BTC UP/DOWN"),
                slug=data.get("slug", ""),
                token_id_up=token_id_up,
                token_id_down=token_id_down,
                price_up=price_up,
                price_down=price_down,
                end_time=end_time,
                active=data.get("active", False),
                accepting_orders=data.get("acceptingOrders", False),
                order_min_size=data.get("orderMinSize", 5),
                liquidity=float(data.get("liquidityNum", 0)),
                timeframe=timeframe,
            )
        except Exception:
            return None

    def find_market_for_timeframe(self, timeframe: str) -> Optional[BTCMarket]:
        cache_key = timeframe
        if cache_key in self._cache:
            cached_market, cached_time = self._cache[cache_key]
            if (time.time() - cached_time) < self._cache_ttl and cached_market.is_tradeable:
                return cached_market

        slug_prefix = trading_config.get_market_slug_prefix(timeframe)
        boundaries = self._get_boundaries(timeframe)
        best_market = None
        now = time.time()

        for epoch in boundaries:
            slug = f"{slug_prefix}-{int(epoch)}"
            try:
                resp = self.session.get(
                    f"{GAMMA_API}/markets/slug/{slug}",
                    timeout=10,
                )
                if resp.status_code != 200:
                    continue
                text = resp.text.strip()
                if text == "null" or not text:
                    continue
                data = resp.json()
                market = self._parse_btc_market(data, timeframe)
                if market and market.is_tradeable and market.end_time > now:
                    if best_market is None or market.end_time < best_market.end_time:
                        best_market = market
            except Exception:
                continue

        if best_market:
            self._cache[cache_key] = (best_market, time.time())
        return best_market

    def find_current_market(self) -> Optional[BTCMarket]:
        for tf in trading_config.market_timeframes:
            market = self.find_market_for_timeframe(tf)
            if market:
                return market
        return None

    def find_all_markets(self) -> dict[str, Optional[BTCMarket]]:
        result = {}
        for tf in trading_config.market_timeframes:
            result[tf] = self.find_market_for_timeframe(tf)
        return result

    # ── Live Prices ──────────────────────────────────

    def get_live_price(self, token_id: str) -> Optional[float]:
        try:
            resp = self.session.get(
                f"{CLOB_HOST}/midpoint",
                params={"token_id": token_id},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                mid = data.get("mid")
                if mid:
                    return float(mid)
        except Exception:
            pass
        return None

    def refresh_market_prices(self, market: BTCMarket) -> BTCMarket:
        up_price = self.get_live_price(market.token_id_up)
        down_price = self.get_live_price(market.token_id_down)
        if up_price is not None:
            market.price_up = up_price
        if down_price is not None:
            market.price_down = down_price
        return market

    def refresh_event_prices(self, event: PolymarketEvent) -> PolymarketEvent:
        """Refresh live prices for a custom market event."""
        for i, token_id in enumerate(event.token_ids):
            price = self.get_live_price(token_id)
            if price is not None and i < len(event.prices):
                event.prices[i] = price
        return event

"""
╔══════════════════════════════════════════════════════════════╗
║   POLYMARKET TELEGRAM BOT — MARKET FINDER                   ║
╚══════════════════════════════════════════════════════════════╝
Finds and manages BTC UP/DOWN markets on Polymarket
using the Gamma API. Supports multiple timeframes.
"""

import time
import math
import json
import requests
from dataclasses import dataclass
from typing import Optional
from config import GAMMA_API, CLOB_HOST, trading_config


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
    """Finds BTC UP/DOWN markets on Polymarket across multiple timeframes."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})
        self._cache: dict[str, tuple[BTCMarket, float]] = {}
        self._cache_ttl: float = 30

    def _get_boundaries(self, timeframe: str) -> list[int]:
        """Get epoch timestamps for interval boundaries."""
        interval_sec = trading_config.get_interval_seconds(timeframe)
        now = time.time()
        current = math.floor(now / interval_sec) * interval_sec
        return [
            current - interval_sec,
            current,
            current + interval_sec,
            current + interval_sec * 2,
        ]

    def _parse_market(self, data: dict, timeframe: str = "15m") -> Optional[BTCMarket]:
        """Parse a Gamma API market response into BTCMarket."""
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
        """Find the current active BTC market for a specific timeframe."""
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
                market = self._parse_market(data, timeframe)

                if market and market.is_tradeable and market.end_time > now:
                    if best_market is None or market.end_time < best_market.end_time:
                        best_market = market
            except Exception:
                continue

        if best_market:
            self._cache[cache_key] = (best_market, time.time())

        return best_market

    def find_current_market(self) -> Optional[BTCMarket]:
        """Find the best market across all configured timeframes."""
        for tf in trading_config.market_timeframes:
            market = self.find_market_for_timeframe(tf)
            if market:
                return market
        return None

    def find_all_markets(self) -> dict[str, Optional[BTCMarket]]:
        """Find markets for all configured timeframes."""
        result = {}
        for tf in trading_config.market_timeframes:
            result[tf] = self.find_market_for_timeframe(tf)
        return result

    def get_live_price(self, token_id: str) -> Optional[float]:
        """Get live midpoint price from CLOB."""
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
        """Refresh live prices for a market."""
        up_price = self.get_live_price(market.token_id_up)
        down_price = self.get_live_price(market.token_id_down)

        if up_price is not None:
            market.price_up = up_price
        if down_price is not None:
            market.price_down = down_price

        return market

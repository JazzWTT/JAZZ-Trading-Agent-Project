"""
JAZZ Trading United Nation - System Configuration
Defines parameters for all 5 agents, risk thresholds, API endpoints, and database settings.
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class MarketConfig:
    assets: List[str] = field(default_factory=lambda: ["BTC", "ETH", "SOL"])
    polymarket_clob_ws: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    polymarket_clob_rest: str = "https://clob.polymarket.com"
    binance_ws: str = "wss://stream.binance.com:9443/ws"
    coinbase_ws: str = "wss://ws-feed.exchange.coinbase.com"
    
    # Expiry Filters
    min_secs_remaining_drop: int = 30     # Hard drop if expiry <= 30s
    danger_zone_min_secs: int = 120       # Brain rejects if < 2 mins (120s)
    danger_zone_max_secs: int = 600       # Brain rejects if > 10 mins (600s)
    
    # Watchdog
    watchdog_stale_threshold_sec: float = 2.0  # > 2s triggers stale-feed warning


@dataclass
class StrategyConfig:
    momentum_window_sec: int = 60          # 60-second rolling momentum window
    spot_momentum_trigger_pct: float = 0.3 # Spot crypto move > 0.3%
    min_profit_threshold_pct: float = 3.5   # Delta >= 3.5% discrepancy (0.035)
    min_depth_top3_usdc: float = 500.0     # Top 3 levels must exceed $500 USDC
    max_spread_bps: float = 400.0          # Suppress signal if spread > 400 bps (~2c on 50c binary)


@dataclass
class RiskConfig:
    total_capital_usdc: float = 10000.0    # Default starting portfolio size
    max_position_exposure_pct: float = 2.0  # Max 2% per single short-term market ($200)
    daily_loss_circuit_breaker_pct: float = 5.0 # Halt if rolling 24h loss >= 5% ($500)
    max_spread_bps_shield: float = 400.0   # Shield blocks if spread > 400 bps
    discrepancy_tolerance_usdc: float = 0.001 # 0.001 USDC threshold for pipeline lock


@dataclass
class SystemConfig:
    market: MarketConfig = field(default_factory=MarketConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    db_path: str = "jazz_ledger.db"
    log_level: str = "INFO"


DEFAULT_CONFIG = SystemConfig()

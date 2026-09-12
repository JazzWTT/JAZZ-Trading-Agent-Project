"""
JAZZ Trading United Nation - Ledger Database
Immutable SQLite audit trail and analytics calculator for Agent 5 (The Ledger).
"""

import sqlite3
import time
import math
import logging
from typing import Optional, Tuple, List, Dict, Any
from core.models import ExecutionRecord, TradeRecord, PortfolioMetrics, DecisionOrder


class LedgerDB:
    def __init__(self, db_path: str = "portfolio_ledger.db"):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            cur = conn.cursor()
            
            # Executions audit table (Agent 3 & 5)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS executions (
                client_order_id TEXT PRIMARY KEY,
                signal_id TEXT,
                token_id TEXT,
                side TEXT,
                price REAL,
                size REAL,
                order_type TEXT,
                submission_timestamp REAL,
                network_hash TEXT,
                status TEXT,
                attempts INTEGER,
                latency_ms REAL,
                error TEXT
            )
            """)

            # Trade lifecycle and P&L table (Agent 5)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                trade_id TEXT PRIMARY KEY,
                token_id TEXT,
                entry_price REAL,
                exit_price REAL,
                shares REAL,
                duration_sec REAL,
                slippage REAL,
                net_pnl REAL,
                status TEXT,
                entry_time REAL,
                exit_time REAL
            )
            """)

            # Reconciliation audit logs (Agent 5)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS balance_audits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                exchange_balance REAL,
                internal_balance REAL,
                discrepancy REAL,
                discrepancy_flag INTEGER
            )
            """)

            # Metrics snapshots
            cur.execute("""
            CREATE TABLE IF NOT EXISTS metrics_snapshots (
                timestamp REAL PRIMARY KEY,
                cash_balance REAL,
                total_trades INTEGER,
                win_rate REAL,
                profit_factor REAL,
                avg_latency_ms REAL,
                max_drawdown_pct REAL
            )
            """)

            # Bot control & IPC table
            cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_control (
                id INTEGER PRIMARY KEY,
                status TEXT DEFAULT 'STOPPED',
                kill_switch INTEGER DEFAULT 0,
                max_position_pct REAL DEFAULT 2.0,
                daily_loss_limit_pct REAL DEFAULT 5.0,
                min_profit_threshold_pct REAL DEFAULT 3.5,
                max_spread_bps REAL DEFAULT 400.0,
                last_heartbeat REAL,
                htx_feed_status TEXT DEFAULT 'ONLINE',
                polymarket_latency_ms REAL DEFAULT 38.5,
                htx_spot_price REAL DEFAULT 77100.0,
                htx_velocity_60s REAL DEFAULT 0.0,
                eth_spot_price REAL DEFAULT 2460.0,
                eth_velocity_60s REAL DEFAULT 0.0,
                sol_spot_price REAL DEFAULT 100.0,
                sol_velocity_60s REAL DEFAULT 0.0,
                updated_at REAL
            )
            """)

            # Ensure columns exist if table was created earlier
            for col_sql in [
                "ALTER TABLE bot_control ADD COLUMN eth_spot_price REAL DEFAULT 2460.0",
                "ALTER TABLE bot_control ADD COLUMN eth_velocity_60s REAL DEFAULT 0.0",
                "ALTER TABLE bot_control ADD COLUMN sol_spot_price REAL DEFAULT 100.0",
                "ALTER TABLE bot_control ADD COLUMN sol_velocity_60s REAL DEFAULT 0.0",
                "ALTER TABLE bot_control ADD COLUMN telegram_bot_token TEXT DEFAULT ''",
                "ALTER TABLE bot_control ADD COLUMN telegram_chat_id TEXT DEFAULT ''",
                "ALTER TABLE bot_control ADD COLUMN telegram_enabled INTEGER DEFAULT 0",
                "ALTER TABLE bot_control ADD COLUMN ofi_btc REAL DEFAULT 0.0",
                "ALTER TABLE bot_control ADD COLUMN ofi_eth REAL DEFAULT 0.0",
                "ALTER TABLE bot_control ADD COLUMN ofi_sol REAL DEFAULT 0.0",
                "ALTER TABLE bot_control ADD COLUMN consensus_btc INTEGER DEFAULT 1",
                "ALTER TABLE bot_control ADD COLUMN consensus_eth INTEGER DEFAULT 1",
                "ALTER TABLE bot_control ADD COLUMN consensus_sol INTEGER DEFAULT 1"
            ]:
                try:
                    cur.execute(col_sql)
                except Exception:
                    pass

            cur.execute("""
            INSERT OR IGNORE INTO bot_control (
                id, status, kill_switch, max_position_pct, daily_loss_limit_pct,
                min_profit_threshold_pct, max_spread_bps, last_heartbeat,
                htx_feed_status, polymarket_latency_ms, htx_spot_price, htx_velocity_60s,
                eth_spot_price, eth_velocity_60s, sol_spot_price, sol_velocity_60s, updated_at
            ) VALUES (1, 'STOPPED', 0, 2.0, 5.0, 3.5, 400.0, ?, 'ONLINE', 38.5, 77100.0, 0.0, 2460.0, 0.0, 100.0, 0.0, ?)
            """, (time.time(), time.time()))

            # Live signals table
            cur.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id TEXT UNIQUE,
                timestamp REAL,
                asset_id TEXT,
                token_id TEXT,
                action TEXT,
                target_limit_price REAL,
                calculated_edge_bps REAL,
                max_size_shares REAL,
                theoretical_probability REAL,
                delta REAL,
                status TEXT DEFAULT 'APPROVED'
            )
            """)

            # System logs table
            cur.execute("""
            CREATE TABLE IF NOT EXISTS system_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                level TEXT,
                source TEXT,
                message TEXT
            )
            """)

            # Portfolio equity history snapshots for live line chart
            cur.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                equity_usdc REAL,
                cash_usdc REAL,
                open_exposure_usdc REAL,
                pnl_24h REAL
            )
            """)

            # Brier Score Calibration Tournament table
            cur.execute("""
            CREATE TABLE IF NOT EXISTS brier_calibration (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                asset_id TEXT,
                market_id TEXT,
                token_id TEXT,
                strike_price REAL,
                expiry_ts REAL,
                model_fair_prob REAL,
                market_mid_price REAL,
                actual_outcome INTEGER,
                brier_model REAL,
                brier_market REAL,
                status TEXT DEFAULT 'PENDING'
            )
            """)
            conn.commit()

    def log_execution(self, record: ExecutionRecord):
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
            INSERT OR REPLACE INTO executions (
                client_order_id, signal_id, token_id, side, price, size,
                order_type, submission_timestamp, network_hash, status,
                attempts, latency_ms, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.client_order_id, record.signal_id, record.token_id,
                record.side, record.price, record.size, record.order_type,
                record.submission_timestamp, record.network_hash, record.status,
                record.attempts, record.latency_ms, record.error
            ))
            conn.commit()

    def record_trade_entry(self, trade: TradeRecord):
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
            INSERT OR REPLACE INTO trades (
                trade_id, token_id, entry_price, exit_price, shares,
                duration_sec, slippage, net_pnl, status, entry_time, exit_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.trade_id, trade.token_id, trade.entry_price, trade.exit_price,
                trade.shares, trade.duration_sec, trade.slippage, trade.net_pnl,
                trade.status, trade.entry_time, trade.exit_time
            ))
            conn.commit()

    def record_trade_exit(self, trade_id: str, exit_price: float, exit_time: float, slippage: float = 0.001):
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT entry_price, shares, entry_time FROM trades WHERE trade_id = ?", (trade_id,))
            row = cur.fetchone()
            if not row:
                return None
            
            entry_price = row["entry_price"]
            shares = row["shares"]
            entry_time = row["entry_time"]
            
            duration_sec = exit_time - entry_time
            gross_pnl = (exit_price - entry_price) * shares
            # Slippage deduction
            net_pnl = gross_pnl - (slippage * shares)

            cur.execute("""
            UPDATE trades SET
                exit_price = ?,
                exit_time = ?,
                duration_sec = ?,
                slippage = ?,
                net_pnl = ?,
                status = 'SETTLED'
            WHERE trade_id = ?
            """, (exit_price, exit_time, duration_sec, slippage, net_pnl, trade_id))
            conn.commit()
            return net_pnl

    def audit_balance(self, exchange_balance: float, internal_balance: float, threshold: float = 0.001) -> Tuple[bool, float]:
        """
        Reconciles exchange balance with internal ledger.
        Returns (is_reconciled, discrepancy).
        Flags discrepancy if > threshold (0.001 USDC).
        """
        discrepancy = abs(exchange_balance - internal_balance)
        is_reconciled = discrepancy <= threshold
        
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
            INSERT INTO balance_audits (timestamp, exchange_balance, internal_balance, discrepancy, discrepancy_flag)
            VALUES (?, ?, ?, ?, ?)
            """, (time.time(), exchange_balance, internal_balance, discrepancy, 0 if is_reconciled else 1))
            conn.commit()
            
        return is_reconciled, discrepancy

    def get_portfolio_accounting(self, initial_capital: float = 10000.0) -> dict:
        """
        Computes mathematically sound portfolio accounting balances:
        - realized_pnl: sum of net_pnl from settled trades
        - realized_pnl_24h: sum of net_pnl from settled trades within last 24h
        - open_cost: total cash committed into currently open positions
        - cash_balance: initial_capital + realized_pnl - open_cost
        - total_equity: cash_balance + open_cost = initial_capital + realized_pnl
        - total_pnl: total_equity - initial_capital = realized_pnl
        - open_count: count of open positions
        """
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COALESCE(SUM(net_pnl), 0.0) FROM trades WHERE status = 'SETTLED'")
            realized_pnl = cur.fetchone()[0] or 0.0

            cur.execute("SELECT COALESCE(SUM(entry_price * shares), 0.0), COUNT(*) FROM trades WHERE status = 'OPEN'")
            row = cur.fetchone()
            open_cost = row[0] or 0.0
            open_count = row[1] or 0

            # 24H Realized PnL
            cutoff_24h = time.time() - 86400.0
            cur.execute("SELECT COALESCE(SUM(net_pnl), 0.0) FROM trades WHERE status = 'SETTLED' AND exit_time >= ?", (cutoff_24h,))
            realized_pnl_24h = cur.fetchone()[0] or 0.0

        cash_balance = initial_capital + realized_pnl - open_cost
        total_equity = cash_balance + open_cost
        pnl_total = total_equity - initial_capital

        return {
            "initial_capital": initial_capital,
            "realized_pnl": round(realized_pnl, 4),
            "realized_pnl_24h": round(realized_pnl_24h, 4),
            "open_cost": round(open_cost, 4),
            "cash_balance": round(cash_balance, 4),
            "total_equity": round(total_equity, 4),
            "total_pnl": round(pnl_total, 4),
            "pnl_pct": round((pnl_total / initial_capital) * 100.0, 2) if initial_capital > 0 else 0.0,
            "realized_pnl_pct": round((realized_pnl_24h / initial_capital) * 100.0, 2) if initial_capital > 0 else 0.0,
            "open_count": open_count
        }

    def reset_database(self, initial_capital: float = 10000.0):
        """Resets all trades, executions, and telemetry back to a clean initial slate."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM trades")
            cur.execute("DELETE FROM executions")
            cur.execute("DELETE FROM balance_audits")
            cur.execute("DELETE FROM metrics_snapshots")
            cur.execute("DELETE FROM portfolio_history")
            cur.execute("DELETE FROM signals")
            cur.execute("DELETE FROM system_logs")
            cur.execute("DELETE FROM brier_calibration")
            now = time.time()
            cur.execute("""
            INSERT INTO portfolio_history (timestamp, equity_usdc, cash_usdc, open_exposure_usdc, pnl_24h)
            VALUES (?, ?, ?, 0.0, 0.0)
            """, (now, initial_capital, initial_capital))
            conn.commit()

    def calculate_metrics(self, current_cash: Optional[float] = None, initial_capital: float = 10000.0) -> PortfolioMetrics:
        """
        Calculates Win Rate, Profit Factor, Average Execution Latency, and Drawdown.
        """
        if current_cash is None:
            acct = self.get_portfolio_accounting(initial_capital=initial_capital)
            current_cash = acct["cash_balance"]

        with self._get_conn() as conn:
            cur = conn.cursor()
            
            # Latency from executions
            cur.execute("SELECT latency_ms FROM executions WHERE status = 'POSTED' OR status = 'FILLED'")
            latencies = [row["latency_ms"] for row in cur.fetchall() if row["latency_ms"] > 0]
            avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

            # Closed trades
            cur.execute("SELECT net_pnl FROM trades WHERE status = 'SETTLED'")
            trades = [row["net_pnl"] for row in cur.fetchall()]
            
            # Active open positions
            cur.execute("SELECT COUNT(*) as count FROM trades WHERE status = 'OPEN'")
            active_positions = cur.fetchone()["count"]

            total_trades = len(trades)
            if total_trades == 0:
                return PortfolioMetrics(
                    cash_balance_usdc=round(current_cash, 4),
                    total_trades=0,
                    win_rate=0.0,
                    profit_factor=1.0,
                    avg_execution_latency_ms=round(avg_latency, 2),
                    max_drawdown_pct=0.0,
                    active_positions=active_positions
                )

            wins = [p for p in trades if p > 0]
            losses = [p for p in trades if p < 0]

            win_rate = (len(wins) / total_trades) * 100.0 if total_trades > 0 else 0.0
            gross_profits = sum(wins)
            gross_losses = abs(sum(losses))

            if gross_losses == 0:
                profit_factor = gross_profits if gross_profits > 0 else 1.0
            else:
                profit_factor = gross_profits / gross_losses

            # Drawdown calculation
            peak = initial_capital
            running = initial_capital
            max_dd = 0.0
            for pnl in trades:
                running += pnl
                if running > peak:
                    peak = running
                dd = (peak - running) / peak * 100.0
                if dd > max_dd:
                    max_dd = dd

            metrics = PortfolioMetrics(
                cash_balance_usdc=round(current_cash, 4),
                total_trades=total_trades,
                win_rate=round(win_rate, 2),
                profit_factor=round(profit_factor, 2),
                avg_execution_latency_ms=round(avg_latency, 2),
                max_drawdown_pct=round(max_dd, 2),
                active_positions=active_positions
            )

            # Store snapshot
            cur.execute("""
            INSERT OR REPLACE INTO metrics_snapshots (
                timestamp, cash_balance, total_trades, win_rate, profit_factor, avg_latency_ms, max_drawdown_pct
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                time.time(), metrics.cash_balance_usdc, metrics.total_trades,
                metrics.win_rate, metrics.profit_factor, metrics.avg_execution_latency_ms,
                metrics.max_drawdown_pct
            ))
            conn.commit()

            return metrics

    # =========================================================================
    # BOT CONTROL & IPC
    # =========================================================================
    def get_bot_control(self) -> dict:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM bot_control WHERE id = 1")
            row = cur.fetchone()
            if row:
                d = dict(row)
                d.setdefault("eth_spot_price", 2460.0)
                d.setdefault("eth_velocity_60s", 0.0)
                d.setdefault("sol_spot_price", 100.0)
                d.setdefault("sol_velocity_60s", 0.0)
                return d
            return {
                "id": 1,
                "status": "STOPPED",
                "kill_switch": 0,
                "max_position_pct": 2.0,
                "daily_loss_limit_pct": 5.0,
                "min_profit_threshold_pct": 3.5,
                "max_spread_bps": 400.0,
                "last_heartbeat": 0.0,
                "htx_feed_status": "ONLINE",
                "polymarket_latency_ms": 38.5,
                "htx_spot_price": 77100.0,
                "htx_velocity_60s": 0.0,
                "eth_spot_price": 2460.0,
                "eth_velocity_60s": 0.0,
                "sol_spot_price": 100.0,
                "sol_velocity_60s": 0.0,
                "telegram_bot_token": "",
                "telegram_chat_id": "",
                "telegram_enabled": 0,
                "ofi_btc": 0.0,
                "ofi_eth": 0.0,
                "ofi_sol": 0.0,
                "consensus_btc": 1,
                "consensus_eth": 1,
                "consensus_sol": 1,
                "updated_at": 0.0
            }

    def update_bot_control(self, **kwargs):
        if not kwargs:
            return
        fields = []
        values = []
        for k, v in kwargs.items():
            fields.append(f"{k} = ?")
            values.append(v)
        fields.append("updated_at = ?")
        values.append(time.time())
        values.append(1)  # WHERE id = 1

        sql = f"UPDATE bot_control SET {', '.join(fields)} WHERE id = ?"
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, values)
            conn.commit()

    # =========================================================================
    # SIGNALS
    # =========================================================================
    def record_signal(self, order: DecisionOrder, status: str = "APPROVED"):
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
            INSERT OR REPLACE INTO signals (
                signal_id, timestamp, asset_id, token_id, action,
                target_limit_price, calculated_edge_bps, max_size_shares,
                theoretical_probability, delta, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                order.signal_id, order.timestamp, order.asset_id, order.token_id,
                order.action, order.target_limit_price, order.calculated_edge_bps,
                order.max_size_shares, order.theoretical_probability, order.delta,
                status
            ))
            conn.commit()

    def get_recent_signals(self, limit: int = 50) -> List[dict]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM signals ORDER BY timestamp DESC LIMIT ?", (limit,))
            return [dict(r) for r in cur.fetchall()]

    # =========================================================================
    # SYSTEM LOGS
    # =========================================================================
    def record_log(self, level: str, source: str, message: str):
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
            INSERT INTO system_logs (timestamp, level, source, message)
            VALUES (?, ?, ?, ?)
            """, (time.time(), level.upper(), source, message))
            conn.commit()

    def get_recent_logs(self, limit: int = 150, level_filter: str = "ALL") -> List[dict]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            if level_filter.upper() == "ALL":
                cur.execute("SELECT * FROM system_logs ORDER BY timestamp DESC LIMIT ?", (limit,))
            else:
                cur.execute(
                    "SELECT * FROM system_logs WHERE level = ? ORDER BY timestamp DESC LIMIT ?",
                    (level_filter.upper(), limit)
                )
            return [dict(r) for r in cur.fetchall()]

    # =========================================================================
    # PORTFOLIO EQUITY HISTORY (LINE CHART)
    # =========================================================================
    def record_portfolio_snapshot(self, equity_usdc: float, cash_usdc: float, open_exposure_usdc: float, pnl_24h: float):
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
            INSERT INTO portfolio_history (timestamp, equity_usdc, cash_usdc, open_exposure_usdc, pnl_24h)
            VALUES (?, ?, ?, ?, ?)
            """, (time.time(), equity_usdc, cash_usdc, open_exposure_usdc, pnl_24h))
            conn.commit()

    def get_portfolio_history(self, limit: int = 200) -> List[dict]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM portfolio_history ORDER BY timestamp ASC LIMIT ?", (limit,))
            return [dict(r) for r in cur.fetchall()]

    # =========================================================================
    # POSITIONS & TRADES FOR TAB 3
    # =========================================================================
    def get_open_positions(self) -> List[dict]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM trades WHERE status = 'OPEN' ORDER BY entry_time DESC")
            return [dict(r) for r in cur.fetchall()]

    def get_settled_trades(self, limit: int = 100) -> List[dict]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM trades WHERE status = 'SETTLED' ORDER BY exit_time DESC LIMIT ?", (limit,))
            return [dict(r) for r in cur.fetchall()]

    # =========================================================================
    # BRIER SCORE CALIBRATION TOURNAMENT
    # =========================================================================
    def record_brier_prediction(
        self,
        asset_id: str,
        market_id: str,
        token_id: str,
        strike_price: float,
        expiry_ts: float,
        model_fair_prob: float,
        market_mid_price: float
    ):
        """Records an independent model forecast vs market quote at entry."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            # Throttle to avoid duplicate pending records for the same token in a short window
            cur.execute("""
            SELECT id FROM brier_calibration 
            WHERE token_id = ? AND status = 'PENDING' AND timestamp > ?
            """, (token_id, time.time() - 60.0))
            if cur.fetchone():
                return

            cur.execute("""
            INSERT INTO brier_calibration (
                timestamp, asset_id, market_id, token_id, strike_price,
                expiry_ts, model_fair_prob, market_mid_price, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
            """, (
                time.time(), asset_id, market_id, token_id, strike_price,
                expiry_ts, model_fair_prob, market_mid_price
            ))
            conn.commit()

    def resolve_expired_brier_predictions(
        self,
        current_spot_prices: Dict[str, float],
        now_ts: Optional[float] = None
    ) -> int:
        """
        Resolves pending predictions where expiry_ts <= now_ts.
        Calculates:
          actual_outcome = 1 if spot >= strike_price else 0
          brier_model = (model_fair_prob - actual_outcome)^2
          brier_market = (market_mid_price - actual_outcome)^2
        """
        now = now_ts or time.time()
        resolved_count = 0
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
            SELECT id, asset_id, strike_price, model_fair_prob, market_mid_price 
            FROM brier_calibration 
            WHERE status = 'PENDING' AND expiry_ts <= ?
            """, (now,))
            rows = cur.fetchall()

            for row in rows:
                row_id = row["id"]
                asset = row["asset_id"]
                strike = row["strike_price"]
                p_model = row["model_fair_prob"]
                p_mkt = row["market_mid_price"]
                spot = current_spot_prices.get(asset, 0.0)

                if spot <= 0 or strike <= 0:
                    continue

                outcome = 1 if spot >= strike else 0
                b_model = (p_model - outcome) ** 2
                b_mkt = (p_mkt - outcome) ** 2

                cur.execute("""
                UPDATE brier_calibration SET
                    actual_outcome = ?,
                    brier_model = ?,
                    brier_market = ?,
                    status = 'RESOLVED'
                WHERE id = ?
                """, (outcome, round(b_model, 6), round(b_mkt, 6), row_id))
                resolved_count += 1

            conn.commit()
        return resolved_count

    def get_brier_metrics(self, limit: int = 50) -> dict:
        """
        Computes overall Brier scores:
        Brier Score = 1/N * sum((forecast - outcome)^2)
        Lower is better!
        skill_delta = brier_market - brier_model (positive means model beat market)
        """
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
            SELECT COUNT(*), AVG(brier_model), AVG(brier_market)
            FROM brier_calibration
            WHERE status = 'RESOLVED'
            """)
            row = cur.fetchone()
            count = row[0] or 0
            avg_model = row[1] or 0.0
            avg_mkt = row[2] or 0.0

            cur.execute("""
            SELECT * FROM brier_calibration
            WHERE status = 'RESOLVED'
            ORDER BY expiry_ts DESC LIMIT ?
            """, (limit,))
            recent = [dict(r) for r in cur.fetchall()]

        # 2.5: Near-zero Brier on binary outcomes always indicates a bug (tautological validation)
        if count > 0 and avg_model < 0.01:
            raise ValueError(
                f"Invalid validation result: brier_model={avg_model:.6f} < 0.01. "
                "A near-zero Brier score on binary outcomes always indicates a bug (F5: predicting identical state), "
                "and must raise rather than display."
            )

        skill_delta = (avg_mkt - avg_model) if count > 0 else 0.0
        return {
            "total_evaluated": count,
            "brier_model": round(avg_model, 4),
            "brier_market": round(avg_mkt, 4),
            "skill_delta": round(skill_delta, 4),
            "has_statistical_edge": (skill_delta > 0.0 and count >= 10),
            "recent_evaluations": recent
        }


class SQLiteLogHandler(logging.Handler):
    """Logging handler that streams logs into the SQLite system_logs table."""
    def __init__(self, db: LedgerDB):
        super().__init__()
        self.db = db

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            self.db.record_log(
                level=record.levelname,
                source=record.name,
                message=msg
            )
        except Exception:
            pass

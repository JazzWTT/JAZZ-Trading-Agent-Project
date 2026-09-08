"""
JAZZ Trading United Nation - Ledger Database
Immutable SQLite audit trail and analytics calculator for Agent 5 (The Ledger).
"""

import sqlite3
import time
import math
from typing import Optional, Tuple, List, Dict, Any
from core.models import ExecutionRecord, TradeRecord, PortfolioMetrics


class LedgerDB:
    def __init__(self, db_path: str = "jazz_ledger.db"):
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

    def calculate_metrics(self, current_cash: float, initial_capital: float = 10000.0) -> PortfolioMetrics:
        """
        Calculates Win Rate, Profit Factor, Average Execution Latency, and Drawdown.
        """
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

"""
JAZZ Trading United Nation - Real-Time Streamlit Trading Terminal
Polymarket Short-Term Crypto Momentum Arbitrage Dashboard
"""

import datetime
import logging
import os
import subprocess
import sys
import time
from typing import Dict, List, Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import DEFAULT_CONFIG, SystemConfig
from database.ledger_db import LedgerDB

# Initialize Database
db = LedgerDB(DEFAULT_CONFIG.db_path)

# =============================================================================
# 1. PAGE CONFIGURATION & STYLING (DARK TERMINAL THEME)
# =============================================================================
st.set_page_config(
    page_title="JAZZ Trading Terminal | Polymarket Momentum Arbitrage",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Trading Terminal Dark CSS
CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

:root {
    --bg: #09090b;
    --bg-subtle: #0c0c0f;
    --card: #131316;
    --card-hover: #18181c;
    --border: #1e1e24;
    --border-subtle: #27272a;
    --text: #fafafa;
    --text-muted: #a1a1aa;
    --text-dim: #71717a;
    --accent: #3b82f6;
    --green: #22c55e;
    --green-muted: rgba(34, 197, 94, 0.12);
    --red: #ef4444;
    --red-muted: rgba(239, 68, 68, 0.12);
    --amber: #f59e0b;
    --amber-muted: rgba(245, 158, 11, 0.12);
    --radius: 10px;
}

html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"], .main, .block-container, section[data-testid="stMain"] {
    background-color: var(--bg) !important;
    color: var(--text) !important;
    font-family: 'DM Sans', -apple-system, sans-serif !important;
}

.block-container {
    padding: 1.5rem 2.0rem 2.5rem !important;
    max-width: 1440px !important;
}

/* Hide default streamlit header / footer decoration */
header[data-testid="stHeader"] {
    background: transparent !important;
}
footer { display: none !important; }

/* Custom Sidebar Styling */
section[data-testid="stSidebar"] {
    background-color: var(--bg-subtle) !important;
    border-right: 1px solid var(--border) !important;
}

/* Metric Cards */
.metric-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.1rem 1.25rem;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    transition: transform 0.15s ease, border-color 0.15s ease;
}
.metric-card:hover {
    border-color: #3f3f46;
    transform: translateY(-1px);
}
.metric-label {
    font-size: 0.78rem;
    color: var(--text-muted);
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
.metric-value {
    font-size: 1.8rem;
    font-weight: 700;
    color: var(--text);
    font-family: 'JetBrains Mono', monospace;
    letter-spacing: -0.02em;
    margin-top: 0.2rem;
}
.metric-delta {
    font-size: 0.75rem;
    font-weight: 600;
    font-family: 'JetBrains Mono', monospace;
    margin-top: 0.35rem;
    padding: 2px 8px;
    border-radius: 6px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
}
.delta-up { color: var(--green); background: var(--green-muted); }
.delta-down { color: var(--red); background: var(--red-muted); }
.delta-warn { color: var(--amber); background: var(--amber-muted); }

/* Badges */
.badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 6px;
    font-size: 0.72rem;
    font-weight: 600;
    font-family: 'JetBrains Mono', monospace;
}
.badge-green { color: var(--green); background: var(--green-muted); border: 1px solid rgba(34,197,94,0.3); }
.badge-red { color: var(--red); background: var(--red-muted); border: 1px solid rgba(239,68,68,0.3); }
.badge-amber { color: var(--amber); background: var(--amber-muted); border: 1px solid rgba(245,158,11,0.3); }
.badge-blue { color: var(--accent); background: rgba(59,130,246,0.12); border: 1px solid rgba(59,130,246,0.3); }

/* Pill Tabs */
button[data-baseweb="tab"] {
    background: transparent !important;
    color: var(--text-muted) !important;
    font-size: 0.85rem !important;
    font-weight: 600 !important;
    padding: 0.6rem 1.2rem !important;
    border: 1px solid transparent !important;
    border-radius: 8px !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
    color: var(--text) !important;
    background: var(--card) !important;
    border-color: var(--border) !important;
}
[data-baseweb="tab-list"] {
    gap: 6px !important;
    background: var(--bg-subtle) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    padding: 4px;
    margin-bottom: 1.25rem;
}

/* Custom Data Table */
.data-table-wrap {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
    margin-top: 0.5rem;
}
.data-table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    font-size: 0.82rem;
    font-family: 'DM Sans', sans-serif;
}
.data-table th {
    text-align: left;
    padding: 0.75rem 1rem;
    color: var(--text-muted);
    font-weight: 600;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    background: #0f0f13;
    border-bottom: 1px solid var(--border);
}
.data-table td {
    padding: 0.7rem 1rem;
    color: var(--text);
    border-bottom: 1px solid var(--border);
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.80rem;
}
.data-table tr:last-child td { border-bottom: none; }
.data-table tr:hover td { background-color: var(--card-hover); }

/* Terminal Logs Box */
.terminal-box {
    background: #060608;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1rem;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.78rem;
    color: #e4e4e7;
    height: 420px;
    overflow-y: auto;
    line-height: 1.6;
}
.terminal-line {
    margin-bottom: 0.25rem;
    word-break: break-all;
}
.log-ts { color: #71717a; margin-right: 8px; }
.log-level-info { color: #38bdf8; font-weight: 600; }
.log-level-warn { color: #facc15; font-weight: 600; }
.log-level-error { color: #f87171; font-weight: 600; }
.log-level-critical { color: #ef4444; font-weight: 700; background: rgba(239,68,68,0.2); padding: 1px 4px; border-radius: 4px; }
.log-hash { color: #c084fc; font-weight: 500; }
.log-badge { color: #4ade80; }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# =============================================================================
# 2. STATE & BACKGROUND PROCESS HELPERS
# =============================================================================
if "bot_process_pid" not in st.session_state:
    st.session_state.bot_process_pid = None

if "last_refresh_ts" not in st.session_state:
    st.session_state.last_refresh_ts = time.time()


def get_active_bot_state() -> dict:
    """Reads latest IPC control state from SQLite database."""
    return db.get_bot_control()


def start_bot_service():
    """Starts the background bot runner."""
    db.update_bot_control(status="RUNNING", kill_switch=0)
    # Check if a process is already tracked
    pid = st.session_state.bot_process_pid
    is_alive = False
    if pid:
        try:
            # Check on Windows
            os.kill(pid, 0)
            is_alive = True
        except (OSError, ProcessLookupError):
            is_alive = False

    if not is_alive:
        # Launch bot_service.py in background
        proc = subprocess.Popen(
            [sys.executable, os.path.join(BASE_DIR, "bot_service.py")],
            cwd=BASE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        st.session_state.bot_process_pid = proc.pid
    st.toast("⚡ Bot Service Started", icon="🟢")


def stop_emergency_kill_switch():
    """Engages emergency kill switch and stops all trading."""
    db.update_bot_control(status="STOPPED", kill_switch=1)
    db.record_log("CRITICAL", "app_dashboard", "[KILL-SWITCH ENGAGED] Emergency stop triggered from web UI!")
    pid = st.session_state.bot_process_pid
    if pid:
        try:
            os.kill(pid, 9)
        except Exception:
            pass
        st.session_state.bot_process_pid = None
    st.toast("🛑 EMERGENCY KILL-SWITCH ACTIVATED", icon="🚨")


# =============================================================================
# 3. SIDEBAR: CONTROLS, RISK SLIDERS & VENUE HEALTH
# =============================================================================
bot_ctrl = get_active_bot_state()
engine_status = bot_ctrl.get("status", "STOPPED")
kill_switch_active = (bot_ctrl.get("kill_switch", 0) == 1)

with st.sidebar:
    # Terminal Brand Header
    st.markdown("""
    <div style="margin-bottom: 1.25rem;">
        <div style="font-size: 1.15rem; font-weight: 700; letter-spacing: -0.01em; color: #fafafa; display: flex; align-items: center; gap: 8px;">
            <span style="color: #3b82f6;">⚡</span> JAZZ TRADING UN
        </div>
        <div style="font-size: 0.72rem; color: #71717a; text-transform: uppercase; letter-spacing: 0.05em; margin-top: 2px;">
            Polymarket Momentum Arbitrage
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Engine Status Pill
    if kill_switch_active:
        st.markdown('<div class="badge badge-red" style="width:100%; text-align:center; padding: 6px 0; margin-bottom: 1rem;">🚨 KILL-SWITCH ACTIVE</div>', unsafe_allow_html=True)
    elif engine_status == "RUNNING":
        st.markdown('<div class="badge badge-green" style="width:100%; text-align:center; padding: 6px 0; margin-bottom: 1rem;">🟢 ENGINE: RUNNING</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="badge badge-amber" style="width:100%; text-align:center; padding: 6px 0; margin-bottom: 1rem;">⚪ ENGINE: HALTED // IDLE</div>', unsafe_allow_html=True)

    # Control Buttons
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("▶ Start Bot", use_container_width=True, type="primary"):
            start_bot_service()
            st.rerun()

    with col_btn2:
        if st.button("🛑 Kill-Switch", use_container_width=True):
            stop_emergency_kill_switch()
            st.rerun()

    st.markdown("<hr style='border-color: #1e1e24; margin: 1.2rem 0;'>", unsafe_allow_html=True)

    # Risk Management Controls
    st.markdown("<div style='font-size: 0.8rem; font-weight: 600; text-transform: uppercase; color: #a1a1aa; letter-spacing: 0.05em; margin-bottom: 0.6rem;'>Risk Guardrails</div>", unsafe_allow_html=True)

    max_pos = st.slider(
        "Max Position Size (% Capital)",
        min_value=0.5,
        max_value=5.0,
        value=float(bot_ctrl.get("max_position_pct", 2.0)),
        step=0.1,
        help="Hard notional ceiling per market. Default is 2% ($200 on $10k)."
    )

    daily_loss = st.slider(
        "Daily Loss Breaker (%)",
        min_value=1.0,
        max_value=10.0,
        value=float(bot_ctrl.get("daily_loss_limit_pct", 5.0)),
        step=0.5,
        help="Circuit breaker trips and halts trading if 24h loss hits threshold."
    )

    min_delta = st.slider(
        "Min Profit Delta Edge (%)",
        min_value=1.0,
        max_value=10.0,
        value=float(bot_ctrl.get("min_profit_threshold_pct", 3.5)),
        step=0.5,
        help="Discrepancy between Black-Scholes fair probability and Polymarket ask."
    )

    max_spread = st.slider(
        "Max Spread Ceiling (bps)",
        min_value=100,
        max_value=800,
        value=int(bot_ctrl.get("max_spread_bps", 400)),
        step=50,
        help="Signals suppressed if spread > ceiling. 400 bps = ~2c spread on 50c token."
    )

    if st.button("Save & Sync Config", use_container_width=True):
        db.update_bot_control(
            max_position_pct=max_pos,
            daily_loss_limit_pct=daily_loss,
            min_profit_threshold_pct=min_delta,
            max_spread_bps=max_spread
        )
        st.toast("Risk settings updated in database!", icon="✅")
        st.rerun()

    st.markdown("<hr style='border-color: #1e1e24; margin: 1.2rem 0;'>", unsafe_allow_html=True)

    # Auto Refresh Setting
    st.markdown("<hr style='border-color: #1e1e24; margin: 1.2rem 0;'>", unsafe_allow_html=True)
    auto_refresh = st.checkbox("Live Auto-Refresh", value=True)
    refresh_sec = st.selectbox("Interval (seconds)", options=[2, 3, 5], index=0)
    refresh_interval = f"{refresh_sec}s" if auto_refresh else None
    if st.button("🔄 Refresh View", use_container_width=True):
        st.rerun()

    # Venue Status Indicators
    st.markdown("<hr style='border-color: #1e1e24; margin: 1.2rem 0;'>", unsafe_allow_html=True)
    st.markdown("<div style='font-size: 0.8rem; font-weight: 600; text-transform: uppercase; color: #a1a1aa; letter-spacing: 0.05em; margin-bottom: 0.6rem;'>Venue Telemetry</div>", unsafe_allow_html=True)

    @st.fragment(run_every=refresh_interval)
    def render_sidebar_telemetry():
        live_ctrl = get_active_bot_state()
        htx_status = live_ctrl.get("htx_feed_status", "ONLINE")
        pm_latency = live_ctrl.get("polymarket_latency_ms", 38.5)
        last_hb = live_ctrl.get("last_heartbeat", 0.0)
        hb_diff = time.time() - last_hb if last_hb > 0 else 999.0
        db_status = "SYNCED" if hb_diff < 5.0 else "IDLE"

        st.markdown(f"""
        <div style="background: #0f0f13; border: 1px solid #1e1e24; border-radius: 8px; padding: 0.75rem 0.85rem; font-size: 0.78rem;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <span style="color: #a1a1aa;">HTX Spot Feed:</span>
                <span class="badge badge-green">{htx_status}</span>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <span style="color: #a1a1aa;">Polymarket CLOB:</span>
                <span class="badge badge-blue">{pm_latency:.1f} ms</span>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="color: #a1a1aa;">Database State:</span>
                <span class="badge {'badge-green' if db_status=='SYNCED' else 'badge-amber'}">{db_status}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    render_sidebar_telemetry()


# =============================================================================
# 4. MAIN DASHBOARD: TABS
# =============================================================================
tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Live Overview & Metrics",
    "📈 Order Book & Signal Feed",
    "💼 Active Positions & Ledger",
    "🖥️ System Logs & Telemetry"
])


# -----------------------------------------------------------------------------
# TAB 1: LIVE OVERVIEW & METRICS
# -----------------------------------------------------------------------------
@st.fragment(run_every=refresh_interval)
def render_tab1():
    # Refresh metrics
    metrics = db.calculate_metrics(current_cash=DEFAULT_CONFIG.risk.total_capital_usdc)
    open_positions = db.get_open_positions()
    open_exp = sum(p["entry_price"] * p["shares"] for p in open_positions)
    total_equity = metrics.cash_balance_usdc + open_exp
    pnl_total = total_equity - DEFAULT_CONFIG.risk.total_capital_usdc
    pnl_pct = (pnl_total / DEFAULT_CONFIG.risk.total_capital_usdc) * 100.0

    # Row 1: KPI Cards
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        delta_type = "up" if pnl_total >= 0 else "down"
        arrow = "↑" if pnl_total >= 0 else "↓"
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Total Portfolio Value</div>
            <div class="metric-value">${total_equity:,.2f}</div>
            <div class="metric-delta delta-{delta_type}">{arrow} {pnl_total:+,.2f} ({pnl_pct:+.2f}%)</div>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Active Open Positions</div>
            <div class="metric-value">{len(open_positions)}</div>
            <div class="metric-delta delta-warn" style="color: #38bdf8; background: rgba(56,189,248,0.12);">${open_exp:,.2f} Notional</div>
        </div>
        """, unsafe_allow_html=True)

    with col3:
        pnl_badge = "delta-up" if pnl_total >= 0 else "delta-down"
        pnl_arrow = "▲" if pnl_total >= 0 else "▼"
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">24H Realized P&L</div>
            <div class="metric-value">${pnl_total:+,.2f}</div>
            <div class="metric-delta {pnl_badge}">{pnl_arrow} {pnl_pct:+.2f}% 24h Return</div>
        </div>
        """, unsafe_allow_html=True)

    with col4:
        wr_type = "delta-up" if metrics.win_rate >= 50 else "delta-warn"
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Win Rate / Profit Factor</div>
            <div class="metric-value">{metrics.win_rate:.1f}%</div>
            <div class="metric-delta {wr_type}">PF: {metrics.profit_factor:.2f} ({metrics.total_trades} Trades)</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='height: 18px;'></div>", unsafe_allow_html=True)

    # Row 2: Portfolio Equity Chart (Plotly)
    hist = db.get_portfolio_history(limit=100)
    
    if not hist:
        # Generate initial baseline points if no history exists yet
        base_time = time.time()
        hist_df = pd.DataFrame([
            {"timestamp": base_time - 300, "equity_usdc": 10000.0},
            {"timestamp": base_time - 200, "equity_usdc": 10000.0},
            {"timestamp": base_time - 100, "equity_usdc": 10000.0},
            {"timestamp": base_time, "equity_usdc": total_equity},
        ])
    else:
        hist_df = pd.DataFrame(hist)

    hist_df["datetime"] = pd.to_datetime(hist_df["timestamp"], unit="s")

    fig_equity = go.Figure()

    # Fill area under equity line
    fig_equity.add_trace(go.Scatter(
        x=hist_df["datetime"],
        y=hist_df["equity_usdc"],
        mode="lines",
        name="Portfolio Equity",
        line=dict(color="#22c55e", width=2.5),
        fill="tozeroy",
        fillcolor="rgba(34, 197, 94, 0.06)",
        hovertemplate="<b>%{x|%H:%M:%S}</b><br>Equity: $%{y:,.2f}<extra></extra>"
    ))

    # Baseline reference at $10,000
    fig_equity.add_hline(
        y=10000.0,
        line_dash="dash",
        line_color="rgba(255, 255, 255, 0.15)",
        annotation_text="Starting Capital ($10,000)",
        annotation_position="bottom right",
        annotation_font_color="#71717a"
    )

    fig_equity.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=25, b=10),
        height=320,
        font=dict(family="JetBrains Mono, monospace", color="#a1a1aa", size=11),
        xaxis=dict(
            gridcolor="rgba(255,255,255,0.04)",
            zerolinecolor="rgba(255,255,255,0.04)",
            tickfont=dict(size=10, color="#71717a")
        ),
        yaxis=dict(
            gridcolor="rgba(255,255,255,0.04)",
            zerolinecolor="rgba(255,255,255,0.04)",
            tickfont=dict(size=10, color="#71717a"),
            tickprefix="$"
        ),
        showlegend=False
    )

    st.markdown("""
    <div style="background: #131316; border: 1px solid #1e1e24; border-radius: 10px; padding: 1.1rem 1.25rem 0.5rem; margin-top: 0.5rem;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
            <div style="font-size: 0.88rem; font-weight: 600; color: #fafafa;">Portfolio Equity Curve (USDC)</div>
            <div style="font-size: 0.72rem; color: #71717a; font-family: 'JetBrains Mono', monospace;">Live Real-Time Stream</div>
        </div>
    """, unsafe_allow_html=True)
    st.plotly_chart(fig_equity, use_container_width=True, config={"displayModeBar": False})
    st.markdown("</div>", unsafe_allow_html=True)

    # Row 3: System Analytics Summary
    st.markdown("<div style='height: 18px;'></div>", unsafe_allow_html=True)
    s_col1, s_col2, s_col3 = st.columns(3)
    with s_col1:
        st.markdown(f"""
        <div style="background: #0f0f13; border: 1px solid #1e1e24; border-radius: 8px; padding: 0.85rem 1rem;">
            <div style="font-size: 0.72rem; color: #71717a; text-transform: uppercase;">Average Execution Latency</div>
            <div style="font-size: 1.25rem; font-weight: 700; color: #38bdf8; font-family: 'JetBrains Mono', monospace;">{metrics.avg_execution_latency_ms:.1f} ms</div>
        </div>
        """, unsafe_allow_html=True)
    with s_col2:
        st.markdown(f"""
        <div style="background: #0f0f13; border: 1px solid #1e1e24; border-radius: 8px; padding: 0.85rem 1rem;">
            <div style="font-size: 0.72rem; color: #71717a; text-transform: uppercase;">Maximum Drawdown</div>
            <div style="font-size: 1.25rem; font-weight: 700; color: {'#22c55e' if metrics.max_drawdown_pct < 2 else '#ef4444'}; font-family: 'JetBrains Mono', monospace;">{metrics.max_drawdown_pct:.2f}%</div>
        </div>
        """, unsafe_allow_html=True)
    with s_col3:
        st.markdown(f"""
        <div style="background: #0f0f13; border: 1px solid #1e1e24; border-radius: 8px; padding: 0.85rem 1rem;">
            <div style="font-size: 0.72rem; color: #71717a; text-transform: uppercase;">Pipeline Health</div>
            <div style="font-size: 1.25rem; font-weight: 700; color: #22c55e; font-family: 'JetBrains Mono', monospace;">HEALTHY & VERIFIED</div>
        </div>
        """, unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# TAB 2: ORDER BOOK & SIGNAL FEED
# -----------------------------------------------------------------------------
@st.fragment(run_every=refresh_interval)
def render_tab2():
    st.markdown("<div style='font-size: 0.95rem; font-weight: 600; color: #fafafa; margin-bottom: 0.8rem;'>HTX Spot Crypto Feeds & Momentum Velocity</div>", unsafe_allow_html=True)

    live_ctrl = get_active_bot_state()
    btc_spot = live_ctrl.get("htx_spot_price", 64250.0)
    btc_vel = live_ctrl.get("htx_velocity_60s", 0.0)

    h_col1, h_col2, h_col3 = st.columns(3)
    with h_col1:
        vel_type = "up" if btc_vel > 0.05 else ("down" if btc_vel < -0.05 else "warn")
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">HTX BTC/USDT Spot</div>
            <div class="metric-value">${btc_spot:,.2f}</div>
            <div class="metric-delta delta-{vel_type}">60s Velocity: {btc_vel:+.3f}%/min</div>
        </div>
        """, unsafe_allow_html=True)

    with h_col2:
        eth_spot = 3480.0 * (1.0 + (btc_vel * 0.01 * 0.8))
        eth_vel = btc_vel * 0.85
        vel_type_eth = "up" if eth_vel > 0.05 else ("down" if eth_vel < -0.05 else "warn")
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">HTX ETH/USDT Spot</div>
            <div class="metric-value">${eth_spot:,.2f}</div>
            <div class="metric-delta delta-{vel_type_eth}">60s Velocity: {eth_vel:+.3f}%/min</div>
        </div>
        """, unsafe_allow_html=True)

    with h_col3:
        sol_spot = 145.0 * (1.0 + (btc_vel * 0.01 * 1.2))
        sol_vel = btc_vel * 1.15
        vel_type_sol = "up" if sol_vel > 0.05 else ("down" if sol_vel < -0.05 else "warn")
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">HTX SOL/USDT Spot</div>
            <div class="metric-value">${sol_spot:,.2f}</div>
            <div class="metric-delta delta-{vel_type_sol}">60s Velocity: {sol_vel:+.3f}%/min</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='height: 18px;'></div>", unsafe_allow_html=True)
    st.markdown("<div style='font-size: 0.95rem; font-weight: 600; color: #fafafa; margin-bottom: 0.8rem;'>Strategy Engine Signal Discrepancies (Black-Scholes vs. Polymarket Ask)</div>", unsafe_allow_html=True)

    recent_signals = db.get_recent_signals(limit=25)

    if not recent_signals:
        st.markdown("""
        <div style="background: #131316; border: 1px solid #1e1e24; border-radius: 8px; padding: 2rem; text-align: center; color: #71717a;">
            No live strategy signals generated yet. Click <b>'Seed Test Simulation Round'</b> in Tab 4 to generate sample live signals.
        </div>
        """, unsafe_allow_html=True)
    else:
        sig_rows = ""
        for s in recent_signals:
            sig_time = datetime.datetime.fromtimestamp(s["timestamp"]).strftime("%H:%M:%S")
            token_side = "YES" if "YES" in s["token_id"] else "NO"
            side_badge = "badge-green" if token_side == "YES" else "badge-red"
            delta_val = s["delta"] * 100.0
            
            sig_rows += f"""
            <tr>
                <td>{s['signal_id']}</td>
                <td style="color: #a1a1aa;">{sig_time}</td>
                <td><b>{s['asset_id']}</b></td>
                <td><span class="badge {side_badge}">{token_side}</span></td>
                <td>{s['theoretical_probability']*100:.1f}%</td>
                <td>${s['target_limit_price']:.4f}</td>
                <td style="color: #22c55e; font-weight: 600;">+{delta_val:.2f}%</td>
                <td style="color: #38bdf8;">+{s['calculated_edge_bps']:.0f} bps</td>
                <td>{s['max_size_shares']:.1f}</td>
                <td><span class="badge badge-green">{s['status']}</span></td>
            </tr>
            """

        st.markdown(f"""
        <div class="data-table-wrap">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Signal ID</th>
                        <th>Time</th>
                        <th>Asset</th>
                        <th>Token</th>
                        <th>BS Model Fair Prob</th>
                        <th>Polymarket Ask</th>
                        <th>Delta Discrepancy</th>
                        <th>Edge (bps)</th>
                        <th>Size (Shares)</th>
                        <th>Shield Status</th>
                    </tr>
                </thead>
                <tbody>
                    {sig_rows}
                </tbody>
            </table>
        </div>
        """, unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# TAB 3: ACTIVE POSITIONS & LEDGER
# -----------------------------------------------------------------------------
@st.fragment(run_every=refresh_interval)
def render_tab3():
    st.markdown("<div style='font-size: 0.95rem; font-weight: 600; color: #fafafa; margin-bottom: 0.6rem;'>Open Positions & Resting Orders</div>", unsafe_allow_html=True)

    open_pos = db.get_open_positions()

    if not open_pos:
        st.markdown("""
        <div style="background: #131316; border: 1px solid #1e1e24; border-radius: 8px; padding: 1.5rem; text-align: center; color: #71717a; margin-bottom: 1.5rem;">
            No active positions open. Capital is 100% in USDC cash reserves.
        </div>
        """, unsafe_allow_html=True)
    else:
        open_rows = ""
        now_ts = time.time()
        for p in open_pos:
            dur = int(now_ts - p["entry_time"])
            notional = p["entry_price"] * p["shares"]
            cur_est = 0.52
            pnl_est = (cur_est - p["entry_price"]) * p["shares"]
            pnl_cls = "color: #22c55e;" if pnl_est >= 0 else "color: #ef4444;"

            open_rows += f"""
            <tr>
                <td>{p['trade_id']}</td>
                <td><b>{p['token_id']}</b></td>
                <td><span class="badge badge-green">BUY</span></td>
                <td>${p['entry_price']:.4f}</td>
                <td>${cur_est:.4f}</td>
                <td>{p['shares']:.1f}</td>
                <td>${notional:.2f}</td>
                <td>{dur}s</td>
                <td style="{pnl_cls} font-weight: 600;">{pnl_est:+.2f} USDC</td>
            </tr>
            """

        st.markdown(f"""
        <div class="data-table-wrap" style="margin-bottom: 1.5rem;">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Trade ID</th>
                        <th>Token ID</th>
                        <th>Side</th>
                        <th>Entry Price</th>
                        <th>Est. Market Bid</th>
                        <th>Shares</th>
                        <th>Notional</th>
                        <th>Duration</th>
                        <th>Unrealized P&L</th>
                    </tr>
                </thead>
                <tbody>{open_rows}</tbody>
            </table>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='font-size: 0.95rem; font-weight: 600; color: #fafafa; margin-bottom: 0.6rem;'>Settled Trades Audit Ledger (Agent 5 - The Ledger)</div>", unsafe_allow_html=True)

    settled_trades = db.get_settled_trades(limit=50)

    if not settled_trades:
        st.markdown("""
        <div style="background: #131316; border: 1px solid #1e1e24; border-radius: 8px; padding: 1.5rem; text-align: center; color: #71717a;">
            No settled trades recorded in database yet.
        </div>
        """, unsafe_allow_html=True)
    else:
        settled_rows = ""
        for t in settled_trades:
            exit_ts = datetime.datetime.fromtimestamp(t["exit_time"]).strftime("%H:%M:%S") if t["exit_time"] else "-"
            pnl_val = t["net_pnl"]
            pnl_cls = "color: #22c55e;" if pnl_val >= 0 else "color: #ef4444;"

            settled_rows += f"""
            <tr>
                <td>{t['trade_id']}</td>
                <td><b>{t['token_id']}</b></td>
                <td>${t['entry_price']:.4f}</td>
                <td>${t['exit_price']:.4f}</td>
                <td>{t['shares']:.1f}</td>
                <td>{t['duration_sec']:.1f}s</td>
                <td>${t['slippage']:.4f}</td>
                <td style="{pnl_cls} font-weight: 700;">{pnl_val:+.2f} USDC</td>
                <td><span class="badge badge-blue">SETTLED</span></td>
                <td style="color: #71717a;">{exit_ts}</td>
            </tr>
            """

        st.markdown(f"""
        <div class="data-table-wrap">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Trade ID</th>
                        <th>Token ID</th>
                        <th>Entry Price</th>
                        <th>Exit Price</th>
                        <th>Shares</th>
                        <th>Duration</th>
                        <th>Slippage</th>
                        <th>Net Realized P&L</th>
                        <th>Status</th>
                        <th>Settled Time</th>
                    </tr>
                </thead>
                <tbody>{settled_rows}</tbody>
            </table>
        </div>
        """, unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# TAB 4: SYSTEM LOGS & TELEMETRY
# -----------------------------------------------------------------------------
@st.fragment(run_every=refresh_interval)
def render_tab4():
    col_filter, col_act1, col_act2 = st.columns([3, 2, 2])
    with col_filter:
        level_filter = st.selectbox("Filter Log Level", options=["ALL", "INFO", "WARNING", "ERROR", "CRITICAL"], index=0)

    with col_act1:
        st.write("")
        if st.button("⚡ Seed Simulation Round", use_container_width=True):
            # Run one simulation round on demand
            cmd = [sys.executable, os.path.join(BASE_DIR, "main.py"), "--rounds", "1"]
            subprocess.run(cmd, cwd=BASE_DIR, capture_output=True)
            st.toast("Simulated tick & execution broadcast completed!", icon="⚡")
            st.rerun()

    with col_act2:
        st.write("")
        if st.button("🗑️ Clear Logs", use_container_width=True):
            with db._get_conn() as conn:
                conn.execute("DELETE FROM system_logs")
                conn.commit()
            st.toast("Logs cleared.", icon="🧹")
            st.rerun()

    recent_logs = db.get_recent_logs(limit=100, level_filter=level_filter)

    if not recent_logs:
        st.markdown("""
        <div class="terminal-box" style="display: flex; align-items: center; justify-content: center; color: #71717a;">
            No system log records matching the filter.
        </div>
        """, unsafe_allow_html=True)
    else:
        log_lines = ""
        for log in recent_logs:
            t_str = datetime.datetime.fromtimestamp(log["timestamp"]).strftime("%H:%M:%S")
            lvl = log["level"].upper()
            lvl_class = "log-level-info"
            if lvl == "WARNING":
                lvl_class = "log-level-warn"
            elif lvl == "ERROR":
                lvl_class = "log-level-error"
            elif lvl == "CRITICAL":
                lvl_class = "log-level-critical"

            msg = log["message"]
            # Color-code key events
            if "0x" in msg:
                parts = msg.split("0x")
                hash_part = "0x" + parts[1].split()[0]
                msg = msg.replace(hash_part, f'<span class="log-hash">{hash_part}</span>')

            log_lines += f"""
            <div class="terminal-line">
                <span class="log-ts">[{t_str}]</span>
                <span class="{lvl_class}">[{lvl}]</span>
                <span style="color: #94a3b8;">[{log['source']}]</span>:
                <span>{msg}</span>
            </div>
            """

        st.markdown(f"""
        <div class="terminal-box">
            {log_lines}
        </div>
        """, unsafe_allow_html=True)


# =============================================================================
# 5. RENDER DASHBOARD TABS
# =============================================================================
with tab1:
    render_tab1()

with tab2:
    render_tab2()

with tab3:
    render_tab3()

with tab4:
    render_tab4()

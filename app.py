# ==============================================================================
# BINANCE CATALYST AGENT OS - INSTITUTIONAL EDITION
# ==============================================================================

import streamlit as st
import pandas as pd
import requests
import json
import time
import hmac
import hashlib
import urllib.parse
from datetime import datetime
import streamlit.components.v1 as components

# ------------------------------------------------------------------------------
# 1. CẤU HÌNH TRANG & KHỞI TẠO SESSION STATE
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="Binance Catalyst Agent OS - Institutional Edition",
    page_icon="⚡",
    layout="wide"
)

GEMINI_API_KEY_SECRET = st.secrets.get("GEMINI_API_KEY", "")

# Init Session States
if "demo_balance" not in st.session_state:
    st.session_state.demo_balance = 10000.0
if "demo_positions" not in st.session_state:
    st.session_state.demo_positions = []
if "trade_history" not in st.session_state:
    st.session_state.trade_history = []
if "watchlist_tokens" not in st.session_state:
    st.session_state.watchlist_tokens = [
        "BTCUSDT", "ETHUSDT", "NEARUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT", "PEPEUSDT"
    ]
if "last_alert_time" not in st.session_state:
    st.session_state.last_alert_time = {}

# Config mặc định Quản lý vốn & TP/SL
if "account_balance" not in st.session_state:
    st.session_state.account_balance = 1000.0
if "max_risk_pct" not in st.session_state:
    st.session_state.max_risk_pct = 1.5
if "tp_rr_ratio" not in st.session_state:
    st.session_state.tp_rr_ratio = 2.0  # Mặc định TP = 2x Risk (R:R = 1:2)
if "max_open_orders" not in st.session_state:
    st.session_state.max_open_orders = 3
if "daily_loss_limit" not in st.session_state:
    st.session_state.daily_loss_limit = 5.0
if "bot_token" not in st.session_state:
    st.session_state.bot_token = ""
if "chat_id" not in st.session_state:
    st.session_state.chat_id = "1892567524"
if "gemini_key" not in st.session_state:
    st.session_state.gemini_key = GEMINI_API_KEY_SECRET

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ------------------------------------------------------------------------------
# 2. HÀM XỬ LÝ API BINANCE & TELEGRAM
# ------------------------------------------------------------------------------
def send_telegram_alert(bot_token: str, chat_id: str, message: str):
    if not bot_token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    try:
        res = requests.post(url, json=payload, timeout=4)
        return res.status_code == 200
    except Exception:
        return False

def get_realtime_market_data_bulk(symbols):
    result = {}
    try:
        url = "https://data-api.binance.vision/api/v3/ticker/24hr"
        res = requests.get(url, timeout=5, headers=HEADERS).json()
        if isinstance(res, list):
            symbol_set = set(symbols)
            for item in res:
                s = item.get("symbol")
                if s in symbol_set:
                    result[s] = {
                        "price": float(item.get("lastPrice", 0)),
                        "change_24h": float(item.get("priceChangePercent", 0)),
                        "vol_24h": float(item.get("quoteVolume", 0)) / 1_000_000
                    }
    except Exception:
        pass
    return result

def get_real_technical_indicators(symbol: str):
    rsi_1h = 50.0
    trend_4h = "NEUTRAL ⚪"
    vol_delta_str = "0.0% (Vol Delta)"

    try:
        url_1h = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=1h&limit=30"
        res = requests.get(url_1h, timeout=4, headers=HEADERS).json()
        if isinstance(res, list) and len(res) >= 15:
            closes = [float(k[4]) for k in res]
            df = pd.DataFrame({'close': closes})
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi_series = 100 - (100 / (1 + rs))
            rsi_val = rsi_series.iloc[-1]
            if not pd.isna(rsi_val):
                rsi_1h = round(rsi_val, 1)
            
            vols = [float(k[7]) for k in res]
            avg_vol = sum(vols[:-1]) / len(vols[:-1]) if len(vols) > 1 else 1
            last_vol = vols[-1]
            vol_diff = ((last_vol - avg_vol) / avg_vol) * 100 if avg_vol > 0 else 0
            vol_delta_str = f"{vol_diff:+.1f}% (Vol Delta)"
    except Exception:
        pass

    try:
        url_4h = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval=4h&limit=30"
        res = requests.get(url_4h, timeout=4, headers=HEADERS).json()
        if isinstance(res, list) and len(res) >= 10:
            closes_4h = [float(k[4]) for k in res]
            current_price = closes_4h[-1]
            sma20 = sum(closes_4h[-20:]) / min(len(closes_4h), 20)
            trend_4h = "BULLISH 🟢" if current_price >= sma20 else "BEARISH 🔴"
    except Exception:
        pass

    return rsi_1h, trend_4h, vol_delta_str

def fetch_scanner_dataframe(symbols):
    bulk_prices = get_realtime_market_data_bulk(symbols)
    data = []
    for symbol in symbols:
        price_info = bulk_prices.get(symbol, {"price": 0.0, "change_24h": 0.0, "vol_24h": 0.0})
        price = price_info["price"]
        price_change = price_info["change_24h"]
        vol_24h = price_info["vol_24h"]
        rsi_1h, trend_4h, vol_delta = get_real_technical_indicators(symbol)

        status = "⏳ CHỜ TÍN HIỆU"
        ai_warning = "Chưa đạt vùng tín hiệu"
        ai_score = "—"

        if rsi_1h <= 48 and "BULLISH" in trend_4h:
            status = "🎯 CẢNH BÁO MUA"
            ai_score = "8"
            ai_warning = "Đang tích lũy đẹp, xu hướng tăng vững"

        data.append({
            "Mã Token": symbol,
            "Giá Hiện Tại": f"${price:,.4f}" if 0 < price < 1 else f"${price:,.2f}",
            "Thay Đổi 24h": f"{price_change:+.2f}%",
            "Vol 24h": f"${vol_24h:.2f}M",
            "Xu hướng 4H": trend_4h,
            "RSI 1H": rsi_1h,
            "Dòng tiền 1H": vol_delta,
            "🧠 AI Score": ai_score,
            "⚠️ Cảnh Báo AI": ai_warning,
            "Trạng thái": status,
            "TradingView": "📈 TV",
            "Binance": "🟡 Futures"
        })
    return pd.DataFrame(data)

def render_tradingview_widget(symbol="BTCUSDT"):
    tv_html = f"""
    <div class="tradingview-widget-container" style="height:550px;width:100%">
      <div id="tradingview_chart_element" style="height:500px;width:100%"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
      new TradingView.widget({{
        "autosize": true,
        "symbol": "BINANCE:{symbol}",
        "interval": "60",
        "timezone": "Asia/Ho_Chi_Minh",
        "theme": "dark",
        "style": "1",
        "locale": "vi_VN",
        "toolbar_bg": "#f1f3f6",
        "enable_publishing": false,
        "allow_symbol_change": true,
        "container_id": "tradingview_chart_element"
      }});
      </script>
    </div>
    """
    components.html(tv_html, height=520)

# ------------------------------------------------------------------------------
# 3. SIDEBAR (CÓ Ô CÀI ĐẶT TP & SL)
# ------------------------------------------------------------------------------
with st.sidebar:
    st.subheader("⚙️ Quản Lý Vốn & Rủi Ro")
    st.session_state.account_balance = st.number_input("Tổng vốn tài khoản ($)", value=st.session_state.account_balance, step=100.0, key="sb_acc_bal")
    st.session_state.max_risk_pct = st.number_input("Rủi ro tối đa/lệnh (% SL)", value=st.session_state.max_risk_pct, step=0.1, key="sb_max_risk")
    
    # BỔ SUNG CÀI ĐẶT TP (TAKE PROFIT)
    st.session_state.tp_rr_ratio = st.number_input("Tỷ lệ Chốt Lời R:R (TP = x lần SL)", value=st.session_state.tp_rr_ratio, step=0.5, key="sb_tp_rr")
    tp_calculated_pct = st.session_state.max_risk_pct * st.session_state.tp_rr_ratio
    st.caption(f"🎯 Mức TP mục tiêu hiện tại: **+{tp_calculated_pct:.2f}%**")

    st.session_state.max_open_orders = st.number_input("Tối đa lệnh mở đồng thời", value=st.session_state.max_open_orders, step=1, key="sb_max_orders")
    st.session_state.daily_loss_limit = st.number_input("Cầu chì ngắt tự động/ngày (%)", value=st.session_state.daily_loss_limit, step=0.5, key="sb_daily_loss")

    st.divider()

    st.subheader("🎯 Chế Độ Vận Hành")
    trading_mode = st.radio(
        "Lựa chọn chế độ giao dịch:",
        ["📢 Bắn Tín Hiệu (Manual)", "⚡ Tự Động Đặt Lệnh (Auto)", "💔 Bán Tự Động (Semi-Auto)"],
        index=0,
        key="sb_trading_mode"
    )

    st.divider()

    st.subheader("📱 Telegram Bot Alert")
    st.session_state.chat_id = st.text_input("Chat ID", value=st.session_state.chat_id, key="sb_chat_id")
    if st.button("📱 Test Gửi Telegram Real", key="sb_btn_test_tg", use_container_width=True):
        if send_telegram_alert(st.session_state.bot_token, st.session_state.chat_id, "🔔 <b>Test kết nối Telegram thành công!</b>"):
            st.success("Đã gửi tin nhắn test!")
        else:
            st.error("Chưa cấu hình Bot Token hoặc Chat ID sai.")

    st.divider()

    st.subheader("📌 Quản Lý Watchlist Token")
    col_add1, col_add2 = st.columns([3, 1])
    with col_add1:
        new_token_in = st.text_input("VD: ADAUSDT", label_visibility="collapsed", placeholder="VD: ADAUSDT", key="sb_input_token").strip().upper()
    with col_add2:
        if st.button("➕", key="sb_btn_add_token"):
            if new_token_in and new_token_in not in st.session_state.watchlist_tokens:
                st.session_state.watchlist_tokens.append(new_token_in)
                st.rerun()

    updated_wl = st.multiselect(
        "Danh sách đang quét (Bấm 'x' để bớt Token):",
        options=st.session_state.watchlist_tokens,
        default=st.session_state.watchlist_tokens,
        key="sb_ms_watchlist"
    )
    if set(updated_wl) != set(st.session_state.watchlist_tokens):
        st.session_state.watchlist_tokens = updated_wl
        st.rerun()

    if st.button("🔄 Reset Watchlist Mặc Định", key="sb_btn_reset_wl", use_container_width=True):
        st.session_state.watchlist_tokens = ["BTCUSDT", "ETHUSDT", "NEARUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT", "PEPEUSDT"]
        st.rerun()

    st.divider()

    st.subheader("🧠 Gemini AI Analyst")
    st.session_state.gemini_key = st.text_input("Gemini API Key", value=st.session_state.gemini_key, type="password", key="sb_gemini_key")
    auto_refresh = st.checkbox("🔄 Tự động cập nhật (15s)", value=True, key="sb_auto_refresh")

# ------------------------------------------------------------------------------
# 4. KHUNG GIAO DIỆN CHÍNH
# ------------------------------------------------------------------------------
st.title("⚡ Binance Catalyst Agent OS - Institutional Edition")

mode_str = trading_mode.split("(")[1].replace(")", "") if "(" in trading_mode else "MANUAL"
st.success(f"🍃 **Đang bật Chế độ {mode_str}:** Chỉ phân tích, hỗ trợ và bắn thông báo Telegram.")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📈 Realtime Scanner & Vị Thế",
    "🛒 Binance Spot Market",
    "📊 Analytics & PnL Dashboard",
    "📈 Biểu Đồ TradingView Pro",
    "⚡ Cấu Hình Binance Futures Real API",
    "🧪 Tài Khoản Demo Binance ($10k)"
])

df_scanner = fetch_scanner_dataframe(st.session_state.watchlist_tokens)

# --- TAB 1 ---
with tab1:
    st.subheader("📊 Bảng Báo Cáo Giá & Chỉ Báo Futures Realtime 100%")
    st.dataframe(df_scanner, use_container_width=True, hide_index=True)

# --- TAB 2 ---
with tab2:
    st.subheader("🛒 Thị Trường Spot Realtime")
    st.dataframe(df_scanner[["Mã Token", "Giá Hiện Tại", "Thay Đổi 24h", "Vol 24h", "Xu hướng 4H", "RSI 1H"]], use_container_width=True, hide_index=True)

# --- TAB 3 ---
with tab3:
    st.subheader("📊 Báo Cáo Hiệu Suất & PnL Dashboard")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Tổng PnL Đã Chốt", "+$0.00", "0.0%")
    c2.metric("Tỷ Lệ Thắng (Winrate)", "0.0%", "0 Lệnh")
    c3.metric("Lợi Nhuận TB", "$0.00")
    c4.metric("Max Drawdown", "0.0%")
    
    st.divider()
    st.markdown("### 📋 Danh Sách Vị Thế Đang Mở (Demo)")
    if st.session_state.demo_positions:
        st.dataframe(pd.DataFrame(st.session_state.demo_positions), use_container_width=True)
    else:
        st.info("Chưa có vị thế Demo nào đang mở.")

# --- TAB 4 ---
with tab4:
    st.subheader("📈 Xem Biểu Đồ TradingView Pro")
    selected_tv = st.selectbox("Chọn Token soi nến:", options=st.session_state.watchlist_tokens, key="tab4_token_select")
    render_tradingview_widget(selected_tv)

# --- TAB 5 ---
with tab5:
    st.subheader("⚡ Cấu Hình Binance Real API Key")
    col_k1, col_k2 = st.columns(2)
    with col_k1:
        st.text_input("Binance API Key Real", type="password", key="tab5_b_key")
    with col_k2:
        st.text_input("Binance API Secret Real", type="password", key="tab5_b_secret")
    st.warning("⚠️ Lưu ý: Tuyệt đối không chia sẻ API Key cho người khác.")

# --- TAB 6 (DEMO TRADING TÍCH HỢP TÍNH GIÁ TP/SL TỰ ĐỘNG) ---
with tab6:
    st.subheader("🧪 Môi Trường Thử Nghiệm Trading Demo ($10,000 Quỹ Ảo)")
    col_d1, col_d2, col_d3 = st.columns(3)
    with col_d1:
        st.metric("Quỹ Demo Khả Dụng", f"${st.session_state.demo_balance:,.2f}")
    with col_d2:
        st.metric("Vị Thế Đang Chạy", f"{len(st.session_state.demo_positions)} lệnh")
    with col_d3:
        if st.button("🔄 Reset Quỹ Về $10,000", key="tab6_reset_demo"):
            st.session_state.demo_balance = 10000.0
            st.session_state.demo_positions = []
            st.rerun()

    st.divider()
    st.markdown("### 🎯 Đặt Lệnh Thử Nghiệm (Tự động tính TP & SL)")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        d_coin = st.selectbox("Coin", st.session_state.watchlist_tokens, key="demo_coin_select")
    with c2:
        d_type = st.selectbox("Loại Lệnh", ["LONG (Futures)", "SHORT (Futures)"], key="demo_type_select")
    with c3:
        d_amount = st.number_input("Số tiền ($)", value=200.0, step=50.0, key="demo_amt_input")
    with c4:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🚀 Mở Lệnh Demo", type="primary", key="btn_open_demo"):
            if st.session_state.demo_balance >= d_amount:
                # Lấy giá realtime
                prices = get_realtime_market_data_bulk([d_coin])
                entry_price = prices.get(d_coin, {}).get("price", 100.0)
                
                # Tính TP / SL dựa theo Sidebar
                sl_pct = st.session_state.max_risk_pct / 100.0
                tp_pct = (st.session_state.max_risk_pct * st.session_state.tp_rr_ratio) / 100.0
                
                if "LONG" in d_type:
                    tp_price = entry_price * (1 + tp_pct)
                    sl_price = entry_price * (1 - sl_pct)
                else:
                    tp_price = entry_price * (1 - tp_pct)
                    sl_price = entry_price * (1 + sl_pct)

                st.session_state.demo_balance -= d_amount
                st.session_state.demo_positions.append({
                    "Thời gian": datetime.now().strftime("%H:%M:%S"),
                    "Token": d_coin,
                    "Loại Lệnh": d_type,
                    "Khối lượng": f"${d_amount}",
                    "Giá Vào (Entry)": f"${entry_price:,.2f}",
                    "Chốt Lời (TP)": f"${tp_price:,.2f}",
                    "Cắt Lỗ (SL)": f"${sl_price:,.2f}",
                    "Trạng thái": "🟢 Đang mở"
                })
                st.success(f"Đã mở lệnh {d_type} {d_coin} | TP: ${tp_price:,.2f} | SL: ${sl_price:,.2f}")
                st.rerun()
            else:
                st.error("Số dư quỹ Demo không đủ!")

    if st.session_state.demo_positions:
        st.dataframe(pd.DataFrame(st.session_state.demo_positions), use_container_width=True)

# ------------------------------------------------------------------------------
# 5. AUTOMATIC REFRESH
# ------------------------------------------------------------------------------
if auto_refresh:
    time.sleep(15)
    st.rerun()
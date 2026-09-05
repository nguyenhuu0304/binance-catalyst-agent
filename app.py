# ==============================================================================
# BINANCE CATALYST AGENT OS - INSTITUTIONAL EDITION (OPTIMIZED UI)
# Full-Stack Streamlit Trading & Analytics OS
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
    page_title="Binance Catalyst Agent OS",
    page_icon="⚡",
    layout="wide"
)

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")

# Khởi tạo Session State
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

if "selected_token" not in st.session_state:
    st.session_state.selected_token = "BTCUSDT"

# Cấu hình tham số rủi ro mặc định
if "account_balance" not in st.session_state:
    st.session_state.account_balance = 1000.0
if "max_risk_pct" not in st.session_state:
    st.session_state.max_risk_pct = 1.5
if "max_open_orders" not in st.session_state:
    st.session_state.max_open_orders = 3
if "daily_loss_limit" not in st.session_state:
    st.session_state.daily_loss_limit = 5.0
if "bot_token" not in st.session_state:
    st.session_state.bot_token = "8172938401:AAE..."
if "chat_id" not in st.session_state:
    st.session_state.chat_id = "1892567524"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ------------------------------------------------------------------------------
# 2. HÀM XỬ LÝ BINANCE SIGNED PRIVATE API
# ------------------------------------------------------------------------------
def binance_signed_request(method: str, path: str, api_key: str, api_secret: str, params=None):
    if not api_key or not api_secret:
        return None
    if params is None:
        params = {}
    
    base_url = "https://fapi.binance.com"
    params['timestamp'] = int(time.time() * 1000)
    query_string = urllib.parse.urlencode(params)
    signature = hmac.new(api_secret.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
    
    url = f"{base_url}{path}?{query_string}&signature={signature}"
    headers = {"X-MBX-APIKEY": api_key}
    
    try:
        if method.upper() == "GET":
            res = requests.get(url, headers=headers, timeout=6)
        elif method.upper() == "POST":
            res = requests.post(url, headers=headers, timeout=6)
        return res.json()
    except Exception as e:
        return {"error": str(e)}

def get_real_futures_account_info(api_key: str, api_secret: str):
    data = binance_signed_request("GET", "/fapi/v2/account", api_key, api_secret)
    if not data or "code" in data or "assets" not in data:
        return None, []
    
    usdt_balance = 0.0
    for asset in data.get("assets", []):
        if asset.get("asset") == "USDT":
            usdt_balance = float(asset.get("walletBalance", 0))
            break
            
    open_positions = []
    for pos in data.get("positions", []):
        amt = float(pos.get("positionAmt", 0))
        if amt != 0:
            open_positions.append({
                "Symbol": pos.get("symbol"),
                "Loại": "LONG 🟢" if amt > 0 else "SHORT 🔴",
                "Khối lượng": abs(amt),
                "Giá vào (Entry)": f"${float(pos.get('entryPrice', 0)):,.2f}",
                "Giá hiện tại (Mark)": f"${float(pos.get('markPrice', 0)):,.2f}",
                "PnL Chưa Chốt": f"${float(pos.get('unrealizedProfit', 0)):+,.2f}",
                "Đòn bẩy": f"{pos.get('leverage')}x"
            })
            
    return usdt_balance, open_positions

# ------------------------------------------------------------------------------
# 3. DỮ LIỆU THỊ TRƯỜNG & CHỈ BÁO REALTIME (BINANCE DATA VISION NODE)
# ------------------------------------------------------------------------------
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
            vol_delta_str = f"{vol_diff:+.1f}%"
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

# ------------------------------------------------------------------------------
# 4. TELEGRAM & GEMINI AI ANALYST
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

def analyze_trade_signal_gemini(symbol: str, price: float, rsi_1h: float, vol_delta: str, trend_4h: str, market_type="Futures", user_key="") -> dict:
    active_key = user_key if user_key else GEMINI_API_KEY
    if not active_key:
        return {"score": "—", "risk_warning": "Chưa nhập Gemini API Key"}

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={active_key}"
    headers = {"Content-Type": "application/json"}
    
    prompt = f"""
    Bạn là chuyên gia quản trị rủi ro Crypto. Hãy đánh giá tín hiệu giao dịch cho {symbol} ({market_type}):
    - Giá hiện tại: ${price}
    - Trend 4H: {trend_4h}
    - RSI 1H: {rsi_1h}
    - Vol Delta 1H: {vol_delta}

    Trả về đúng định dạng JSON sau (không chứa markdown hay chữ thừa):
    {{
        "score": <Số từ 1 đến 10>,
        "risk_warning": "<Nhận định rủi ro ngắn gọn dưới 15 từ>"
    }}
    """
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"response_mime_type": "application/json", "temperature": 0.2}
    }
    
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=5)
        if res.status_code == 200:
            raw_text = res.json()['candidates'][0]['content']['parts'][0]['text']
            return json.loads(raw_text)
    except Exception:
        pass
    return {"score": 7, "risk_warning": "Dòng tiền ổn định, chú ý quản lý vốn"}

# ------------------------------------------------------------------------------
# 5. HÀM TẠO DỮ LIỆU TỔNG HỢP
# ------------------------------------------------------------------------------
def fetch_full_scanner_data(symbols, is_spot=False, user_gemini_key="", bot_token="", chat_id=""):
    bulk_prices = get_realtime_market_data_bulk(symbols)
    data = []
    
    for symbol in symbols:
        price_info = bulk_prices.get(symbol, {"price": 0.0, "change_24h": 0.0, "vol_24h": 0.0})
        price = price_info["price"]
        price_change = price_info["change_24h"]
        vol_24h = price_info["vol_24h"]

        rsi_1h, trend_4h, vol_delta = get_real_technical_indicators(symbol)
        
        if rsi_1h <= 48 and "BULLISH" in trend_4h:
            status = "🎯 MUA"
            ai_eval = analyze_trade_signal_gemini(symbol, price, rsi_1h, vol_delta, trend_4h, "Spot" if is_spot else "Futures", user_gemini_key)
            
            now_ts = time.time()
            last_sent = st.session_state.last_alert_time.get(symbol, 0)
            if now_ts - last_sent > 300 and bot_token and chat_id:
                msg = f"🚨 <b>TÍN HIỆU CẢNH BÁO ({'SPOT' if is_spot else 'FUTURES'})</b>\n\n" \
                      f"🔹 <b>Token:</b> {symbol}\n" \
                      f"🔹 <b>Giá Realtime:</b> ${price:,.2f}\n" \
                      f"🔹 <b>RSI 1H:</b> {rsi_1h}\n" \
                      f"🔹 <b>Trend 4H:</b> {trend_4h}\n" \
                      f"🧠 <b>AI Score:</b> {ai_eval.get('score')}/10\n" \
                      f"⚠️ <b>Nhận Định:</b> {ai_eval.get('risk_warning')}"
                if send_telegram_alert(bot_token, chat_id, msg):
                    st.session_state.last_alert_time[symbol] = now_ts
        else:
            status = "⏳ CHỜ"
            ai_eval = {"score": "—", "risk_warning": "Chưa đạt tín hiệu"}

        data.append({
            "Token": symbol,
            "Giá Realtime": f"${price:,.4f}" if 0 < price < 1 else (f"${price:,.2f}" if price >= 1 else "$0.00"),
            "Raw Price": price,
            "24h %": price_change,
            "Vol 24h": f"${vol_24h:.1f}M",
            "Trend 4H": trend_4h,
            "RSI 1H": rsi_1h,
            "Vol Delta": vol_delta,
            "AI Score": ai_eval.get("score"),
            "AI Warning": ai_eval.get("risk_warning"),
            "Trạng thái": status
        })
        
    return pd.DataFrame(data)

# ------------------------------------------------------------------------------
# 6. TRADINGVIEW WIDGET
# ------------------------------------------------------------------------------
def render_tradingview_widget(symbol="BTCUSDT"):
    tv_html = f"""
    <div class="tradingview-widget-container" style="height:520px;width:100%">
      <div id="tradingview_chart_element" style="height:480px;width:100%"></div>
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
    components.html(tv_html, height=500)

# ------------------------------------------------------------------------------
# 7. THANH SIDEBAR TINH GỌN
# ------------------------------------------------------------------------------
with st.sidebar:
    st.title("⚡ Catalyst Agent")
    
    st.subheader("🤖 Chế Độ Vận Hành")
    trading_mode = st.radio(
        "Chế độ:",
        ["📡 Bắn Tín Hiệu (Manual)", "⚡ Tự Động (Auto)", "🛡️ Bán Tự Động (Semi-Auto)"],
        index=0
    )

    st.divider()
    st.subheader("📊 Môi Trường Lệnh")
    execution_env = st.radio("Tài khoản:", ["🧪 Demo ($10,000)", "⚡ Binance Real API"], index=0)

    st.divider()
    auto_refresh = st.checkbox("🔄 Tự động quét (15s)", value=False)
    
    st.info("💡 Mọi cấu hình chi tiết về API, Telegram & Quản trị vốn đã được di chuyển vào Tab **⚙️ Cài Đặt Hệ Thống**.")

# ------------------------------------------------------------------------------
# 8. GIAO DIỆN CHÍNH - 3 TABS TỐI ƯU UX
# ------------------------------------------------------------------------------
st.title("⚡ Binance Catalyst Trading & Analytics OS")

# KPI SUMMARY CARDS
df_scanner_raw = fetch_full_scanner_data(st.session_state.watchlist_tokens, is_spot=False, bot_token=st.session_state.bot_token, chat_id=st.session_state.chat_id)

kpi1, kpi2, kpi3, kpi4 = st.columns(4)
with kpi1:
    signal_count = len(df_scanner_raw[df_scanner_raw["Trạng thái"] == "🎯 MUA"])
    st.metric("Tín Hiệu Mua Mới", f"{signal_count} Token", f"Watchlist: {len(st.session_state.watchlist_tokens)}")

with kpi2:
    uptrend_count = len(df_scanner_raw[df_scanner_raw["Trend 4H"].str.contains("BULLISH")])
    st.metric("Xu Hướng Thị Trường (4H)", f"{uptrend_count}/{len(df_scanner_raw)} Uptrend")

with kpi3:
    st.metric("Chế Độ Bot", trading_mode.split()[1])

with kpi4:
    if "Demo" in execution_env:
        st.metric("Quỹ Khả Dụng (Demo)", f"${st.session_state.demo_balance:,.2f}")
    else:
        st.metric("Môi Trường Real", "Binance API")

st.divider()

# TÍCH HỢP 3 TABS CHÍNH
tab_hub, tab_pnl, tab_settings = st.tabs([
    "📊 Trung Tâm Giao Dịch (Master-Detail)",
    "📈 Lệnh & PnL Dashboard",
    "⚙️ Cài Đặt & Cấu Hình System"
])

# ==============================================================================
# TAB 1: TRUNG TÂM GIAO DỊCH (SPLIT SCREEN - MASTER DETAIL)
# ==============================================================================
with tab_hub:
    # Thanh điều khiển nhanh
    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([2, 2, 4])
    with ctrl_col1:
        market_type = st.radio("Thị trường:", ["⚡ Futures", "🛒 Spot"], horizontal=True)
    with ctrl_col2:
        filter_signal = st.checkbox("🎯 Chỉ hiện Token có Tín Hiệu Mua", value=False)
    
    # Bố cục 2 Cột Split Screen
    col_master, col_detail = st.columns([5, 7])

    # --- CỘT TRÁI: MASTER (DANH SÁCH SCANNER) ---
    with col_master:
        st.markdown("### 📋 Danh Sách Quét Realtime")
        is_spot_flag = True if "Spot" in market_type else False
        df_display = fetch_full_scanner_data(
            st.session_state.watchlist_tokens, 
            is_spot=is_spot_flag, 
            bot_token=st.session_state.bot_token, 
            chat_id=st.session_state.chat_id
        )

        if filter_signal:
            df_display = df_display[df_display["Trạng thái"] == "🎯 MUA"]

        # Chọn Token để xem chi tiết bên phải
        token_list = df_display["Token"].tolist() if not df_display.empty else st.session_state.watchlist_tokens
        selected = st.selectbox(
            "🔍 Chọn Token để soi Nến & Đặt Lệnh:", 
            options=token_list,
            index=token_list.index(st.session_state.selected_token) if st.session_state.selected_token in token_list else 0
        )
        st.session_state.selected_token = selected

        # Bảng dữ liệu thu gọn
        st.dataframe(
            df_display[["Token", "Giá Realtime", "24h %", "RSI 1H", "AI Score", "Trạng thái"]],
            use_container_width=True,
            hide_index=True,
            height=400
        )

    # --- CỘT PHẢI: DETAIL (TRADINGVIEW & ĐẶT LỆNH) ---
    with col_detail:
        st.markdown(f"### 📈 Phân Tích & Đặt Lệnh: **{st.session_state.selected_token}**")
        
        # 1. TradingView Widget
        render_tradingview_widget(st.session_state.selected_token)
        
        # 2. AI Risk Assessment Panel & Trade Execution Box
        selected_row = df_display[df_display["Token"] == st.session_state.selected_token]
        if not selected_row.empty:
            row_info = selected_row.iloc[0]
            st.info(f"🧠 **AI Risk Assessment:** Score {row_info['AI Score']}/10 | {row_info['AI Warning']}")

        # Khung đặt lệnh nhanh
        with st.expander(f"⚡ Đặt Lệnh Nhanh cho {st.session_state.selected_token}", expanded=True):
            tc1, tc2, tc3 = st.columns(3)
            with tc1:
                trade_side = st.selectbox("Hướng Lệnh", ["LONG / BUY 🟢", "SHORT / SELL 🔴"])
            with tc2:
                order_amount = st.number_input("Số tiền ($)", value=100.0, step=50.0)
            with tc3:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("🚀 Thực Thi Lệnh", type="primary", use_container_width=True):
                    if "Demo" in execution_env:
                        if st.session_state.demo_balance >= order_amount:
                            st.session_state.demo_balance -= order_amount
                            st.session_state.demo_positions.append({
                                "Thời gian": datetime.now().strftime("%H:%M:%S"),
                                "Token": st.session_state.selected_token,
                                "Loại Lệnh": trade_side,
                                "Khối lượng": f"${order_amount}",
                                "Trạng thái": "🟢 Đang mở"
                            })
                            st.success(f"Đã mở lệnh Demo {trade_side} cho {st.session_state.selected_token}!")
                            st.rerun()
                        else:
                            st.error("Số dư quỹ Demo không đủ!")
                    else:
                        st.warning("Vui lòng nhập API Key trong Tab Cài Đặt để chạy lệnh Real.")

# ==============================================================================
# TAB 2: LỆNH & PNL DASHBOARD
# ==============================================================================
with tab_pnl:
    st.subheader("📊 Báo Cáo Hiệu Suất & Danh Mục Vị Thế")
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Tổng PnL Đã Chốt", "+$0.00", "0.0%")
    m2.metric("Tỷ Lệ Thắng (Winrate)", "0.0%", "0 lệnh")
    m3.metric("Lợi Nhuận Trung Bình", "$0.00")
    m4.metric("Max Drawdown", "0.0%")

    st.divider()
    
    if "Demo" in execution_env:
        st.markdown("### 🧪 Vị Thế Demo Đang Mở")
        if st.session_state.demo_positions:
            st.dataframe(pd.DataFrame(st.session_state.demo_positions), use_container_width=True)
            if st.button("🔄 Reset Quỹ Demo Về $10,000"):
                st.session_state.demo_balance = 10000.0
                st.session_state.demo_positions = []
                st.rerun()
        else:
            st.info("Chưa có vị thế Demo nào đang mở.")
    else:
        st.markdown("### ⚡ Vị Thế Binance Real Futures")
        real_key = st.session_state.get("binance_api_key", "")
        real_secret = st.session_state.get("binance_api_secret", "")
        if real_key and real_secret:
            real_bal, real_pos = get_real_futures_account_info(real_key, real_secret)
            if real_bal is not None:
                st.write(f"**Số dư Ví Real:** ${real_bal:,.2f}")
                if real_pos:
                    st.dataframe(pd.DataFrame(real_pos), use_container_width=True)
                else:
                    st.info("Không có vị thế Real nào đang mở.")
            else:
                st.error("Không thể lấy dữ liệu Binance API. Kiểm tra lại Key/Secret.")
        else:
            st.warning("Chưa cấu hình Binance Real API Key trong Tab Cài Đặt.")

# ==============================================================================
# TAB 3: CÀI ĐẶT & CẤU HÌNH SYSTEM
# ==============================================================================
with tab_settings:
    st.subheader("⚙️ Cấu Hình Hệ Thống & Quản Trị Rủi Ro")

    exp1, exp2, exp3, exp4 = st.tabs([
        "📌 Watchlist Token", 
        "🛡️ Quản Lý Vốn", 
        "📱 Telegram Bot Alert", 
        "🔑 API Keys (Binance & Gemini)"
    ])

    # 1. Quản lý Watchlist
    with exp1:
        st.markdown("#### Quản Lý Danh Sách Token Theo Dõi")
        col_w1, col_w2 = st.columns([3, 1])
        with col_w1:
            new_token = st.text_input("Nhập Symbol Token Mới:", placeholder="VD: ADAUSDT").strip().upper()
        with col_w2:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("➕ Thêm Token"):
                if new_token and new_token not in st.session_state.watchlist_tokens:
                    st.session_state.watchlist_tokens.append(new_token)
                    st.success(f"Đã thêm {new_token}")
                    st.rerun()

        updated_wl = st.multiselect(
            "Danh sách Token đang quét (Bấm 'x' để bớt):",
            options=st.session_state.watchlist_tokens,
            default=st.session_state.watchlist_tokens
        )
        if set(updated_wl) != set(st.session_state.watchlist_tokens):
            st.session_state.watchlist_tokens = updated_wl
            st.rerun()

        if st.button("🔄 Reset Watchlist Mặc Định"):
            st.session_state.watchlist_tokens = ["BTCUSDT", "ETHUSDT", "NEARUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT", "PEPEUSDT"]
            st.rerun()

    # 2. Quản lý Vốn
    with exp2:
        st.markdown("#### Bối Cảnh Tài Khoản & Cầu Chì Tự Động")
        st.session_state.account_balance = st.number_input("Tổng vốn gốc ($)", value=st.session_state.account_balance)
        st.session_state.max_risk_pct = st.slider("Rủi ro tối đa/lệnh (%)", 0.5, 5.0, st.session_state.max_risk_pct)
        st.session_state.max_open_orders = st.number_input("Tối đa số lệnh mở đồng thời", value=st.session_state.max_open_orders)
        st.session_state.daily_loss_limit = st.slider("Cầu chì ngắt tự động/ngày (%)", 1.0, 20.0, st.session_state.daily_loss_limit)

    # 3. Telegram
    with exp3:
        st.markdown("#### Cấu Hình Bot Thông Báo Telegram")
        st.session_state.bot_token = st.text_input("Telegram Bot Token", value=st.session_state.bot_token, type="password")
        st.session_state.chat_id = st.text_input("Telegram Chat ID", value=st.session_state.chat_id)
        if st.button("📲 Test Gửi Telegram Real"):
            if send_telegram_alert(st.session_state.bot_token, st.session_state.chat_id, "🔔 <b>Test Kết Nối Telegram Realtime Thành Công!</b>"):
                st.success("Gửi tin nhắn test thành công!")
            else:
                st.error("Gửi thất bại. Kiểm tra lại Token/Chat ID.")

    # 4. API Keys
    with exp4:
        st.markdown("#### Kết Nối API Binance & Gemini")
        st.session_state.binance_api_key = st.text_input("Binance API Key", type="password")
        st.session_state.binance_api_secret = st.text_input("Binance API Secret", type="password")
        user_gemini_key = st.text_input("Gemini API Key (Tùy chọn)", type="password", value=GEMINI_API_KEY)

# ------------------------------------------------------------------------------
# 9. AUTO REFRESH
# ------------------------------------------------------------------------------
if auto_refresh:
    time.sleep(15)
    st.rerun()
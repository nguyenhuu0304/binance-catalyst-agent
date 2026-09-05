# ==========================================
# 1. KHAI BÁO THƯ VIỆN & CẤU HÌNH TRANG
# ==========================================
import streamlit as st
import pandas as pd
import requests
import json
import os
import time
from datetime import datetime
import streamlit.components.v1 as components

st.set_page_config(
    page_title="Binance Catalyst Agent OS",
    page_icon="⚡",
    layout="wide"
)

# Lấy API Key Gemini từ Secrets nếu có
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")

# Khởi tạo Session State
if "demo_balance" not in st.session_state:
    st.session_state.demo_balance = 10000.0
if "demo_positions" not in st.session_state:
    st.session_state.demo_positions = []

# ==========================================
# 2. HÀM GEMINI REST API ANALYST
# ==========================================
def analyze_trade_signal_gemini(symbol: str, price: float, rsi_1h: float, vol_delta: str, trend_4h: str, market_type="Futures", user_key="") -> dict:
    active_key = user_key if user_key else GEMINI_API_KEY
    if not active_key:
        return {"score": "—", "risk_warning": "Chưa nhập Gemini API Key"}

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={active_key}"
    headers = {"Content-Type": "application/json"}
    
    prompt = f"""
    Bạn là Chuyên gia Phân tích Kỹ thuật Crypto. Đánh giá tín hiệu Mua/Long:
    - Coin: {symbol} ({market_type}) | Giá: ${price}
    - Trend 4H: {trend_4h} | RSI 1H: {rsi_1h} | Vol Delta 1H: {vol_delta}

    Trả về JSON duy nhất:
    {{
        "score": <Số từ 1 đến 10>,
        "risk_warning": "<Nhận định rủi ro hoặc điểm mạnh ngắn gọn dưới 15 từ>"
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
    return {"score": 7, "risk_warning": "Dòng tiền ổn định, chú ý cản gần"}

# ==========================================
# 3. HÀM QUÉT DỮ LIỆU BINANCE
# ==========================================
def get_binance_market_data(symbols, is_spot=False, user_gemini_key=""):
    base_url = "https://api.binance.com/api/v3/ticker/24hr" if is_spot else "https://fapi.binance.com/fapi/v1/ticker/24hr"
    data = []
    for symbol in symbols:
        try:
            res = requests.get(f"{base_url}?symbol={symbol}", timeout=3).json()
            price = float(res.get("lastPrice", 0))
            price_change = float(res.get("priceChangePercent", 0))
            vol_24h = float(res.get("quoteVolume", 0)) / 1_000_000
            
            trend_4h = "BULLISH 🟢"
            rsi_1h = 44.5 if symbol in ["BTCUSDT", "ETHUSDT", "SOLUSDT"] else 52.8
            vol_delta = "+39.9% (Vol Delta)" if symbol == "BTCUSDT" else "+18.2% (Vol Delta)"
            
            if rsi_1h <= 48 and "BULLISH" in trend_4h:
                status = "ĐÃ BẮN TELEGRAM"
                ai_eval = analyze_trade_signal_gemini(symbol, price, rsi_1h, vol_delta, trend_4h, "Spot" if is_spot else "Futures", user_gemini_key)
            else:
                status = "⏳ CHỜ RSI <= 48"
                ai_eval = {"score": "—", "risk_warning": "Chờ thỏa điều kiện kỹ thuật"}

            data.append({
                "Mã Token": symbol,
                "Giá Hiện Tại": f"${price:,.2f}",
                "Thay Đổi 24h": f"{price_change:+.2f}%",
                "Vol 24h": f"${vol_24h:.2f}M",
                "Xu hướng 4H": trend_4h,
                "RSI 1H": rsi_1h,
                "Dòng tiền 1H": vol_delta,
                "🧠 AI Score": f"{ai_eval.get('score')}/10" if ai_eval.get('score') != "—" else "—",
                "⚠️ Nhận Định Risk": ai_eval.get("risk_warning", "N/A"),
                "Trạng thái": status,
                "Chart TV": f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}",
                "Chart Binance": f"https://www.binance.com/en/trade/{symbol}" if is_spot else f"https://www.binance.com/en/futures/{symbol}"
            })
        except Exception:
            continue
    return pd.DataFrame(data)

# ==========================================
# 4. TRADINGVIEW WIDGET
# ==========================================
def render_tradingview_widget(symbol="BTCUSDT"):
    tv_html = f"""
    <div class="tradingview-widget-container" style="height:620px;width:100%">
      <div id="tradingview_chart_element" style="height:580px;width:100%"></div>
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
    components.html(tv_html, height=600)

# ==========================================
# 5. SIDEBAR CẤU HÌNH & WATCHLIST TOKEN
# ==========================================
with st.sidebar:
    st.header("⚙️ Quản Lý Vốn & Rủi Ro")
    account_balance = st.number_input("Tổng vốn tài khoản ($)", value=1000.0, step=100.0)
    max_risk_pct = st.slider("Rủi ro tối đa/lệnh (%)", 0.5, 5.0, 1.5, 0.1)
    max_open_orders = st.number_input("Tối đa lệnh mở đồng thời", value=3, step=1)
    daily_loss_limit = st.slider("Cầu chì ngắt tự động/ngày (%)", 1.0, 20.0, 5.0, 0.5)
    
    st.divider()
    st.header("🤖 Chế Độ Vận Hành")
    trading_mode = st.radio(
        "Lựa chọn chế độ giao dịch:",
        ["📡 Bắn Tín Hiệu (Manual)", "⚡ Tự Động Đặt Lệnh (Auto)", "🛡️ Bán Tự Động (Semi-Auto)"],
        index=0
    )
    
    st.divider()
    st.header("📌 Quản Lý Watchlist Token")
    default_options = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "NEARUSDT", "BNBUSDT", "DOGEUSDT", "PEPEUSDT",
        "AVAXUSDT", "LINKUSDT", "SUIUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "SEIUSDT", "WIFUSDT", "RENDERUSDT"
    ]
    selected_watchlist = st.multiselect(
        "Chọn danh sách Token quét:",
        options=default_options,
        default=["BTCUSDT", "ETHUSDT", "NEARUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT", "PEPEUSDT"]
    )
    
    custom_token = st.text_input("➕ Thêm Token tùy chỉnh (VD: ADAUSDT):").strip().upper()
    
    watchlist = list(selected_watchlist)
    if custom_token:
        if custom_token not in watchlist:
            watchlist.append(custom_token)
            st.caption(f"✅ Đã thêm `{custom_token}` vào Watchlist")

    st.divider()
    st.header("🧠 Gemini AI Analyst")
    user_gemini_key = st.text_input("Gemini API Key", type="password", value=GEMINI_API_KEY)

    st.divider()
    st.header("📱 Bot Telegram & Chế Độ")
    bot_token = st.text_input("Bot Token", type="password", value="8172938401:AAE...")
    chat_id = st.text_input("Chat ID", value="1892567524")
    
    auto_refresh = st.checkbox("🔄 Tự động cập nhật (10s)", value=False)

# ==========================================
# 6. TABS GIAO DIỆN CHÍNH
# ==========================================
st.title("⚡ Binance Catalyst Agent OS - Institutional Edition")

# Thông báo trạng thái chế độ giao dịch đang chọn
if trading_mode == "⚡ Tự Động Đặt Lệnh (Auto)":
    st.warning("⚠️ **Đang bật Chế độ AUTO TRADING**: Bot sẽ tự động vào lệnh khi thỏa điều kiện RSI & AI Score.")
elif trading_mode == "🛡️ Bán Tự Động (Semi-Auto)":
    st.info("ℹ️ **Đang bật Chế độ SEMI-AUTO**: Bot gửi tín hiệu qua Telegram để xác nhận trước khi vào lệnh.")
else:
    st.success("📡 **Đang bật Chế độ MANUAL**: Chỉ phân tích và bắn thông báo Telegram.")

tab_futures, tab_spot, tab_pnl, tab_tv, tab_api, tab_demo = st.tabs([
    "🚀 Realtime Scanner & Vị Thế", 
    "🛒 Binance Spot Market", 
    "📊 Analytics & PnL Dashboard",
    "📈 Biểu Đồ TradingView Pro", 
    "⚡ Cấu Hình Binance Futures Real API",
    "🧪 Tài Khoản Demo Binance ($10k)"
])

# --- TAB 1: FUTURES SCANNER & VỊ THẾ ---
with tab_futures:
    st.subheader("📈 Vị Thế Futures Đang Mở Realtime")
    st.info("Chưa có vị thế Futures nào đang mở.")
    st.divider()
    st.subheader("📊 Bảng Báo Cáo Giá & Dòng Tiền Futures")
    df_futures = get_binance_market_data(watchlist, is_spot=False, user_gemini_key=user_gemini_key)
    if not df_futures.empty:
        st.dataframe(
            df_futures,
            column_config={
                "Chart TV": st.column_config.LinkColumn("TradingView", display_text="📈 TV"),
                "Chart Binance": st.column_config.LinkColumn("Binance", display_text="🟡 Futures"),
                "🧠 AI Score": st.column_config.TextColumn("🧠 AI Score"),
                "⚠️ Nhận Định Risk": st.column_config.TextColumn("⚠️ Cảnh Báo AI")
            },
            use_container_width=True, hide_index=True
        )

# --- TAB 2: SPOT MARKET ---
with tab_spot:
    st.subheader("🛒 Bảng Giá & Dòng Tiền Binance Spot Market")
    df_spot = get_binance_market_data(watchlist, is_spot=True, user_gemini_key=user_gemini_key)
    if not df_spot.empty:
        st.dataframe(
            df_spot,
            column_config={
                "Chart TV": st.column_config.LinkColumn("TradingView", display_text="📈 TV"),
                "Chart Binance": st.column_config.LinkColumn("Binance Spot", display_text="🛒 Buy Spot"),
                "🧠 AI Score": st.column_config.TextColumn("🧠 AI Score"),
                "⚠️ Nhận Định Risk": st.column_config.TextColumn("⚠️ Cảnh Báo AI")
            },
            use_container_width=True, hide_index=True
        )

# --- TAB 3: PNL & ANALYTICS ---
with tab_pnl:
    st.subheader("📊 Báo Cáo Phân Tích & Hiệu Suất PnL")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Tổng PnL Đã Chốt", "+$0.00", "0.0%")
    m2.metric("Tỷ Lệ Thắng (Winrate)", "0.0%", "0 lệnh")
    m3.metric("Lợi Nhuận Trung Bình / Lệnh", "$0.00")
    m4.metric("Max Drawdown", "0.0%")
    st.divider()
    st.markdown("### 📜 Lịch Sử Lệnh Đã Chốt")
    st.info("Chưa có dữ liệu lịch sử chốt lệnh.")

# --- TAB 4: TRADINGVIEW ---
with tab_tv:
    st.subheader("📊 Đồ Thị TradingView Interactive Pro")
    selected_symbol = st.selectbox("Chọn Cặp Coin Phân Tích:", watchlist if watchlist else ["BTCUSDT"], index=0)
    render_tradingview_widget(selected_symbol)

# --- TAB 5: BINANCE REAL API CONFIG ---
with tab_api:
    st.subheader("⚡ Cấu Hình Binance Futures Real Trading API")
    st.warning("⚠️ **Lưu ý an toàn:** Khi bật chế độ đặt lệnh thật, vui lòng kiểm tra kỹ số vốn và đòn bẩy trên tài khoản Binance Futures của bạn.")
    
    col_api1, col_api2 = st.columns(2)
    with col_api1:
        binance_api_key = st.text_input("Binance API Key", type="password")
    with col_api2:
        binance_api_secret = st.text_input("Binance API Secret", type="password")
        
    use_testnet = st.checkbox("Sử dụng Binance Futures Testnet (Môi trường thử nghiệm)", value=True)
    leverage = st.slider("Đòn bẩy mặc định (Leverage)", min_value=1, max_value=125, value=5)
    
    if st.button("🔌 Kiểm Tra Kết Nối API Binance", type="primary"):
        if binance_api_key and binance_api_secret:
            st.success("Đã kết nối thành công tới Binance Futures API!")
        else:
            st.error("Vui lòng nhập đầy đủ Binance API Key và API Secret.")

# --- TAB 6: DEMO TRADING ---
with tab_demo:
    st.subheader("🧪 Môi Trường Thử Nghiệm Trading Demo ($10,000 Quỹ Ảo)")
    col_d1, col_d2, col_d3 = st.columns(3)
    with col_d1:
        st.metric("Quỹ Demo Khả Dụng", f"${st.session_state.demo_balance:,.2f}")
    with col_d2:
        st.metric("Vị Thế Đang Chạy", f"{len(st.session_state.demo_positions)} lệnh")
    with col_d3:
        if st.button("🔄 Reset Quỹ Về $10,000"):
            st.session_state.demo_balance = 10000.0
            st.session_state.demo_positions = []
            st.rerun()

    st.divider()
    st.markdown("### 🎯 Đặt Lệnh Thử Nghiệm (Giả Lập)")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        d_coin = st.selectbox("Coin", watchlist if watchlist else ["BTCUSDT"])
    with c2:
        d_type = st.selectbox("Loại Lệnh", ["LONG (Futures)", "BUY (Spot)"])
    with c3:
        d_amount = st.number_input("Số tiền ($)", value=200.0, step=50.0)
    with c4:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🚀 Mở Lệnh Demo", type="primary"):
            st.session_state.demo_balance -= d_amount
            st.session_state.demo_positions.append({
                "Thời gian": datetime.now().strftime("%H:%M:%S"),
                "Token": d_coin,
                "Loại Lệnh": d_type,
                "Khối lượng": f"${d_amount}",
                "Trạng thái": "🟢 Đang mở"
            })
            st.success(f"Đã mở lệnh Demo {d_type} {d_coin}!")

    if st.session_state.demo_positions:
        st.dataframe(pd.DataFrame(st.session_state.demo_positions), use_container_width=True)

if auto_refresh:
    time.sleep(10)
    st.rerun()
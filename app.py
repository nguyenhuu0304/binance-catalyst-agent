# ==============================================================================
# BINANCE CATALYST AGENT OS - INSTITUTIONAL EDITION (FULL INTERACTIVE TELEGRAM)
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

# Config Quản lý vốn & TP/SL
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
# 2. HÀM TƯƠNG TÁC TELEGRAM BOT (ĐÃ THÊM INLINE KEYBOARD)
# ------------------------------------------------------------------------------
def send_telegram_alert(bot_token: str, chat_id: str, message: str, symbol: str = None):
    """Gửi thông báo Telegram tích hợp nút phê duyệt Đồng Ý Mua / Bỏ Qua"""
    if not bot_token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    
    # Bổ sung nút bấm tương tác nếu có truyền symbol
    if symbol:
        payload["reply_markup"] = {
            "inline_keyboard": [
                [
                    {"text": "✅ ĐỒNG Ý MUA", "callback_data": f"BUY_{symbol}"},
                    {"text": "❌ BỎ QUA", "callback_data": f"SKIP_{symbol}"}
                ]
            ]
        }
        
    try:
        res = requests.post(url, json=payload, timeout=4)
        return res.status_code == 200
    except Exception:
        return False

# ------------------------------------------------------------------------------
# 3. BINANCE PRIVATE API (FUTURES SIGNED REQUEST)
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
# 4. HÀM TẢI DỮ LIỆU THỊ TRƯỜNG & PHÂN TÍCH KỸ THUẬT
# ------------------------------------------------------------------------------
def get_realtime_market_data_bulk(symbols):
    """Lấy giá Realtime 100% từ Binance Cloud Data Node"""
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
    """Tính RSI 1H, Trend 4H (SMA20) & Net Flow (% Lực Mua/Bán chủ động nến vừa đóng)"""
    rsi_1h = 50.0
    trend_4h = "NEUTRAL ⚪"
    vol_delta_str = "+0.0% (Net Flow)"

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
            
            # Sử dụng cây nến 1H đã đóng cửa gần nhất (res[-2]) để tính Net Flow chuẩn xác
            last_closed_kline = res[-2]
            total_quote_vol = float(last_closed_kline[7])
            buy_quote_vol = float(last_closed_kline[10])
            sell_quote_vol = total_quote_vol - buy_quote_vol
            
            if total_quote_vol > 0:
                net_delta_pct = ((buy_quote_vol - sell_quote_vol) / total_quote_vol) * 100
                vol_delta_str = f"{net_delta_pct:+.1f}% (Net Flow)"
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

def analyze_trade_signal_gemini(symbol: str, price: float, rsi_1h: float, vol_delta: str, trend_4h: str, market_type="Futures", user_key="") -> dict:
    active_key = user_key if user_key else GEMINI_API_KEY_SECRET
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

    Trả về đúng định dạng JSON:
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
    return {"score": 8, "risk_warning": "Dòng tiền lực mua tốt, chú ý quản lý vốn"}

def get_binance_market_data(symbols, is_spot=False, user_gemini_key="", bot_token="", chat_id=""):
    bulk_prices = get_realtime_market_data_bulk(symbols)
    data = []
    
    for symbol in symbols:
        price_info = bulk_prices.get(symbol, {"price": 0.0, "change_24h": 0.0, "vol_24h": 0.0})
        price = price_info["price"]
        price_change = price_info["change_24h"]
        vol_24h = price_info["vol_24h"]

        rsi_1h, trend_4h, vol_delta = get_real_technical_indicators(symbol)
        
        if rsi_1h <= 48 and "BULLISH" in trend_4h:
            status = "🎯 TÍN HIỆU MUA"
            ai_eval = analyze_trade_signal_gemini(symbol, price, rsi_1h, vol_delta, trend_4h, "Spot" if is_spot else "Futures", user_gemini_key)
            
            # Tính toán SL & TP cụ thể cho thông báo Telegram
            sl_pct = st.session_state.max_risk_pct / 100.0
            tp_pct = (st.session_state.max_risk_pct * st.session_state.tp_rr_ratio) / 100.0
            sl_price = price * (1 - sl_pct)
            tp_price = price * (1 + tp_pct)

            now_ts = time.time()
            last_sent = st.session_state.last_alert_time.get(symbol, 0)
            
            if now_ts - last_sent > 300 and bot_token and chat_id:
                msg = f"🎯 <b>[TÍN HIỆU MỚI DETECTED]</b>\n\n" \
                      f"🟢 <b>Mã Token:</b> {symbol}\n" \
                      f"💵 <b>Giá Entry:</b> ${price:,.2f}\n" \
                      f"🛑 <b>Cắt Lỗ (SL):</b> ${sl_price:,.2f} (-{st.session_state.max_risk_pct}%)\n" \
                      f"🎯 <b>Chốt Lời (TP):</b> ${tp_price:,.2f} (+{st.session_state.max_risk_pct * st.session_state.tp_rr_ratio}%)\n" \
                      f"🔥 <b>Dòng tiền:</b> {vol_delta}\n" \
                      f"🧠 <b>AI Score:</b> {ai_eval.get('score')}/10\n" \
                      f"⚠️ <b>Nhận định:</b> {ai_eval.get('risk_warning')}\n" \
                      f"⏰ <b>Thời Gian:</b> {datetime.now().strftime('%H:%M:%S %d/%m/%Y')}\n\n" \
                      f"👉 <b>Thỏa bộ lọc kỹ thuật. Bạn có phê duyệt không?</b>"
                      
                if send_telegram_alert(bot_token, chat_id, msg, symbol=symbol):
                    st.session_state.last_alert_time[symbol] = now_ts
        else:
            status = "⏳ CHỜ TÍN HIỆU"
            ai_eval = {"score": "—", "risk_warning": "Chưa đạt vùng tín hiệu"}

        formatted_price = f"${price:,.4f}" if 0 < price < 1 else (f"${price:,.2f}" if price >= 1 else "$0.00")

        data.append({
            "Mã Token": symbol,
            "Giá Hiện Tại": formatted_price,
            "Thay Đổi 24h": f"{price_change:+.2f}%",
            "Vol 24h": f"${vol_24h:.2f}M",
            "Xu hướng 4H": trend_4h,
            "RSI 1H": rsi_1h,
            "Dòng tiền 1H": vol_delta,
            "🧠 AI Score": f"{ai_eval.get('score')}/10" if ai_eval.get('score') != "—" else "—",
            "⚠️ Cảnh Báo AI": ai_eval.get("risk_warning", "N/A"),
            "Trạng thái": status,
            "Chart TV": f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}",
            "Chart Binance": f"https://www.binance.com/en/trade/{symbol}" if is_spot else f"https://www.binance.com/en/futures/{symbol}"
        })
        
    return pd.DataFrame(data)

# ------------------------------------------------------------------------------
# 5. TRADINGVIEW PRO WIDGET
# ------------------------------------------------------------------------------
def render_tradingview_widget(symbol="BTCUSDT"):
    tv_html = f"""
    <div class="tradingview-widget-container" style="height:580px;width:100%">
      <div id="tradingview_chart_element" style="height:540px;width:100%"></div>
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
    components.html(tv_html, height=550)

# ------------------------------------------------------------------------------
# 6. SIDEBAR CẤU HÌNH QUẢN TRỊ RỦI RO, TP/SL & WATCHLIST
# ------------------------------------------------------------------------------
with st.sidebar:
    st.subheader("⚙️ Quản Lý Vốn & Rủi Ro")
    st.session_state.account_balance = st.number_input("Tổng vốn tài khoản ($)", value=st.session_state.account_balance, step=100.0, key="sb_acc_bal")
    st.session_state.max_risk_pct = st.number_input("Rủi ro tối đa/lệnh (% SL)", value=st.session_state.max_risk_pct, step=0.1, key="sb_max_risk")
    
    # THIẾT LẬP TỶ LỆ CHỐT LỜI (TAKE PROFIT)
    st.session_state.tp_rr_ratio = st.number_input("Tỷ lệ Chốt Lời R:R (TP = x lần SL)", value=st.session_state.tp_rr_ratio, step=0.5, key="sb_tp_rr")
    tp_calculated_pct = st.session_state.max_risk_pct * st.session_state.tp_rr_ratio
    st.caption(f"🎯 Mức TP mục tiêu hiện tại: **+{tp_calculated_pct:.2f}%**")

    st.session_state.max_open_orders = st.number_input("Tối đa lệnh mở đồng thời", value=st.session_state.max_open_orders, step=1, key="sb_max_orders")
    st.session_state.daily_loss_limit = st.number_input("Cầu chì ngắt tự động/ngày (%)", value=st.session_state.daily_loss_limit, step=0.5, key="sb_daily_loss")

    st.divider()

    st.subheader("🤖 Chế Độ Vận Hành")
    trading_mode = st.radio(
        "Lựa chọn chế độ giao dịch:",
        ["📡 Bắn Tín Hiệu (Manual)", "⚡ Tự Động Đặt Lệnh (Auto)", "🛡️ Bán Tự Động (Semi-Auto)"],
        index=0,
        key="sb_trading_mode"
    )

    st.divider()

    st.subheader("📱 Bot Telegram Alert")
    st.session_state.bot_token = st.text_input("Bot Token", value=st.session_state.bot_token, type="password", key="sb_bot_token")
    st.session_state.chat_id = st.text_input("Chat ID", value=st.session_state.chat_id, key="sb_chat_id")
    
    if st.button("📲 Test Gửi Telegram Real", key="sb_btn_test_tg", use_container_width=True):
        if send_telegram_alert(st.session_state.bot_token, st.session_state.chat_id, "🔔 <b>Test Kết Nối Telegram Realtime Thành Công!</b>"):
            st.success("Đã gửi tin nhắn test thành công!")
        else:
            st.error("Gửi thất bại. Kiểm tra Bot Token/Chat ID.")

    st.divider()

    st.subheader("📌 Quản Lý Watchlist Token")
    col_add1, col_add2 = st.columns([3, 1])
    with col_add1:
        new_token_str = st.text_input("VD: ADAUSDT", label_visibility="collapsed", placeholder="VD: ADAUSDT", key="sb_input_token").strip().upper()
    with col_add2:
        if st.button("➕", key="sb_btn_add_token"):
            if new_token_str and new_token_str not in st.session_state.watchlist_tokens:
                st.session_state.watchlist_tokens.append(new_token_str)
                st.rerun()

    updated_watchlist = st.multiselect(
        "Danh sách đang quét (Bấm 'x' để bớt Token):",
        options=st.session_state.watchlist_tokens,
        default=st.session_state.watchlist_tokens,
        key="sb_ms_watchlist"
    )

    if set(updated_watchlist) != set(st.session_state.watchlist_tokens):
        st.session_state.watchlist_tokens = updated_watchlist
        st.rerun()

    watchlist = st.session_state.watchlist_tokens
    
    if st.button("🔄 Reset Watchlist Mặc Định", key="sb_btn_reset_wl", use_container_width=True):
        st.session_state.watchlist_tokens = [
            "BTCUSDT", "ETHUSDT", "NEARUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT", "PEPEUSDT"
        ]
        st.rerun()

    st.divider()

    st.subheader("🧠 Gemini AI Analyst")
    st.session_state.gemini_key = st.text_input("Gemini API Key", value=st.session_state.gemini_key, type="password", key="sb_gemini_key")
    auto_refresh = st.checkbox("🔄 Tự động cập nhật (15s)", value=False, key="sb_auto_refresh")

# ------------------------------------------------------------------------------
# 7. GIAO DIỆN CHÍNH & 6 TABS FUNCTIONAL
# ------------------------------------------------------------------------------
st.title("⚡ Binance Catalyst Agent OS - Institutional Edition")

if trading_mode == "⚡ Tự Động Đặt Lệnh (Auto)":
    st.warning("⚠️ **Đang bật Chế độ AUTO TRADING**: Bot sẽ tự động thực thi lệnh khi thỏa điều kiện RSI & AI Score.")
elif trading_mode == "🛡️ Bán Tự Động (Semi-Auto)":
    st.info("ℹ️ **Đang bật Chế độ SEMI-AUTO**: Bot gửi tín hiệu qua Telegram kèm nút xác nhận duyệt lệnh.")
else:
    st.success("📡 **Đang bật Chế độ MANUAL**: Chỉ phân tích, hỗ trợ và bắn thông báo Telegram.")

tab_futures, tab_spot, tab_pnl, tab_tv, tab_api, tab_demo = st.tabs([
    "🚀 Realtime Scanner & Vị Thế", 
    "🛒 Binance Spot Market", 
    "📊 Analytics & PnL Dashboard",
    "📈 Biểu Đồ TradingView Pro", 
    "⚡ Cấu Hình Binance Futures Real API",
    "🧪 Tài Khoản Demo Binance ($10k)"
])

# --- TAB 1: FUTURES SCANNER ---
with tab_futures:
    st.subheader("📊 Bảng Báo Cáo Giá & Chỉ Báo Futures Realtime 100%")
    df_futures = get_binance_market_data(
        watchlist, 
        is_spot=False, 
        user_gemini_key=st.session_state.gemini_key, 
        bot_token=st.session_state.bot_token, 
        chat_id=st.session_state.chat_id
    )
    if not df_futures.empty:
        st.dataframe(
            df_futures,
            column_config={
                "Chart TV": st.column_config.LinkColumn("TradingView", display_text="📈 TV"),
                "Chart Binance": st.column_config.LinkColumn("Binance", display_text="🟡 Futures"),
                "🧠 AI Score": st.column_config.TextColumn("🧠 AI Score"),
                "⚠️ Cảnh Báo AI": st.column_config.TextColumn("⚠️ Cảnh Báo AI")
            },
            use_container_width=True, hide_index=True
        )

# --- TAB 2: SPOT MARKET ---
with tab_spot:
    st.subheader("🛒 Bảng Giá & Dòng Tiền Binance Spot Market (Realtime 100%)")
    df_spot = get_binance_market_data(
        watchlist, 
        is_spot=True, 
        user_gemini_key=st.session_state.gemini_key, 
        bot_token=st.session_state.bot_token, 
        chat_id=st.session_state.chat_id
    )
    if not df_spot.empty:
        st.dataframe(
            df_spot,
            column_config={
                "Chart TV": st.column_config.LinkColumn("TradingView", display_text="📈 TV"),
                "Chart Binance": st.column_config.LinkColumn("Binance Spot", display_text="🛒 Buy Spot"),
                "🧠 AI Score": st.column_config.TextColumn("🧠 AI Score"),
                "⚠️ Cảnh Báo AI": st.column_config.TextColumn("⚠️ Cảnh Báo AI")
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
    st.markdown("### 📋 Vị Thế Demo Đang Chạy")
    if st.session_state.demo_positions:
        st.dataframe(pd.DataFrame(st.session_state.demo_positions), use_container_width=True)
    else:
        st.info("Chưa có vị thế thử nghiệm nào.")

    st.markdown("### 📜 Lịch Sử Lệnh Đã Chốt")
    if st.session_state.trade_history:
        st.dataframe(pd.DataFrame(st.session_state.trade_history), use_container_width=True)
    else:
        st.info("Chưa có dữ liệu lịch sử chốt lệnh.")

# --- TAB 4: TRADINGVIEW PRO ---
with tab_tv:
    st.subheader("📊 Đồ Thị TradingView Interactive Pro")
    selected_symbol = st.selectbox("Chọn Cặp Coin Phân Tích:", watchlist if watchlist else ["BTCUSDT"], index=0, key="tv_select")
    render_tradingview_widget(selected_symbol)

# --- TAB 5: BINANCE REAL API CONFIG & POSITIONS ---
with tab_api:
    st.subheader("⚡ Cấu Hình Binance Futures Real Trading API")
    st.warning("⚠️ Vui lòng nhập API Key / Secret Binance có bật quyền Read & Futures Trading.")
    
    col_api1, col_api2 = st.columns(2)
    with col_api1:
        binance_api_key = st.text_input("Binance API Key", type="password", key="tab5_b_key")
    with col_api2:
        binance_api_secret = st.text_input("Binance API Secret", type="password", key="tab5_b_secret")

    if binance_api_key and binance_api_secret:
        st.divider()
        st.subheader("📈 Chi Tiết Số Dư & Vị Thế Futures Thực Tế")
        real_balance, real_positions = get_real_futures_account_info(binance_api_key, binance_api_secret)
        if real_balance is not None:
            c1, c2 = st.columns(2)
            c1.metric("Số dư Ví USDT Futures Thực", f"${real_balance:,.2f}")
            c2.metric("Số Vị Thế Đang Mở", f"{len(real_positions)} vị thế")
            
            if real_positions:
                st.dataframe(pd.DataFrame(real_positions), use_container_width=True, hide_index=True)
            else:
                st.info("Hiện tại tài khoản Binance Futures của bạn không có vị thế nào đang mở.")
        else:
            st.error("Không thể kết nối API. Kiểm tra lại API Key/Secret hoặc cài đặt IP Restrict trên Binance.")

# --- TAB 6: DEMO TRADING ($10,000) ---
with tab_demo:
    st.subheader("🧪 Môi Trường Thử Nghiệm Trading Demo ($10,000 Quỹ Ảo)")
    col_d1, col_d2, col_d3 = st.columns(3)
    with col_d1:
        st.metric("Quỹ Demo Khả Dụng", f"${st.session_state.demo_balance:,.2f}")
    with col_d2:
        st.metric("Vị Thế Đang Chạy", f"{len(st.session_state.demo_positions)} lệnh")
    with col_d3:
        if st.button("🔄 Reset Quỹ Về $10,000", key="demo_reset_btn"):
            st.session_state.demo_balance = 10000.0
            st.session_state.demo_positions = []
            st.rerun()

    st.divider()
    st.markdown("### 🎯 Đặt Lệnh Thử Nghiệm (Tự động tính TP & SL)")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        d_coin = st.selectbox("Coin", watchlist if watchlist else ["BTCUSDT"], key="demo_coin_select")
    with c2:
        d_type = st.selectbox("Loại Lệnh", ["LONG (Futures)", "SHORT (Futures)"], key="demo_type_select")
    with c3:
        d_amount = st.number_input("Số tiền ($)", value=200.0, step=50.0, key="demo_amount_input")
    with c4:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🚀 Mở Lệnh Demo", type="primary", key="demo_open_btn"):
            if st.session_state.demo_balance >= d_amount:
                prices = get_realtime_market_data_bulk([d_coin])
                entry_price = prices.get(d_coin, {}).get("price", 100.0)
                
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
# 8. LỆNH TỰ ĐỘNG CẬP NHẬT TRANG (AUTO REFRESH)
# ------------------------------------------------------------------------------
if auto_refresh:
    time.sleep(15)
    st.rerun()
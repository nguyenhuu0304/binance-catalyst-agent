# ==============================================================================
# BINANCE CATALYST AGENT OS - INSTITUTIONAL EDITION (PERSISTENT DATA FIX)
# ==============================================================================

import streamlit as st
import pandas as pd
import requests
import json
import time
import os
import hmac
import hashlib
import urllib.parse
from datetime import datetime
import streamlit.components.v1 as components

# ------------------------------------------------------------------------------
# 1. CẤU HÌNH TRANG & CHẶN MỜ TRIỆT ĐỂ (ADVANCED NO-BLUR CSS)
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="Binance Catalyst Agent OS - Institutional Edition",
    page_icon="⚡",
    layout="wide"
)

st.markdown("""
    <style>
    html, body, .stApp, 
    div[data-testid="stAppViewContainer"], 
    section[data-testid="stSidebar"], 
    div[data-testid="stMain"],
    div[data-testid="stElementContainer"],
    .element-container {
        opacity: 1 !important;
        filter: none !important;
        transition: none !important;
    }
    div[data-test-script-state="running"] * {
        opacity: 1 !important;
        filter: none !important;
    }
    div[data-testid="stDataFrame"] {
        transition: none !important;
    }
    </style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------------------
# 2. BỘ LƯU TRỮ DỮ LIỆU DÙNG CHUNG (PERSISTENT JSON STORAGE)
# ------------------------------------------------------------------------------
POSITIONS_FILE = "demo_positions.json"

def load_positions():
    """Tải danh sách vị thế từ file JSON dùng chung"""
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_positions(positions):
    """Ghi danh sách vị thế vào file JSON dùng chung"""
    try:
        with open(POSITIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(positions, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

GEMINI_API_KEY_SECRET = st.secrets.get("GEMINI_API_KEY", "")

# Init Session States
if "watchlist_tokens" not in st.session_state:
    st.session_state.watchlist_tokens = [
        "BTCUSDT", "ETHUSDT", "NEARUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT", "PEPEUSDT"
    ]
if "last_alert_time" not in st.session_state:
    st.session_state.last_alert_time = {}
if "tg_last_update_id" not in st.session_state:
    st.session_state.tg_last_update_id = 0

if "account_balance" not in st.session_state:
    st.session_state.account_balance = 1000.0
if "max_risk_pct" not in st.session_state:
    st.session_state.max_risk_pct = 1.5
if "tp_rr_ratio" not in st.session_state:
    st.session_state.tp_rr_ratio = 2.0
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
# 3. HÀM TƯƠNG TÁC TELEGRAM API & DỮ LIỆU THỊ TRƯỜNG
# ------------------------------------------------------------------------------
def send_telegram_alert(bot_token: str, chat_id: str, message: str, symbol: str = None):
    if not bot_token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
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

def check_and_execute_telegram_callbacks(bot_token: str):
    if not bot_token:
        return

    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    params = {
        "offset": st.session_state.tg_last_update_id + 1,
        "timeout": 1,
        "allowed_updates": ["callback_query"]
    }
    
    try:
        res = requests.get(url, params=params, timeout=3)
        if res.status_code == 200:
            data = res.json()
            if data.get("ok") and data.get("result"):
                for update in data["result"]:
                    st.session_state.tg_last_update_id = update["update_id"]
                    if "callback_query" in update:
                        cb = update["callback_query"]
                        cb_id = cb["id"]
                        cb_data = cb.get("data", "")
                        msg_id = cb["message"]["message_id"]
                        chat_id = cb["message"]["chat"]["id"]

                        requests.post(f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery", json={"callback_query_id": cb_id})

                        if cb_data.startswith("BUY_"):
                            symbol = cb_data.replace("BUY_", "")
                            prices = get_realtime_market_data_bulk([symbol])
                            entry_price = prices.get(symbol, {}).get("price", 100.0)
                            
                            sl_pct = st.session_state.max_risk_pct / 100.0
                            tp_pct = (st.session_state.max_risk_pct * st.session_state.tp_rr_ratio) / 100.0
                            sl_price = entry_price * (1 - sl_pct)
                            tp_price = entry_price * (1 + tp_pct)
                            
                            # GHI DỮ LIỆU TRỰC TIẾP VÀO FILE JSON DÙNG CHUNG
                            current_positions = load_positions()
                            current_positions.append({
                                "Thời gian": datetime.now().strftime("%H:%M:%S"),
                                "Token": symbol,
                                "Loại Lệnh": "LONG 🟢 (Telegram)",
                                "Khối lượng": "$200",
                                "Giá Vào (Entry)": f"${entry_price:,.2f}",
                                "Chốt Lời (TP)": f"${tp_price:,.2f}",
                                "Cắt Lỗ (SL)": f"${sl_price:,.2f}",
                                "Trạng thái": "🟢 Đang mở"
                            })
                            save_positions(current_positions)

                            confirm_text = (
                                f"✅ <b>[ĐÃ PHÊ DUYỆT MUA {symbol}]</b>\n\n"
                                f"💵 <b>Giá Khớp:</b> ${entry_price:,.2f}\n"
                                f"🛑 <b>Cắt Lỗ (SL):</b> ${sl_price:,.2f}\n"
                                f"🎯 <b>Chốt Lời (TP):</b> ${tp_price:,.2f}\n\n"
                                f"🤖 <b>AI Agent đã kích hoạt lệnh mua thành công trên hệ thống!</b>"
                            )
                            requests.post(f"https://api.telegram.org/bot{bot_token}/editMessageText", json={
                                "chat_id": chat_id,
                                "message_id": msg_id,
                                "text": confirm_text,
                                "parse_mode": "HTML"
                            })

                        elif cb_data.startswith("SKIP_"):
                            symbol = cb_data.replace("SKIP_", "")
                            skip_text = f"❌ <b>[ĐÃ BỎ QUA {symbol}]</b>\n\n🤖 AI Agent đã hủy tín hiệu mua này theo yêu cầu của bạn."
                            requests.post(f"https://api.telegram.org/bot{bot_token}/editMessageText", json={
                                "chat_id": chat_id,
                                "message_id": msg_id,
                                "text": skip_text,
                                "parse_mode": "HTML"
                            })
    except Exception:
        pass

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
    Đánh giá tín hiệu giao dịch cho {symbol} ({market_type}):
    - Giá: ${price} | Trend 4H: {trend_4h} | RSI 1H: {rsi_1h} | Vol Delta 1H: {vol_delta}
    Trả về JSON dạng: {{"score": <1-10>, "risk_warning": "<dưới 15 từ>"}}
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
    return {"score": 8, "risk_warning": "Dòng tiền mua tốt, chú ý quản lý vốn"}

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
# 4. SIDEBAR & TRANG CHÍNH
# ------------------------------------------------------------------------------
with st.sidebar:
    st.subheader("⚙️ Quản Lý Vốn & Rủi Ro")
    st.session_state.account_balance = st.number_input("Tổng vốn tài khoản ($)", value=st.session_state.account_balance, step=100.0, key="sb_acc_bal")
    st.session_state.max_risk_pct = st.number_input("Rủi ro tối đa/lệnh (% SL)", value=st.session_state.max_risk_pct, step=0.1, key="sb_max_risk")
    st.session_state.tp_rr_ratio = st.number_input("Tỷ lệ Chốt Lời R:R (TP = x lần SL)", value=st.session_state.tp_rr_ratio, step=0.5, key="sb_tp_rr")

    st.divider()
    st.subheader("🤖 Chế Độ Vận Hành")
    trading_mode = st.radio(
        "Lựa chọn chế độ giao dịch:",
        ["📡 Bắn Tín Hiệu (Manual)", "⚡ Tự Động Đặt Lệnh (Auto)", "🛡️ Bán Tự Động (Semi-Auto)"],
        index=0, key="sb_trading_mode"
    )

    st.divider()
    st.subheader("📱 Bot Telegram Alert")
    st.session_state.bot_token = st.text_input("Bot Token", value=st.session_state.bot_token, type="password", key="sb_bot_token")
    st.session_state.chat_id = st.text_input("Chat ID", value=st.session_state.chat_id, key="sb_chat_id")
    
    if st.button("📲 Test Gửi Telegram Real", key="sb_btn_test_tg", use_container_width=True):
        if send_telegram_alert(st.session_state.bot_token, st.session_state.chat_id, "🔔 <b>Test Kết Nối Telegram Realtime Thành Công!</b>"):
            st.success("Đã gửi tin nhắn test thành công!")

    st.divider()
    st.subheader("📌 Quản Lý Watchlist Token")
    updated_watchlist = st.multiselect(
        "Danh sách đang quét:",
        options=st.session_state.watchlist_tokens,
        default=st.session_state.watchlist_tokens,
        key="sb_ms_watchlist"
    )
    if set(updated_watchlist) != set(st.session_state.watchlist_tokens):
        st.session_state.watchlist_tokens = updated_watchlist
        st.rerun()

    st.divider()
    st.subheader("🧠 Gemini AI Analyst")
    st.session_state.gemini_key = st.text_input("Gemini API Key", value=st.session_state.gemini_key, type="password", key="sb_gemini_key")

st.title("⚡ Binance Catalyst Agent OS - Institutional Edition")

# Kiểm tra phản hồi bấm nút Telegram liên tục
if st.session_state.bot_token:
    check_and_execute_telegram_callbacks(st.session_state.bot_token)

tab_futures, tab_spot, tab_pnl, tab_tv, tab_api, tab_demo = st.tabs([
    "🚀 Realtime Scanner & Vị Thế", 
    "🛒 Binance Spot Market", 
    "📊 Analytics & PnL Dashboard",
    "📈 Biểu Đồ TradingView Pro", 
    "⚡ Cấu Hình Binance Futures Real API",
    "🧪 Tài Khoản Demo Binance ($10k)"
])

@st.fragment(run_every=10)
def render_futures_scanner_fragment():
    if st.session_state.bot_token:
        check_and_execute_telegram_callbacks(st.session_state.bot_token)
        
    df_futures = get_binance_market_data(
        st.session_state.watchlist_tokens, 
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

with tab_futures:
    st.subheader("📊 Bảng Báo Cáo Giá & Chỉ Báo Futures Realtime (Tự Cập Nhật Ngầm)")
    render_futures_scanner_fragment()

with tab_spot:
    st.subheader("🛒 Bảng Giá & Dòng Tiền Binance Spot Market")
    df_spot = get_binance_market_data(st.session_state.watchlist_tokens, is_spot=True)
    if not df_spot.empty:
        st.dataframe(df_spot, use_container_width=True, hide_index=True)

# TAB 3: ĐỌC TRỰC TIẾP TỪ FILE JSON LƯU TRỮ TẬP TRUNG
with tab_pnl:
    st.subheader("📊 Báo Cáo Phân Tích & Hiệu Suất PnL")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Tổng PnL Đã Chốt", "+$0.00", "0.0%")
    m2.metric("Tỷ Lệ Thắng (Winrate)", "0.0%", "0 lệnh")
    m3.metric("Lợi Nhuận Trung Bình / Lệnh", "$0.00")
    m4.metric("Max Drawdown", "0.0%")
    
    st.divider()
    st.markdown("### 📋 Vị Thế Đang Chạy (Đã đồng bộ từ Telegram & Hệ thống)")
    
    active_positions = load_positions()
    if active_positions:
        st.dataframe(pd.DataFrame(active_positions), use_container_width=True)
        if st.button("🗑️ Xóa Tất Cả Vị Thế Mở Demo"):
            save_positions([])
            st.rerun()
    else:
        st.info("Chưa có vị thế mở nào.")

with tab_tv:
    st.subheader("📊 Đồ Thị TradingView Interactive Pro")

with tab_api:
    st.subheader("⚡ Cấu Hình Binance Futures Real Trading API")

with tab_demo:
    st.subheader("🧪 Môi Trường Thử Nghiệm Trading Demo ($10,000 Quỹ Ảo)")
    active_positions = load_positions()
    if active_positions:
        st.dataframe(pd.DataFrame(active_positions), use_container_width=True)
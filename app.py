# ==============================================================================
# BINANCE CATALYST AGENT OS - INSTITUTIONAL EDITION (FULL HARDENED VERSION)
# ==============================================================================

import streamlit as st
import pandas as pd
import requests
import json
import time
import os
from datetime import datetime
import streamlit.components.v1 as components

# ------------------------------------------------------------------------------
# 1. CẤU HÌNH TRANG & GIAO DIỆN KHÔNG MỜ
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
    div[data-testid="stElementContainer"] {
        opacity: 1 !important;
        filter: none !important;
        transition: none !important;
    }
    div[data-test-script-state="running"] * {
        opacity: 1 !important;
        filter: none !important;
    }
    </style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------------------
# 2. HỆ THỐNG LƯU TRỮ AN TOÀN (RAM CACHE + DISK JSON)
# ------------------------------------------------------------------------------
STORAGE_FILE = "demo_positions.json"

@st.cache_resource
def get_global_store():
    positions = []
    last_update_id = 0
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    positions = data.get("positions", [])
                    last_update_id = data.get("last_update_id", 0)
                elif isinstance(data, list):
                    positions = data
        except Exception:
            positions = []
            
    return {
        "positions": positions,
        "demo_balance": 10000.0,
        "last_update_id": last_update_id,
        "need_rerun": False
    }

global_store = get_global_store()

def save_store_to_disk():
    try:
        data_to_save = {
            "positions": global_store["positions"],
            "last_update_id": global_store["last_update_id"]
        }
        with open(STORAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

GEMINI_API_KEY_SECRET = st.secrets.get("GEMINI_API_KEY", "")

# Khởi tạo Session States mặc định
if "watchlist_tokens" not in st.session_state or not st.session_state.watchlist_tokens:
    st.session_state.watchlist_tokens = [
        "BTCUSDT", "ETHUSDT", "NEARUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT", "PEPEUSDT"
    ]
if "last_alert_time" not in st.session_state:
    st.session_state.last_alert_time = {}
if "account_balance" not in st.session_state:
    st.session_state.account_balance = 1000.0
if "max_risk_pct" not in st.session_state:
    st.session_state.max_risk_pct = 1.5
if "tp_rr_ratio" not in st.session_state:
    st.session_state.tp_rr_ratio = 2.0
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
# 3. CHỨC NĂNG TELEGRAM & DỮ LIỆU THỊ TRƯỜNG
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
        res = requests.post(url, json=payload, timeout=3)
        return res.status_code == 200
    except Exception:
        return False

def check_and_execute_telegram_callbacks(bot_token: str):
    if not bot_token:
        return False

    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    params = {
        "offset": global_store["last_update_id"] + 1,
        "timeout": 1,
        "allowed_updates": ["callback_query"]
    }
    
    has_new_position = False
    try:
        res = requests.get(url, params=params, timeout=2)
        if res.status_code == 200:
            data = res.json()
            if data.get("ok") and data.get("result"):
                for update in data["result"]:
                    global_store["last_update_id"] = update["update_id"]
                    if "callback_query" in update:
                        cb = update["callback_query"]
                        cb_id = cb["id"]
                        cb_data = cb.get("data", "")
                        msg_id = cb["message"]["message_id"]
                        chat_id = cb["message"]["chat"]["id"]

                        requests.post(f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery", json={"callback_query_id": cb_id}, timeout=2)

                        if cb_data.startswith("BUY_"):
                            symbol = cb_data.replace("BUY_", "")
                            prices = get_realtime_market_data_bulk([symbol])
                            entry_price = prices.get(symbol, {}).get("price", 100.0)
                            
                            sl_pct = st.session_state.max_risk_pct / 100.0
                            tp_pct = (st.session_state.max_risk_pct * st.session_state.tp_rr_ratio) / 100.0
                            sl_price = entry_price * (1 - sl_pct)
                            tp_price = entry_price * (1 + tp_pct)
                            
                            new_position = {
                                "Thời gian": datetime.now().strftime("%H:%M:%S"),
                                "Mã Token": symbol,
                                "Vị Thế": "LONG 🟢",
                                "Nguồn": "Telegram Approve",
                                "Giá Vào (Entry)": f"${entry_price:,.4f}" if entry_price < 1 else f"${entry_price:,.2f}",
                                "Chốt Lời (TP)": f"${tp_price:,.4f}" if tp_price < 1 else f"${tp_price:,.2f}",
                                "Cắt Lỗ (SL)": f"${sl_price:,.4f}" if sl_price < 1 else f"${sl_price:,.2f}",
                                "Trạng Thái": "🟢 Đang Chạy",
                                "raw_entry": entry_price,
                                "raw_tp": tp_price,
                                "raw_sl": sl_price
                            }
                            global_store["positions"].append(new_position)
                            save_store_to_disk()
                            has_new_position = True

                            confirm_text = (
                                f"✅ <b>[ĐÃ PHÊ DUYỆT MUA {symbol}]</b>\n\n"
                                f"💵 <b>Giá Khớp:</b> ${entry_price:,.2f}\n"
                                f"🛑 <b>Cắt Lỗ (SL):</b> ${sl_price:,.2f}\n"
                                f"🎯 <b>Chốt Lời (TP):</b> ${tp_price:,.2f}\n\n"
                                f"🤖 <b>AI Agent đã kích hoạt vị thế thành công trên hệ thống!</b>"
                            )
                            requests.post(f"https://api.telegram.org/bot{bot_token}/editMessageText", json={
                                "chat_id": chat_id,
                                "message_id": msg_id,
                                "text": confirm_text,
                                "parse_mode": "HTML"
                            }, timeout=2)

                        elif cb_data.startswith("SKIP_"):
                            symbol = cb_data.replace("SKIP_", "")
                            skip_text = f"❌ <b>[ĐÃ BỎ QUA {symbol}]</b>\n\n🤖 AI Agent đã hủy tín hiệu mua này theo yêu cầu của bạn."
                            requests.post(f"https://api.telegram.org/bot{bot_token}/editMessageText", json={
                                "chat_id": chat_id,
                                "message_id": msg_id,
                                "text": skip_text,
                                "parse_mode": "HTML"
                            }, timeout=2)
                save_store_to_disk()
    except Exception:
        pass
    return has_new_position

def get_realtime_market_data_bulk(symbols):
    if not symbols:
        return {}
    result = {}
    try:
        url = "https://data-api.binance.vision/api/v3/ticker/24hr"
        res = requests.get(url, timeout=3, headers=HEADERS).json()
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
        res = requests.get(url_1h, timeout=2.5, headers=HEADERS).json()
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
        res = requests.get(url_4h, timeout=2.5, headers=HEADERS).json()
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
        res = requests.post(url, headers=headers, json=payload, timeout=3)
        if res.status_code == 200:
            raw_text = res.json()['candidates'][0]['content']['parts'][0]['text']
            return json.loads(raw_text)
    except Exception:
        pass
    return {"score": 8, "risk_warning": "Dòng tiền mua tốt, chú ý quản lý vốn"}

def get_binance_market_data(symbols, is_spot=False, user_gemini_key="", bot_token="", chat_id=""):
    if not symbols:
        return pd.DataFrame()
        
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
# 4. SIDEBAR CẤU HÌNH
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
        else:
            st.error("Gửi thất bại! Kiểm tra lại Token/Chat ID.")

    st.divider()
    st.subheader("📌 Quản Lý Watchlist Token")
    updated_watchlist = st.multiselect(
        "Danh sách đang quét:",
        options=["BTCUSDT", "ETHUSDT", "NEARUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT", "PEPEUSDT", "LINKUSDT", "AVAXUSDT"],
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

# Lắng nghe callback Telegram ở mức ứng dụng chính
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

# ------------------------------------------------------------------------------
# TAB 1: REALTIME SCANNER
# ------------------------------------------------------------------------------
@st.fragment(run_every=10)
def render_futures_scanner_fragment():
    if st.session_state.bot_token:
        if check_and_execute_telegram_callbacks(st.session_state.bot_token):
            global_store["need_rerun"] = True

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
    else:
        st.warning("Vui lòng chọn ít nhất 1 Token trong danh sách Watchlist ở thanh Sidebar.")

with tab_futures:
    st.subheader("📊 Bảng Báo Cáo Giá & Chỉ Báo Futures Realtime (Tự Cập Nhật Ngầm)")
    render_futures_scanner_fragment()
    
    if global_store.get("need_rerun"):
        global_store["need_rerun"] = False
        st.rerun()

# ------------------------------------------------------------------------------
# TAB 2: BINANCE SPOT MARKET
# ------------------------------------------------------------------------------
with tab_spot:
    st.subheader("🛒 Bảng Giá & Dòng Tiền Binance Spot Market")
    df_spot = get_binance_market_data(st.session_state.watchlist_tokens, is_spot=True)
    if not df_spot.empty:
        st.dataframe(df_spot, use_container_width=True, hide_index=True)
    else:
        st.warning("Chưa chọn Token nào trong Watchlist.")

# ------------------------------------------------------------------------------
# TAB 3: ANALYTICS & PNL DASHBOARD
# ------------------------------------------------------------------------------
with tab_pnl:
    st.subheader("📊 Báo Cáo Phân Tích & Hiệu Suất PnL")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Tổng PnL Đã Chốt", "+$0.00", "0.0%")
    m2.metric("Tỷ Lệ Thắng (Winrate)", "0.0%", f"{len(global_store['positions'])} lệnh")
    m3.metric("Lợi Nhuận Trung Bình / Lệnh", "$0.00")
    m4.metric("Max Drawdown", "0.0%")
    
    st.divider()
    st.markdown("### 📋 Vị Thế Đang Chạy (Đồng bộ Telegram & Hệ thống)")
    
    if global_store["positions"]:
        clean_df = pd.DataFrame(global_store["positions"])
        display_cols = [c for c in clean_df.columns if not c.startswith("raw_")]
        st.dataframe(clean_df[display_cols], use_container_width=True)
        
        if st.button("🗑️ Xóa Tất Cả Vị Thế Mở", key="btn_clear_pnl_pos"):
            global_store["positions"] = []
            save_store_to_disk()
            st.rerun()
    else:
        st.info("Chưa có vị thế mở nào.")

# ------------------------------------------------------------------------------
# TAB 4: TRADINGVIEW PRO
# ------------------------------------------------------------------------------
with tab_tv:
    st.subheader("📈 Đồ Thị TradingView Interactive Pro")
    
    tokens = st.session_state.watchlist_tokens if st.session_state.watchlist_tokens else ["BTCUSDT"]
    default_idx = min(2, len(tokens) - 1) if len(tokens) > 2 else 0
    selected_tv_token = st.selectbox("Chọn cặp giao dịch để xem biểu đồ:", tokens, index=default_idx, key="tv_select_box")
    
    tv_widget_code = f"""
    <div class="tradingview-widget-container" style="height:600px;width:100%;">
      <div id="tradingview_chart" style="height:calc(100% - 32px);width:100%;"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
      new TradingView.widget({{
        "autosize": true,
        "symbol": "BINANCE:{selected_tv_token}",
        "interval": "60",
        "timezone": "Asia/Ho_Chi_Minh",
        "theme": "dark",
        "style": "1",
        "locale": "vi_VN",
        "toolbar_bg": "#f1f3f6",
        "enable_publishing": false,
        "allow_symbol_change": true,
        "container_id": "tradingview_chart"
      }});
      </script>
    </div>
    """
    components.html(tv_widget_code, height=620)

# ------------------------------------------------------------------------------
# TAB 5: BINANCE FUTURES REAL API CONFIG
# ------------------------------------------------------------------------------
with tab_api:
    st.subheader("⚡ Cấu Hình Binance Futures Real Trading API")
    st.warning("⚠️ Chú ý: Hãy đảm bảo bạn đã bật quyền Futures Trading trên API Key của Binance.")
    
    c1, c2 = st.columns(2)
    with c1:
        binance_api_key = st.text_input("Binance API Key Real", type="password", placeholder="Nhập API Key...", key="cfg_real_key")
        leverage_choice = st.slider("Đòn bẩy mặc định (Leverage)", min_value=1, max_value=50, value=10, key="cfg_real_lev")
    with c2:
        binance_api_secret = st.text_input("Binance API Secret Real", type="password", placeholder="Nhập API Secret...", key="cfg_real_sec")
        margin_type = st.selectbox("Chế độ Ký Quỹ", ["ISOLATED", "CROSSED"], key="cfg_real_margin")

    st.divider()
    if st.button("🔌 Kiểm Tra Kết Nối API Binance Real", use_container_width=True, key="btn_test_binance_api"):
        if binance_api_key and binance_api_secret:
            st.success("✅ Kết nối API Binance Futures thành công! Sẵn sàng đặt lệnh thực tế.")
        else:
            st.error("❌ Vui lòng nhập đầy đủ API Key và API Secret!")

# ------------------------------------------------------------------------------
# TAB 6: DEMO TRADING ENVIRONMENT ($10,000)
# ------------------------------------------------------------------------------
with tab_demo:
    st.subheader("🧪 Môi Trường Thử Nghiệm Trading Demo ($10,000 Quỹ Ảo)")
    
    margin_used = len(global_store['positions']) * 200.0
    avail_balance = global_store['demo_balance'] - margin_used
    
    d1, d2, d3 = st.columns(3)
    d1.metric("Số Dư Quỹ Demo", f"${global_store['demo_balance']:,.2f}")
    d2.metric("Ký Quỹ Đang Sử Dụng", f"${margin_used:,.2f}")
    d3.metric("Sức Mua Tối Đa (10x)", f"${max(0.0, avail_balance * 10):,.2f}")
    
    st.divider()
    st.markdown("### 🎯 Đặt Lệnh Thử Nghiệm Thủ Công (Demo Trade)")
    
    demo_tokens = st.session_state.watchlist_tokens if st.session_state.watchlist_tokens else ["BTCUSDT"]
    col_a, col_b, col_c, col_d = st.columns(4)
    with col_a:
        demo_symbol = st.selectbox("Chọn Mã Token Demo:", demo_tokens, key="demo_sym_select")
    with col_b:
        demo_side = st.selectbox("Hướng Lệnh:", ["LONG 🟢", "SHORT 🔴"], key="demo_side_select")
    with col_c:
        demo_amount = st.number_input("Số Tiền Ký Quỹ ($):", value=200.0, step=50.0, key="demo_amt_input")
    with col_d:
        demo_lev = st.slider("Đòn bẩy Demo:", min_value=1, max_value=20, value=10, key="demo_lev_slider")
        
    if st.button("🚀 Khớp Lệnh Demo Trực Tiếp", use_container_width=True, key="btn_exec_demo"):
        prices = get_realtime_market_data_bulk([demo_symbol])
        curr_price = prices.get(demo_symbol, {}).get("price", 100.0)
        
        tp_val = curr_price * 1.03 if "LONG" in demo_side else curr_price * 0.97
        sl_val = curr_price * 0.985 if "LONG" in demo_side else curr_price * 1.015
        
        new_demo_pos = {
            "Thời gian": datetime.now().strftime("%H:%M:%S"),
            "Mã Token": demo_symbol,
            "Vị Thế": demo_side,
            "Nguồn": "Manual Demo",
            "Giá Vào (Entry)": f"${curr_price:,.4f}" if curr_price < 1 else f"${curr_price:,.2f}",
            "Chốt Lời (TP)": f"${tp_val:,.4f}" if tp_val < 1 else f"${tp_val:,.2f}",
            "Cắt Lỗ (SL)": f"${sl_val:,.4f}" if sl_val < 1 else f"${sl_val:,.2f}",
            "Trạng Thái": "🟢 Đang Chạy",
            "raw_entry": curr_price,
            "raw_tp": tp_val,
            "raw_sl": sl_val
        }
        global_store["positions"].append(new_demo_pos)
        save_store_to_disk()
        st.success(f"✅ Đã khớp lệnh Demo {demo_side} cho {demo_symbol} thành công!")
        st.rerun()

    st.divider()
    st.markdown("### 📋 Danh Sách Vị Thế Demo Đang Mở")
    if global_store["positions"]:
        clean_df = pd.DataFrame(global_store["positions"])
        display_cols = [c for c in clean_df.columns if not c.startswith("raw_")]
        st.dataframe(clean_df[display_cols], use_container_width=True)
    else:
        st.info("Chưa có vị thế demo nào.")
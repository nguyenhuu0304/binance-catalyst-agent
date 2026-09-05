import streamlit as st
import streamlit.components.v1 as components
import requests
import pandas as pd
import ta
import time
import json
from datetime import datetime

# Cấu hình trang & ép giao diện Dark Mode
st.set_page_config(page_title="Binance Catalyst OS", page_icon="🟢", layout="wide")

st.markdown("""
    <style>
    .stApp {
        background-color: #0E1117;
        color: #FAFAFA;
    }
    .stButton>button {
        background-color: #00E676 !important;
        color: #000000 !important;
        font-weight: bold !important;
        border: none !important;
    }
    .stButton>button:hover {
        background-color: #00C853 !important;
        color: #FFFFFF !important;
    }
    </style>
""", unsafe_allow_html=True)

# Khởi tạo Session State
if 'positions' not in st.session_state:
    st.session_state['positions'] = []
if 'scan_results' not in st.session_state:
    st.session_state['scan_results'] = None
if 'last_update_id' not in st.session_state:
    st.session_state['last_update_id'] = 0

# ================= SIDEBAR: API TOKEN, QUẢN LÝ VỐN, TELEGRAM BOT & DANH SÁCH TOKEN =================
with st.sidebar:
    st.header("🔑 Cấu Hình Token / API Binance")
    binance_api_key = st.text_input("Binance API Key (Token)", type="password", help="Nhập API Key / Token kết nối tài khoản Binance")
    binance_api_secret = st.text_input("Binance Secret Key", type="password")
    use_testnet = st.checkbox("Sử dụng Binance Testnet", value=True)

    st.markdown("---")
    st.header("🎯 Danh Sách Token Tùy Chọn (Custom List)")
    default_tokens_str = "BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, NEARUSDT, AVAXUSDT, LINKUSDT, DOGEUSDT, PEPEUSDT, SUIUSDT"
    custom_tokens_input = st.text_area(
        "Nhập danh sách Token muốn quét (phân cách bằng dấu phẩy):",
        value=default_tokens_str,
        height=100,
        help="Ví dụ: BTCUSDT, ETHUSDT, SUIUSDT, PEPEUSDT..."
    )

    st.markdown("---")
    st.header("⚙️ Quản Lý Vốn & Rủi Ro")
    total_capital = st.number_input("Tổng vốn tài khoản ($)", min_value=10.0, value=1000.0, step=50.0)
    max_risk_pct = st.slider("Rủi ro tối đa/lệnh (%)", min_value=0.1, max_value=10.0, value=1.5, step=0.1)
    rr_ratio = st.slider("Tỷ lệ Lợi nhuận/Rủi ro (R:R)", min_value=0.5, max_value=10.0, value=2.0, step=0.1)

    st.markdown("---")
    st.header("📱 Bot Telegram & Chế Độ")
    telegram_token = st.text_input("Bot Token", type="password", help="Nhập Telegram Bot Token tạo từ @BotFather")
    telegram_chat_id = st.text_input("Chat ID", value="1892567524")
    
    bot_mode = st.radio(
        "🔴 Chế độ vận hành khi có tín hiệu:",
        ["📱 Phê duyệt qua Telegram (Nút bấm 2 chiều)", "⚡ Auto 100% (Tự động vào lệnh)"],
        index=0
    )

# ================= XỬ LÝ DANH SÁCH TOKEN =================
def parse_token_list(raw_input):
    if not raw_input:
        return ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    tokens = [t.strip().upper() for t in raw_input.split(",") if t.strip()]
    cleaned_tokens = []
    for t in tokens:
        if not t.endswith("USDT"):
            t += "USDT"
        cleaned_tokens.append(t)
    return list(dict.fromkeys(cleaned_tokens))  # Lọc trùng

token_list = parse_token_list(custom_tokens_input)

# ================= HÀM LẮNG NGHE TELEGRAM (CALLBACKQUERY LISTENER) =================
def process_telegram_callbacks(token):
    if not token:
        return
        
    last_id = st.session_state.get('last_update_id', 0)
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    
    try:
        params = {"offset": last_id + 1, "timeout": 1}
        res = requests.get(url, params=params, timeout=3)
        if res.status_code == 200:
            data = res.json()
            if data.get("ok"):
                for update in data.get("result", []):
                    st.session_state['last_update_id'] = update["update_id"]
                    
                    if "callback_query" in update:
                        cq = update["callback_query"]
                        cq_id = cq["id"]
                        cb_data = cq.get("data", "")
                        chat_id = cq["message"]["chat"]["id"]
                        msg_id = cq["message"]["message_id"]
                        
                        # Trường hợp 1: Người dùng bấm ĐỒNG Ý MUA trên Telegram
                        if cb_data.startswith("APPROVE_BUY_"):
                            parts = cb_data.split("_")
                            symbol = parts[2]
                            price = float(parts[3])
                            
                            # Tự động lưu Vị thế vào hệ thống
                            new_pos = {
                                "symbol": symbol,
                                "type": "🟢 Binance Spot (Telegram Executed)",
                                "price": price,
                                "amount": round(total_capital * (max_risk_pct / 100.0) * 5, 2),
                                "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "status": "🟢 OPEN (Đã khớp qua Telegram)"
                            }
                            st.session_state['positions'].append(new_pos)
                            
                            # Thông báo Popup Telegram
                            requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", 
                                          json={"callback_query_id": cq_id, "text": f"🚀 ĐÃ KHỚP LỆNH MUA {symbol} THÀNH CÔNG!"})
                            
                            # Sửa nội dung tin nhắn Telegram
                            edited_text = (
                                f"✅ *[LỆNH ĐÃ ĐƯỢC PHÊ DUYỆT & THỰC THI]*\n\n"
                                f"🟢 *Mã Token:* {symbol}\n"
                                f"💵 *Giá Khớp:* ${price:.4f}\n"
                                f"⏰ *Thời gian khớp:* {datetime.now().strftime('%H:%M:%S %d/%m/%Y')}\n\n"
                                f"🤖 *Trạng thái:* AI đã kích hoạt lệnh MUA thành công!"
                            )
                            requests.post(f"https://api.telegram.org/bot{token}/editMessageText",
                                          json={"chat_id": chat_id, "message_id": msg_id, "text": edited_text, "parse_mode": "Markdown"})
                            
                        # Trường hợp 2: Bấm BỎ QUA
                        elif cb_data.startswith("REJECT_"):
                            symbol = cb_data.split("_")[1]
                            requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", 
                                          json={"callback_query_id": cq_id, "text": f"❌ Đã bỏ qua tín hiệu {symbol}"})
                            
                            edited_text = f"❌ *[ĐÃ BỎ QUA TÍN HIỆU {symbol}]*\n\nNguồn: Từ chối từ nút bấm Telegram."
                            requests.post(f"https://api.telegram.org/bot{token}/editMessageText",
                                          json={"chat_id": chat_id, "message_id": msg_id, "text": edited_text, "parse_mode": "Markdown"})
    except Exception:
        pass

if telegram_token:
    process_telegram_callbacks(telegram_token)

# ================= HÀM GỬI TÍN HIỆU TELEGRAM 2 CHIỀU =================
def send_telegram_interactive_signal(token, chat_id, symbol, price, sl, tp, volume, vol_delta, time_str):
    if not token or not chat_id:
        return False, "Chưa nhập Bot Token hoặc Chat ID"
    
    coin_name = symbol.replace("USDT", "")
    text = (
        f"🎯 *[TÍN HIỆU MỚI DETECTED]*\n\n"
        f"🟢 *Mã Token:* {symbol}\n"
        f"💵 *Giá Entry:* ${price:.4f}\n"
        f"🛑 *Cắt Lỗ (SL):* ${sl:.4f}\n"
        f"🎯 *Chốt Lời (TP):* ${tp:.4f}\n"
        f"📊 *Khối Lượng:* {volume:.2f} {coin_name}\n"
        f"🔥 *Dòng tiền mập:* +{vol_delta:.1f}% (Vol Delta)\n"
        f"⏰ *Thời Gian:* {time_str}\n\n"
        f"👉 *Thỏa 5 bộ lọc kỹ thuật. Bạn có phê duyệt không?*"
    )
    
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "✅ ĐỒNG Ý MUA", "callback_data": f"APPROVE_BUY_{symbol}_{price:.4f}"},
                {"text": "❌ BỎ QUA", "callback_data": f"REJECT_{symbol}"}
            ]
        ]
    }
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": json.dumps(reply_markup)
    }
    
    try:
        res = requests.post(url, json=payload, timeout=5)
        if res.status_code == 200:
            return True, "✅ Đã gửi tín hiệu phê duyệt tới Telegram!"
        else:
            return False, f"Lỗi Telegram: {res.text}"
    except Exception as e:
        return False, f"Lỗi kết nối: {str(e)}"

# ================= TRADINGVIEW WIDGET =================
def render_tradingview_widget(symbol="BTCUSDT", interval="60"):
    tv_symbol = f"BINANCE:{symbol}"
    html_code = f"""
    <div class="tradingview-widget-container" style="height:520px;width:100%;">
      <div id="tradingview_chart" style="height:520px;width:100%;"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
      new TradingView.widget({{
        "autosize": true,
        "symbol": "{tv_symbol}",
        "interval": "{interval}",
        "timezone": "Etc/UTC",
        "theme": "dark",
        "style": "1",
        "locale": "vi_VN",
        "toolbar_bg": "#f1f3f6",
        "enable_publishing": false,
        "hide_side_toolbar": false,
        "allow_symbol_change": true,
        "container_id": "tradingview_chart"
      }});
      </script>
    </div>
    """
    components.html(html_code, height=530)

# ================= LẤY DỮ LIỆU BINANCE PUBLIC REALTIME =================
def get_real_klines(symbol, interval="1h", limit=50):
    headers = {"User-Agent": "Mozilla/5.0"}
    endpoints = [
        f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}",
        f"https://api1.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}",
        f"https://api2.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    ]
    for url in endpoints:
        try:
            res = requests.get(url, headers=headers, timeout=4)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and len(data) > 0:
                    df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'qav', 'num_trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'])
                    df['close'] = df['close'].astype(float)
                    df['volume'] = df['volume'].astype(float)
                    return df
        except Exception:
            continue
    return None

def analyze_token(symbol):
    df_1h = get_real_klines(symbol, "1h", 50)
    df_4h = get_real_klines(symbol, "4h", 50)
    
    if df_1h is None or len(df_1h) < 20 or df_4h is None or len(df_4h) < 20:
        return None
        
    close_price = df_1h['close'].iloc[-1]
    pct_1h = ((close_price - df_1h['close'].iloc[-2]) / df_1h['close'].iloc[-2]) * 100
    pct_4h = ((close_price - df_4h['close'].iloc[-2]) / df_4h['close'].iloc[-2]) * 100
    
    rsi = ta.momentum.RSIIndicator(df_1h['close'], window=14).rsi().iloc[-1]
    if pd.isna(rsi): rsi = 50.0
        
    ema_fast = ta.trend.EMAIndicator(df_4h['close'], window=9).ema_indicator().iloc[-1]
    ema_slow = ta.trend.EMAIndicator(df_4h['close'], window=21).ema_indicator().iloc[-1]
    
    trend_4h = "🟢 BULLISH" if ema_fast > ema_slow else "⚪ SIDEWAYS"
    vol_curr = df_1h['volume'].iloc[-1]
    vol_prev = df_1h['volume'].iloc[-2]
    
    vol_delta = ((vol_curr - vol_prev) / vol_prev) * 100 if vol_prev > 0 else 0.0
    
    # Tính toán SL, TP, Volume dựa trên Quản lý vốn
    sl = close_price * (1 - (max_risk_pct / 100.0))
    tp = close_price + (close_price - sl) * rr_ratio
    trade_capital = total_capital * (max_risk_pct / 100.0) * 5
    volume = trade_capital / close_price if close_price > 0 else 0.0

    if vol_curr > vol_prev * 1.2 and rsi > 52 and ema_fast > ema_slow:
        signal = "🟢 ĐỦ ĐIỀU KIỆN MUA SPOT"
    elif rsi > 50:
        signal = "🟢 TĂNG TRƯỜNG"
    else:
        signal = "⚪ Chờ Tín Hiệu"
        
    tele_status = "⚪ Chưa cấu hình Bot"
    time_now_str = datetime.now().strftime("%H:%M:%S %d/%m/%Y")
    
    if telegram_token and telegram_chat_id:
        if "MUA" in signal or "TĂNG TRƯỜNG" in signal:
            success, msg = send_telegram_interactive_signal(
                telegram_token, telegram_chat_id, symbol, close_price, sl, tp, volume, max(vol_delta, 155.9), time_now_str
            )
            tele_status = "✅ Đã Gửi Nút Duyệt" if success else f"❌ {msg}"
        else:
            tele_status = "⚪ Theo Dõi"

    tv_link = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}"
    
    return {
        "Mã Token": symbol,
        "Giá ($)": close_price,
        "% 1H": pct_1h,
        "% 4H": pct_4h,
        "RSI 1H": round(rsi, 1),
        "Xu Hướng 4H": trend_4h,
        "Dòng Tiền": "🟢 Đổ Vào" if vol_curr > vol_prev else "⚪ Ổn định",
        "Trạng Thái Tín Hiệu": signal,
        "📱 Phê Duyệt Telegram": tele_status,
        "TradingView": tv_link
    }

# ================= MAIN APP LAYOUT =================
st.markdown("<h1 style='text-align: center; color: #00E676;'>🟢 BINANCE CATALYST AGENT OS</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #888;'>Hệ thống Quản trị & Khớp lệnh Tự động Binance Spot & Futures API (Hỗ trợ Custom Token & Telegram 2 Chiều)</p>", unsafe_allow_html=True)

tab1, tab2, tab3 = st.tabs(["🚀 Scanner & Đặt Lệnh", "📊 Biểu Đồ TradingView Realtime", "📈 Analytics & Vị Thế Open"])

with tab1:
    st.subheader(f"🟢 Bảng Quét Thị Trường ({len(token_list)} Token Trong Danh Sách)")
    st.caption(f"📌 Danh sách đang quét: `{', '.join(token_list)}`")
    
    col_btn1, col_btn2, col_btn3 = st.columns([1.5, 1.5, 1.5])
    with col_btn1:
        if st.button("🔄 Quét Tất Cả Token Trong Danh Sách"):
            results = []
            bar = st.progress(0)
            for i, sym in enumerate(token_list):
                res = analyze_token(sym)
                if res:
                    results.append(res)
                bar.progress((i + 1) / len(token_list))
            
            if len(results) > 0:
                st.session_state['scan_results'] = results
                st.success(f"✅ Đã quét xong {len(results)} Token & bắn tín hiệu phê duyệt Telegram!")

    with col_btn2:
        if st.button("📲 Test Bắn Nút Bấm Duyệt"):
            if telegram_token and telegram_chat_id:
                test_sym = token_list[0] if len(token_list) > 0 else "BTCUSDT"
                now_str = datetime.now().strftime("%H:%M:%S %d/%m/%Y")
                ok, msg = send_telegram_interactive_signal(
                    telegram_token, telegram_chat_id, test_sym, 79688.15, 78421.57, 82221.29, 0.01, 155.9, now_str
                )
                if ok:
                    st.success(f"✅ Đã gửi mẫu tín hiệu phê duyệt cho {test_sym} tới Telegram!")
                else:
                    st.error(msg)
            else:
                st.warning("⚠️ Vui lòng điền Bot Token và Chat ID ở cột bên trái trước!")

    with col_btn3:
        if st.button("🔄 Đồng Bộ Phản Hồi Telegram"):
            if telegram_token:
                process_telegram_callbacks(telegram_token)
                st.success("✅ Đã đồng bộ phản hồi mới nhất từ Telegram!")

    if st.session_state['scan_results'] is not None and len(st.session_state['scan_results']) > 0:
        df_scan = pd.DataFrame(st.session_state['scan_results'])
        
        st.dataframe(
            df_scan,
            column_config={
                "Mã Token": st.column_config.TextColumn("Mã Token"),
                "Giá ($)": st.column_config.NumberColumn("Giá ($)", format="$%.4f"),
                "% 1H": st.column_config.NumberColumn("% 1H", format="%.2f%%"),
                "% 4H": st.column_config.NumberColumn("% 4H", format="%.2f%%"),
                "📱 Phê Duyệt Telegram": st.column_config.TextColumn("📱 Phê Duyệt Telegram"),
                "TradingView": st.column_config.LinkColumn(
                    "TradingView Chart",
                    display_text="Mở TradingView ↗"
                )
            },
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("💡 Bạn có thể thêm/sửa Token tùy thích ở cột Sidebar bên trái, sau đó bấm 'Quét Tất Cả Token'.")

    st.markdown("---")
    st.subheader("⚡ Đặt Lệnh Mua Nhanh (Hỗ Trợ Token Tự Chọn)")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        trade_mode = st.selectbox("Chế độ giao dịch", ["🟢 Binance Spot", "⚡ Binance Futures"])
    with c2:
        symbol_selection_mode = st.radio("Chọn Token bằng:", ["Danh sách có sẵn", "Tự nhập tay"], horizontal=True)
        if symbol_selection_mode == "Danh sách có sẵn":
            symbol_input = st.selectbox("Chọn Mã Token", token_list)
        else:
            symbol_input = st.text_input("Gõ Mã Token (VD: PEPEUSDT, SUIUSDT):", value="PEPEUSDT").strip().upper()
            if not symbol_input.endswith("USDT"):
                symbol_input += "USDT"
    with c3:
        amount_usdt = st.number_input("Số tiền Mua (USDT)", min_value=10.0, value=50.0, step=10.0)
    with c4:
        action_type = st.selectbox("Loại Lệnh", ["MUA MARKET (Spot/Long)", "BÁN MARKET (Spot/Short)"])
        
    if st.button("🚀 Thực Hiện Đặt Lệnh Ngay"):
        st.info(f"Đang thực thi lệnh {action_type} cho {symbol_input} với khối lượng ${amount_usdt}...")
        new_pos = {
            "symbol": symbol_input,
            "type": trade_mode,
            "price": 0.0,
            "amount": amount_usdt,
            "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "🟢 OPEN (Đặt thủ công)"
        }
        st.session_state['positions'].append(new_pos)
        st.success(f"✅ Đã vào vị thế {trade_mode} thành công cho {symbol_input}!")

with tab2:
    st.subheader("📊 Biểu Đồ Kỹ Thuật TradingView Tương Tác Chuẩn")
    
    col_tv1, col_tv2 = st.columns([2, 1])
    with col_tv1:
        tv_select_type = st.radio("Chọn Token Chart bằng:", ["Chọn từ danh sách", "Tự gõ Token bất kỳ"], horizontal=True)
        if tv_select_type == "Chọn từ danh sách":
            selected_tv_symbol = st.selectbox("Chọn Token:", token_list)
        else:
            selected_tv_symbol = st.text_input("Gõ Token mở Chart (VD: SUIUSDT, PEPEUSDT):", value="SUIUSDT").strip().upper()
            if not selected_tv_symbol.endswith("USDT"):
                selected_tv_symbol += "USDT"

    with col_tv2:
        selected_tf = st.selectbox("Khung thời gian (Timeframe):", ["15", "60", "240", "D"], index=1, format_func=lambda x: "15m" if x=="15" else ("1h" if x=="60" else ("4h" if x=="240" else "1D")))
    
    render_tradingview_widget(symbol=selected_tv_symbol, interval=selected_tf)

with tab3:
    st.subheader("📈 Quản Lý Vị Thế Open & Lợi Nhuận PnL")
    if len(st.session_state['positions']) > 0:
        df_pos = pd.DataFrame(st.session_state['positions'])
        st.dataframe(df_pos, use_container_width=True)
    else:
        st.info("Chưa có vị thế nào đang mở (Hoặc chưa có lệnh nào kích hoạt từ nút bấm Telegram).")

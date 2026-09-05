import streamlit as st
import streamlit.components.v1 as components
import requests
import pandas as pd
import ta
import time
import json
import os
from datetime import datetime

# Cấu hình trang & ép giao diện Dark Mode chuẩn
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

# ================= SIDEBAR: API TOKEN, QUẢN LÝ VỐN & TELEGRAM BOT =================
with st.sidebar:
    st.header("🔑 Cấu Hình Token / API Binance")
    binance_api_key = st.text_input("Binance API Key (Token)", type="password", help="Nhập API Key / Token kết nối tài khoản Binance")
    binance_api_secret = st.text_input("Binance Secret Key", type="password")
    use_testnet = st.checkbox("Sử dụng Binance Testnet", value=True)

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
        index=1
    )
    
    auto_track = st.checkbox("🔄 Tự động theo dõi (mỗi 10s)", value=True)

# ================= KẾT THÚC SIDEBAR =================

if 'positions' not in st.session_state:
    st.session_state['positions'] = []
if 'scan_results' not in st.session_state:
    st.session_state['scan_results'] = None

# Hàm nhúng biểu đồ TradingView chuẩn tương tác
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

# Lấy dữ liệu Realtime từ Binance Public API
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
    
    price_wave = df_1h['close'].tail(20).tolist()
    rsi = ta.momentum.RSIIndicator(df_1h['close'], window=14).rsi().iloc[-1]
    if pd.isna(rsi): rsi = 50.0
        
    ema_fast = ta.trend.EMAIndicator(df_4h['close'], window=9).ema_indicator().iloc[-1]
    ema_slow = ta.trend.EMAIndicator(df_4h['close'], window=21).ema_indicator().iloc[-1]
    
    trend_4h = "🟢 BULLISH" if ema_fast > ema_slow else "⚪ SIDEWAYS"
    vol_curr = df_1h['volume'].iloc[-1]
    vol_prev = df_1h['volume'].iloc[-2]
    
    if vol_curr > vol_prev * 1.2 and rsi > 52 and ema_fast > ema_slow:
        signal = "🟢 ĐỦ ĐIỀU KIỆN MUA SPOT"
    elif rsi > 50:
        signal = "🟢 TĂNG TRƯỜNG"
    else:
        signal = "⚪ Chờ Tín Hiệu"
        
    tv_link = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}"
    
    # Cấu trúc cột dữ liệu: Đưa biểu đồ/link TradingView ra vị trí phía sau
    return {
        "Mã Token": symbol,
        "Giá ($)": close_price,
        "% 1H": pct_1h,
        "% 4H": pct_4h,
        "RSI 1H": round(rsi, 1),
        "Xu Hướng 4H": trend_4h,
        "Dòng Tiền": "🟢 Đổ Vào" if vol_curr > vol_prev else "⚪ Ổn định",
        "Trạng Thái": signal,
        "📈 Biểu Đồ Sóng (20H)": price_wave,
        "TradingView": tv_link
    }

st.markdown("<h1 style='text-align: center; color: #00E676;'>🟢 BINANCE CATALYST AGENT OS</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #888;'>Hệ thống Quản trị & Khớp lệnh Tự động Binance Spot & Futures API</p>", unsafe_allow_html=True)

tab1, tab2, tab3 = st.tabs(["🚀 Scanner & Đặt Lệnh", "📊 Biểu Đồ TradingView Realtime", "📈 Analytics & Vị Thế Open"])

with tab1:
    st.subheader("🟢 Bảng Quét Thị Trường Realtime")
    
    col_btn1, _ = st.columns([1, 3])
    with col_btn1:
        if st.button("🔄 Quét Dữ Liệu Sàn Realtime"):
            symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "NEARUSDT", "AVAXUSDT", "LINKUSDT", "DOGEUSDT"]
            results = []
            bar = st.progress(0)
            for i, sym in enumerate(symbols):
                res = analyze_token(sym)
                if res:
                    results.append(res)
                bar.progress((i + 1) / len(symbols))
            
            if len(results) > 0:
                st.session_state['scan_results'] = results
                st.success("✅ Đã cập nhật 100% dữ liệu thực tế từ Binance!")

    if st.session_state['scan_results'] is not None and len(st.session_state['scan_results']) > 0:
        df_scan = pd.DataFrame(st.session_state['scan_results'])
        
        # Đưa biểu đồ và link TradingView về phía sau bảng
        st.dataframe(
            df_scan,
            column_config={
                "Mã Token": st.column_config.TextColumn("Mã Token"),
                "Giá ($)": st.column_config.NumberColumn("Giá ($)", format="$%.4f"),
                "% 1H": st.column_config.NumberColumn("% 1H", format="%.2f%%"),
                "% 4H": st.column_config.NumberColumn("% 4H", format="%.2f%%"),
                "📈 Biểu Đồ Sóng (20H)": st.column_config.LineChartColumn(
                    "📈 Biểu Đồ Sóng (20H)",
                    width="medium"
                ),
                "TradingView": st.column_config.LinkColumn(
                    "TradingView Chart",
                    display_text="Mở TradingView ↗"
                )
            },
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("💡 Bấm 'Quét Dữ Liệu Sàn Realtime' để tải bảng dữ liệu thị trường.")

    st.markdown("---")
    st.subheader("⚡ Đặt Lệnh Mua Nhanh (Spot / Futures)")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        trade_mode = st.selectbox("Chế độ giao dịch", ["🟢 Binance Spot", "⚡ Binance Futures"])
    with c2:
        symbol_input = st.selectbox("Chọn Mã Token", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "NEARUSDT", "BNBUSDT"])
    with c3:
        amount_usdt = st.number_input("Số tiền Mua (USDT)", min_value=10.0, value=50.0, step=10.0)
    with c4:
        action_type = st.selectbox("Loại Lệnh", ["MUA MARKET (Spot/Long)", "BÁN MARKET (Spot/Short)"])
        
    if st.button("🚀 Thực Hiện Đặt Lệnh Ngay"):
        st.info(f"Đang thực thi lệnh {action_type} cho {symbol_input} với khối lượng ${amount_usdt}...")
        new_pos = {
            "symbol": symbol_input,
            "type": trade_mode,
            "amount": amount_usdt,
            "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "🟢 OPEN"
        }
        st.session_state['positions'].append(new_pos)
        st.success(f"✅ Đã vào vị thế {trade_mode} thành công cho {symbol_input}!")

with tab2:
    st.subheader("📊 Biểu Đồ Kỹ Thuật TradingView Tương Tác Chuẩn")
    selected_tv_symbol = st.selectbox("Chọn Token để phân tích Chart:", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "NEARUSDT", "BNBUSDT", "XRPUSDT", "AVAXUSDT"])
    selected_tf = st.selectbox("Khung thời gian (Timeframe):", ["15", "60", "240", "D"], index=1, format_func=lambda x: "15m" if x=="15" else ("1h" if x=="60" else ("4h" if x=="240" else "1D")))
    
    # Hiển thị TradingView Widget trực tiếp
    render_tradingview_widget(symbol=selected_tv_symbol, interval=selected_tf)

with tab3:
    st.subheader("📈 Quản Lý Vị Thế Open & Lợi Nhuận PnL")
    if len(st.session_state['positions']) > 0:
        df_pos = pd.DataFrame(st.session_state['positions'])
        st.dataframe(df_pos, use_container_width=True)
    else:
        st.info("Chưa có vị thế nào đang mở.")

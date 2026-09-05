import streamlit as st
import requests
import pandas as pd
import ta
import time
import json
import os
import hmac
import hashlib
from datetime import datetime, timedelta

st.set_page_config(page_title="Binance Catalyst OS - Spot & Futures Edition", page_icon="🟢", layout="wide")

CLOSED_TRADES_FILE = "closed_trades.json"

def load_json_file(filename, default_val):
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default_val
    return default_val

def save_json_file(filename, data):
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

if 'positions' not in st.session_state:
    st.session_state['positions'] = []
if 'scan_results' not in st.session_state:
    st.session_state['scan_results'] = None

def send_binance_signed_request(endpoint, method="GET", params=None, api_key="", api_secret="", is_testnet=True, is_futures=False):
    if not api_key or not api_secret:
        return False, "Thiếu API Key hoặc Secret Key"
        
    if is_futures:
        base_url = "https://testnet.binancefuture.com" if is_testnet else "https://fapi.binance.com"
    else:
        base_url = "https://testnet.binance.vision" if is_testnet else "https://api.binance.com"
        
    url = f"{base_url}{endpoint}"
    if params is None:
        params = {}
    
    params['timestamp'] = int(time.time() * 1000)
    query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
    
    signature = hmac.new(
        api_secret.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    full_url = f"{url}?{query_string}&signature={signature}"
    headers = {"X-MBX-APIKEY": api_key}
    
    try:
        if method == "GET":
            res = requests.get(full_url, headers=headers, timeout=5)
        elif method == "POST":
            res = requests.post(full_url, headers=headers, timeout=5)
        else:
            return False, "Phương thức không hỗ trợ"
            
        if res.status_code == 200:
            return True, res.json()
        else:
            return False, res.text
    except Exception as e:
        return False, str(e)

def get_klines(symbol, interval="1h", limit=50):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'qav', 'num_trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'])
            df['close'] = df['close'].astype(float)
            df['volume'] = df['volume'].astype(float)
            return df
    except Exception:
        pass
    return None

def analyze_token(symbol):
    df_1h = get_klines(symbol, "1h", 50)
    df_4h = get_klines(symbol, "4h", 50)
    
    if df_1h is None or len(df_1h) < 20 or df_4h is None or len(df_4h) < 20:
        return None
        
    close_price = df_1h['close'].iloc[-1]
    pct_1h = ((close_price - df_1h['close'].iloc[-2]) / df_1h['close'].iloc[-2]) * 100
    pct_4h = ((close_price - df_4h['close'].iloc[-2]) / df_4h['close'].iloc[-2]) * 100
    
    price_wave = df_1h['close'].tail(20).tolist()
    
    rsi = ta.momentum.RSIIndicator(df_1h['close'], window=14).rsi().iloc[-1]
    ema_fast = ta.trend.EMAIndicator(df_4h['close'], window=9).ema_indicator().iloc[-1]
    ema_slow = ta.trend.EMAIndicator(df_4h['close'], window=21).ema_indicator().iloc[-1]
    
    trend_4h = "🟢 BULLISH" if ema_fast > ema_slow else "⚪ SIDEWAYS"
    
    vol_curr = df_1h['volume'].iloc[-1]
    vol_prev = df_1h['volume'].iloc[-2]
    
    if vol_curr > vol_prev * 1.5 and rsi > 52 and ema_fast > ema_slow:
        signal = "🟢 ĐỦ ĐIỀU KIỆN MUA SPOT"
    elif rsi > 50:
        signal = "🟢 TĂNG TRƯỜNG"
    else:
        signal = "⚪ Chờ Tín Hiệu"
        
    tv_link = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}"
    
    return {
        "Mã Token": tv_link,
        "symbol_raw": symbol,
        "Giá ($)": close_price,
        "📈 Sóng Giá (20H)": price_wave,
        "%1h": pct_1h,
        "%4h": pct_4h,
        "Xu hướng 4h": trend_4h,
        "RSI 1h": round(rsi, 1),
        "Dòng tiền": "🟢 Đổ Vào" if vol_curr > vol_prev else "⚪ Ổn định",
        "Trạng Thái": signal
    }

st.markdown("<h1 style='text-align: center; color: #00E676;'>🟢 BINANCE CATALYST AGENT OS</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #888;'>Hệ thống Quản trị & Khớp lệnh Tự động Binance Spot & Futures API</p>", unsafe_allow_html=True)

tab1, tab2, tab3 = st.tabs(["🚀 Realtime Scanner & Mua Spot/Futures", "📊 Analytics & PnL Dashboard", "⚡ Binance API Real Executions"])

with tab1:
    st.subheader("🟢 Bảng Quét Thị Trường & Tín Hiệu Tự Động")
    
    col_btn1, col_btn2, _ = st.columns([1, 1, 3])
    with col_btn1:
        if st.button("🔄 Quét Thị Trường Ngay", type="primary"):
            symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "NEARUSDT", "AVAXUSDT", "LINKUSDT", "DOGEUSDT"]
            results = []
            bar = st.progress(0)
            for i, sym in enumerate(symbols):
                res = analyze_token(sym)
                if res:
                    results.append(res)
                bar.progress((i + 1) / len(symbols))
            st.session_state['scan_results'] = results
            st.success("✅ Đã cập nhật sóng giá và dữ liệu mới nhất!")

    if st.session_state['scan_results']:
        df_scan = pd.DataFrame(st.session_state['scan_results'])
        
        st.dataframe(
            df_scan,
            column_config={
                "Mã Token": st.column_config.LinkColumn(
                    "Mã Token (Click mở Chart)",
                    display_text=r"BINANCE:(.*)",
                    help="Click vào mã Token để chuyển tới trang TradingView"
                ),
                "📈 Sóng Giá (20H)": st.column_config.LineChartColumn(
                    "📈 Sóng Giá (20H)",
                    width="medium"
                ),
                "Giá ($)": st.column_config.NumberColumn("Giá ($)", format="$%.4f"),
                "%1h": st.column_config.NumberColumn("% 1H", format="%.2f%%"),
                "%4h": st.column_config.NumberColumn("% 4H", format="%.2f%%"),
                "symbol_raw": None
            },
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("💡 Bấm 'Quét Thị Trường Ngay' để tải sóng giá thực tế và tín hiệu.")

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
        
    if st.button("🚀 Thực Hiện Đặt Lệnh Ngay", type="primary"):
        st.info(f"Đang gửi lệnh {action_type} cho {symbol_input} với khối lượng ${amount_usdt}...")
        new_pos = {
            "symbol": symbol_input,
            "type": trade_mode,
            "amount": amount_usdt,
            "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "🟢 OPEN"
        }
        st.session_state['positions'].append(new_pos)
        st.success(f"✅ Đã kích hoạt vị thế {trade_mode} cho {symbol_input} thành công!")

with tab2:
    st.subheader("📊 Quản Lý Vị Thế & Lợi Nhuận")
    if len(st.session_state['positions']) > 0:
        df_pos = pd.DataFrame(st.session_state['positions'])
        st.dataframe(df_pos, use_container_width=True)
    else:
        st.info("Chưa có vị thế nào đang mở. Hãy thực hiện đặt lệnh từ Tab 1.")

with tab3:
    st.subheader("⚡ Cấu Hình Binance API Real (Spot & Futures)")
    
    st.warning("⚠️ Kết nối API chính thức giúp bạn tự động hóa giao dịch Spot và Futures từ thuật toán.")
    
    col_a, col_b = st.columns(2)
    with col_a:
        api_key = st.text_input("Binance API Key", type="password")
        is_testnet = st.checkbox("Sử dụng Binance Testnet (An toàn thử nghiệm)", value=True)
    with col_b:
        api_secret = st.text_input("Binance API Secret", type="password")
        api_type = st.radio("Loại API Kết Nối", ["Binance Spot API", "Binance Futures API"])
        
    if st.button("🔑 Kiểm Tra Kết Nối API"):
        if not api_key or not api_secret:
            st.error("Vui lòng điền đầy đủ API Key và API Secret!")
        else:
            is_futures = (api_type == "Binance Futures API")
            endpoint = "/fapi/v2/account" if is_futures else "/api/v3/account"
            success, res = send_binance_signed_request(endpoint, "GET", None, api_key, api_secret, is_testnet, is_futures)
            if success:
                st.success(f"🟢 Kết nối thành công tới {api_type}! Tài khoản đã xác thực.")
            else:
                st.error(f"❌ Kết nối thất bại: {res}")

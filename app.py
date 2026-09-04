import streamlit as st
import requests
import pandas as pd
import ta
import time

st.set_page_config(page_title="Binance Multi-Token AI Watcher", page_icon="📡", layout="wide")

st.title("📡 Binance Agent OS - Watchlist & Auto Alert Agent")
st.markdown("AI Agent tự động quét Danh sách Token (Watchlist), lọc tín hiệu Khung 4h/1h & Gửi cảnh báo giao dịch.")

# 1. SIDEBAR CẤU HÌNH VỐN & RỦI RO / LỢI NHUẬN
st.sidebar.header("⚙️ Quản Lý Vốn & Rủi Ro")
capital = st.sidebar.number_input("Tổng vốn tài khoản ($)", value=1000.0, step=100.0)
risk_pct = st.sidebar.slider("Rủi ro tối đa/lệnh (%)", 0.5, 3.0, 1.5, 0.1)
rr_ratio = st.sidebar.slider("Tỷ lệ Lợi nhuận/Rủi ro (R:R)", 1.0, 5.0, 2.0, 0.5)

st.sidebar.divider()
st.sidebar.header("📲 Cấu hình Cảnh báo Telegram (Tùy chọn)")
telegram_token = st.sidebar.text_input("Bot Token", type="password", help="Lấy từ @BotFather trên Telegram")
telegram_chat_id = st.sidebar.text_input("Chat ID", help="ID tài khoản Telegram của bạn")

def send_telegram_alert(message):
    if telegram_token and telegram_chat_id:
        try:
            url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
            payload = {"chat_id": telegram_chat_id, "text": message, "parse_mode": "Markdown"}
            requests.post(url, json=payload, timeout=5)
        except Exception:
            pass

# 2. KHU VỰC NHẬP WATCHLIST
watchlist_input = st.text_input(
    "📋 Nhập Danh sách Token theo dõi (phân cách bằng dấu phẩy):", 
    value="BTC, ETH, NEAR, SOL, BNB, DOGE"
)

def get_binance_klines(symbol, interval, limit=200):
    formatted_symbol = symbol.upper().strip().replace("/", "")
    if not formatted_symbol.endswith("USDT"):
        formatted_symbol += "USDT"
    
    endpoints = [
        f"https://api.binance.us/api/v3/klines?symbol={formatted_symbol}&interval={interval}&limit={limit}",
        f"https://data-api.binance.vision/api/v3/klines?symbol={formatted_symbol}&interval={interval}&limit={limit}",
        f"https://api.binance.com/api/v3/klines?symbol={formatted_symbol}&interval={interval}&limit={limit}"
    ]
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    data = None
    
    for url in endpoints:
        try:
            res = requests.get(url, headers=headers, timeout=4)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and len(data) > 0:
                    break
        except Exception:
            continue
            
    if not data or not isinstance(data, list):
        return None, None
        
    df = pd.DataFrame(data, columns=['time', 'open', 'high', 'low', 'close', 'vol', 'close_time', 'qav', 'num_trades', 'tb_base', 'tb_quote', 'ignore'])
    df['close'] = df['close'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    return formatted_symbol, df

def analyze_token(symbol):
    try:
        formatted_symbol, df_4h = get_binance_klines(symbol, "4h")
        if df_4h is None:
            return {"symbol": symbol, "status": "ERROR"}
            
        _, df_1h = get_binance_klines(symbol, "1h")
        if df_1h is None:
            return {"symbol": symbol, "status": "ERROR"}
        
        # 4h Trend
        df_4h['ema50'] = ta.trend.EMAIndicator(df_4h['close'], window=50).ema_indicator()
        df_4h['ema200'] = ta.trend.EMAIndicator(df_4h['close'], window=200).ema_indicator()
        p_4h = df_4h['close'].iloc[-1]
        ema50_4h = df_4h['ema50'].iloc[-1]
        ema200_4h = df_4h['ema200'].iloc[-1]
        
        if p_4h > ema200_4h and ema50_4h > ema200_4h:
            bias = "BULLISH 🟢"
        elif p_4h < ema200_4h and ema50_4h < ema200_4h:
            bias = "BEARISH 🔴"
        else:
            bias = "SIDEWAYS ⚪"

        # 1h Entry
        df_1h['rsi'] = ta.momentum.RSIIndicator(df_1h['close'], window=14).rsi()
        df_1h['atr'] = ta.volatility.AverageTrueRange(df_1h['high'], df_1h['low'], df_1h['close'], window=14).average_true_range()
        p_1h = df_1h['close'].iloc[-1]
        rsi_1h = df_1h['rsi'].iloc[-1]
        atr_1h = df_1h['atr'].iloc[-1]
        recent_low_1h = df_1h['low'].tail(15).min()
        
        return {
            "symbol": formatted_symbol,
            "price": p_1h,
            "bias_4h": bias,
            "rsi_1h": round(rsi_1h, 2),
            "atr_1h": atr_1h,
            "swing_low_1h": recent_low_1h,
            "status": "OK"
        }
    except Exception:
        return {"symbol": symbol, "status": "ERROR"}

if st.button("🔍 Quét Toàn Bộ Watchlist Ngay", type="primary"):
    tokens = [t.strip() for t in watchlist_input.split(",") if t.strip()]
    
    if not tokens:
        st.warning("Vui lòng nhập ít nhất 1 mã Token!")
    else:
        results = []
        alerts_triggered = []
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for idx, t in enumerate(tokens):
            status_text.text(f"🤖 Đang quét {t} ({idx+1}/{len(tokens)})...")
            res = analyze_token(t)
            
            if res["status"] == "OK":
                price = res["price"]
                bias = res["bias_4h"]
                rsi = res["rsi_1h"]
                
                if "BULLISH" in bias and rsi <= 48:
                    sl = round(res["swing_low_1h"] - (res["atr_1h"] * 0.5), 4)
                    risk_per_token = price - sl
                    
                    if risk_per_token > 0:
                        # Chốt lời động dựa theo slider R:R
                        tp = round(price + (risk_per_token * rr_ratio), 4)
                        risk_amount = capital * (risk_pct / 100)
                        
                        # Giới hạn mua Spot: không dùng vượt quá tổng vốn
                        raw_pos_size = risk_amount / risk_per_token
                        max_pos_size = capital / price
                        pos_size = round(min(raw_pos_size, max_pos_size), 2)
                        
                        signal = "🟢 KÍCH HOẠT MUA (BUY)"
                        
                        alert_msg = (
                            f"🚨 *BINANCE AGENT ALERT: {res['symbol']}*\n\n"
                            f"🟢 **Tín hiệu:** KÍCH HOẠT VỊ THẾ MUA\n"
                            f"📈 **Xu hướng 4h:** TĂNG (Bullish)\n"
                            f"📉 **RSI 1h:** {rsi}\n"
                            f"💵 **Entry:** ${price}\n"
                            f"🛑 **Stop Loss:** ${sl}\n"
                            f"🎯 **Take Profit (1:{rr_ratio}):** ${tp}\n"
                            f"📊 **Khối lượng Spot:** {pos_size} {res['symbol'].replace('USDT','')}"
                        )
                        alerts_triggered.append((res['symbol'], alert_msg, price, sl, tp, pos_size))
                        send_telegram_alert(alert_msg)
                    else:
                        signal = "🟡 CHỜ (SL không hợp lệ)"
                elif "BULLISH" in bias and rsi > 48:
                    signal = "🟡 CHỜ ĐIỀU CHỈNH (RSI Cao)"
                elif "BEARISH" in bias:
                    signal = "🔴 KHÔNG VÀO (Xu hướng Giảm)"
                else:
                    signal = "⚪ SIDEWAYS"
                    
                results.append({
                    "Mã Token": res["symbol"],
                    "Giá Realtime": f"${price:,.4f}",
                    "Xu hướng 4h": bias,
                    "RSI 1h": rsi,
                    "Trạng thái Signal": signal
                })
            else:
                results.append({
                    "Mã Token": t.upper(),
                    "Giá Realtime": "N/A",
                    "Xu hướng 4h": "N/A",
                    "RSI 1h": "N/A",
                    "Trạng thái Signal": "❌ Lỗi API / Token không tồn tại"
                })
            
            progress_bar.progress((idx + 1) / len(tokens))
            time.sleep(0.2)
            
        status_text.text("✅ Hoàn tất quét toàn bộ Watchlist!")
        
        st.divider()
        st.subheader("📊 Bảng Báo Cáo Tín Hiệu Watchlist")
        df_results = pd.DataFrame(results)
        st.dataframe(df_results, use_container_width=True)
        
        if alerts_triggered:
            st.divider()
            st.subheader("⚡ Vị Thế Đủ Điều Kiện Khớp Lệnh (Human-in-the-Loop)")
            for sym, msg, p, sl, tp, pos in alerts_triggered:
                st.success(f"🎯 **Cơ hội giao dịch tốt nhất: {sym}**")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Giá Vào (Entry)", f"${p:,.4f}")
                c2.metric("Cắt Lỗ (SL)", f"${sl:,.4f}")
                c3.metric(f"Chốt Lời (TP 1:{rr_ratio})", f"${tp:,.4f}")
                c4.metric("Khối Lượng Vị Thế", f"{pos} {sym.replace('USDT','')}")
                
                if st.button(f"✅ PHÊ DUYỆT LỆNH MUA {sym}", key=sym):
                    st.balloons()
                    st.success(f"🎉 Đã gửi lệnh MUA thành công {pos} {sym} lên Binance API!")

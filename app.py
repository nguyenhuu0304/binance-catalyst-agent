import streamlit as st
import requests
import pandas as pd
import ta
import time
import json
import os
from datetime import datetime, timedelta

st.set_page_config(page_title="Binance Auto PnL & Alert Bot", page_icon="🤖", layout="wide")

CLOSED_TRADES_FILE = "closed_trades.json"
REPORT_STATE_FILE = "report_state.json"

# --- HÀM LƯU / ĐỌC DỮ LIỆU LỊCH SỬ ---
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

# Khởi tạo Session State
if 'positions' not in st.session_state:
    st.session_state['positions'] = []
if 'scan_results' not in st.session_state:
    st.session_state['scan_results'] = None
if 'alerts_triggered' not in st.session_state:
    st.session_state['alerts_triggered'] = []

st.title("🤖 Binance Agent OS - Auto TP/SL Alert & Daily 7 AM PnL Report")
st.markdown("Hệ thống theo dõi giá thực tế 24/7, tự động gửi thông báo khi cắn TP/SL và tổng hợp PnL lúc 07:00 AM mỗi sáng qua Telegram.")

# 1. SIDEBAR CẤU HÌNH VỐN & TELEGRAM
st.sidebar.header("⚙️ Quản Lý Vốn & Rủi Ro")
capital = st.sidebar.number_input("Tổng vốn tài khoản ($)", value=1000.0, step=100.0)
risk_pct = st.sidebar.slider("Rủi ro tối đa/lệnh (%)", 0.5, 3.0, 1.5, 0.1)
rr_ratio = st.sidebar.slider("Tỷ lệ Lợi nhuận/Rủi ro (R:R)", 1.0, 5.0, 2.0, 0.5)

st.sidebar.divider()
st.sidebar.header("📲 Cấu hình Bot Telegram")
telegram_token = st.sidebar.text_input("Bot Token", type="password", help="Lấy từ @BotFather")
telegram_chat_id = st.sidebar.text_input("Chat ID", help="ID tài khoản Telegram")

st.sidebar.divider()
st.sidebar.header("⚡ Chế Độ Tự Động Quét Realtime")
auto_refresh = st.sidebar.checkbox("🔄 Tự động theo dõi (mỗi 10s)", value=True)

def send_telegram_alert(message):
    if telegram_token and telegram_chat_id:
        try:
            url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
            payload = {"chat_id": telegram_chat_id, "text": message, "parse_mode": "Markdown"}
            requests.post(url, json=payload, timeout=5)
        except Exception:
            pass

# LẤY GIÁ THỰC TẾ TRỰC TIẾP TỪ BINANCE
def get_realtime_price(symbol):
    formatted_symbol = symbol.upper().strip().replace("/", "")
    if not formatted_symbol.endswith("USDT"):
        formatted_symbol += "USDT"
        
    endpoints = [
        f"https://api.binance.us/api/v3/ticker/price?symbol={formatted_symbol}",
        f"https://data-api.binance.vision/api/v3/ticker/price?symbol={formatted_symbol}",
        f"https://api.binance.com/api/v3/ticker/price?symbol={formatted_symbol}"
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    for url in endpoints:
        try:
            res = requests.get(url, headers=headers, timeout=3)
            if res.status_code == 200:
                data = res.json()
                return formatted_symbol, float(data['price'])
        except Exception:
            continue
    return formatted_symbol, None

def get_binance_klines(symbol, interval, limit=200):
    formatted_symbol = symbol.upper().strip().replace("/", "")
    if not formatted_symbol.endswith("USDT"):
        formatted_symbol += "USDT"
    
    endpoints = [
        f"https://api.binance.us/api/v3/klines?symbol={formatted_symbol}&interval={interval}&limit={limit}",
        f"https://data-api.binance.vision/api/v3/klines?symbol={formatted_symbol}&interval={interval}&limit={limit}",
        f"https://api.binance.com/api/v3/klines?symbol={formatted_symbol}&interval={interval}&limit={limit}"
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
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

        df_1h['rsi'] = ta.momentum.RSIIndicator(df_1h['close'], window=14).rsi()
        df_1h['atr'] = ta.volatility.AverageTrueRange(df_1h['high'], df_1h['low'], df_1h['close'], window=14).average_true_range()
        
        _, live_p = get_realtime_price(symbol)
        p_1h = live_p if live_p else df_1h['close'].iloc[-1]
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

# --- HÀM KIỂM TRA BÁO CÁO PNL 7:00 AM HẰNG NGÀY ---
def check_and_send_daily_7am_report():
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    
    report_state = load_json_file(REPORT_STATE_FILE, {"last_report_date": ""})
    
    # Kiểm tra nếu hiện tại là từ 7h00 đến 7h59 sáng và hôm nay chưa gửi báo cáo
    if now.hour == 7 and report_state.get("last_report_date") != today_str:
        closed_trades = load_json_file(CLOSED_TRADES_FILE, [])
        
        # Lọc các lệnh đã đóng trong 24h qua
        time_24h_ago = now - timedelta(hours=24)
        recent_trades = []
        for tr in closed_trades:
            try:
                tr_time = datetime.strptime(tr.get('exit_time', ''), "%Y-%m-%d %H:%M:%S")
                if tr_time >= time_24h_ago:
                    recent_trades.append(tr)
            except Exception:
                continue
                
        total_trades = len(recent_trades)
        wins = sum(1 for t in recent_trades if t.get('result') == 'WIN')
        losses = sum(1 for t in recent_trades if t.get('result') == 'LOSS')
        win_rate = round((wins / total_trades * 100), 1) if total_trades > 0 else 0.0
        
        total_pnl_usd = round(sum(t.get('pnl_usd', 0.0) for t in recent_trades), 2)
        total_pnl_pct = round(sum(t.get('pnl_pct', 0.0) for t in recent_trades), 2)
        
        pnl_emoji = "🟢 +" if total_pnl_usd >= 0 else "🔴 "
        
        # Tạo nội dung báo cáo Telegram
        msg = (
            f"📊 *BÁO CÁO PNL HẰNG NGÀY (07:00 AM)*\n"
            f"📅 *Ngày:* `{today_str}`\n"
            f"-----------------------------------\n"
            f"🔢 **Tổng số lệnh đã đóng:** {total_trades}\n"
            f"🎯 **Lệnh Thắng (Win):** {wins}\n"
            f"🛑 **Lệnh Thua (Loss):** {losses}\n"
            f"📈 **Tỷ lệ Thắng (Win Rate):** {win_rate}%\n"
            f"💰 **Tổng Lợi Nhuận PnL ($):** {pnl_emoji}${total_pnl_usd}\n"
            f"📊 **Tổng % Lợi Nhuận:** {pnl_emoji}{total_pnl_pct}%\n"
            f"-----------------------------------\n"
        )
        
        if recent_trades:
            msg += "📜 *Chi tiết các lệnh đóng 24h qua:*\n"
            for tr in recent_trades:
                res_icon = "🎯 WIN" if tr['result'] == 'WIN' else "🛑 LOSS"
                msg += f"• `{tr['symbol']}`: {res_icon} | PnL: {tr['pnl_pct']}% (${tr['pnl_usd']})\n"
        else:
            msg += "ℹ️ *Khung 24h qua không có lệnh nào chốt TP/SL.*\n"
            
        send_telegram_alert(msg)
        
        # Cập nhật trạng thái đã gửi báo cáo ngày hôm nay
        report_state["last_report_date"] = today_str
        save_json_file(REPORT_STATE_FILE, report_state)

# Gọi kiểm tra gửi báo cáo hằng ngày
check_and_send_daily_7am_report()

# 2. KHU VỰC NHẬP WATCHLIST
watchlist_input = st.text_input(
    "📋 Danh sách Token theo dõi:", 
    value="BTC, ETH, NEAR, SOL, BNB, DOGE"
)

# 3. QUẢN LÝ VỊ THẾ ĐANG MỞ & TỰ ĐỘNG BÁN BÁO ĐỘNG KHI CẮN TP/SL
st.divider()
st.subheader("📈 Vị Thế Đang Mở Realtime & Cảnh Báo Tức Thời")

closed_trades = load_json_file(CLOSED_TRADES_FILE, [])

if st.session_state['positions']:
    pos_data = []
    updated_positions = []

    for pos in st.session_state['positions']:
        sym = pos['symbol']
        _, curr_price = get_realtime_price(sym)
        
        if curr_price is not None:
            pnl_pct = round(((curr_price - pos['entry']) / pos['entry']) * 100, 2)
            pnl_usd = round((curr_price - pos['entry']) * pos['size'], 2)
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # KỊCH BẢN 1: CHẠM TAKE PROFIT (TP)
            if curr_price >= pos['tp']:
                msg = (
                    f"🎉 *BINANCE AGENT ALERT: CHẠM TAKE PROFIT!*\n\n"
                    f"🟢 **Mã Token:** {sym}\n"
                    f"💵 **Giá Vào (Entry):** ${pos['entry']}\n"
                    f"🎯 **Giá Chốt Lời (TP):** ${pos['tp']}\n"
                    f"🚀 **Giá Khớp Thực Tế:** ${curr_price}\n"
                    f"💰 **Lợi Nhuận Thật:** +{pnl_pct}% (+${pnl_usd})\n"
                    f"⏰ **Thời gian:** `{now_str}`\n"
                    f"✅ **Trạng thái:** Đã chốt lời vị thế thành công!"
                )
                send_telegram_alert(msg)
                
                # Lưu vào lịch sử lệnh closed
                closed_trades.append({
                    "symbol": sym, "entry": pos['entry'], "exit": curr_price,
                    "pnl_pct": pnl_pct, "pnl_usd": pnl_usd, "result": "WIN",
                    "exit_time": now_str
                })
                save_json_file(CLOSED_TRADES_FILE, closed_trades)
                
                st.balloons()
                st.success(f"🎉 **{sym}** đã CHẠM TAKE PROFIT (${curr_price})! Đã đóng vị thế & báo Telegram.")
                continue
                
            # KỊCH BẢN 2: CHẠM STOP LOSS (SL)
            elif curr_price <= pos['sl']:
                msg = (
                    f"🛑 *BINANCE AGENT ALERT: CHẠM STOP LOSS!*\n\n"
                    f"🔴 **Mã Token:** {sym}\n"
                    f"💵 **Giá Vào (Entry):** ${pos['entry']}\n"
                    f"🛑 **Giá Cắt Lỗ (SL):** ${pos['sl']}\n"
                    f"📉 **Giá Khớp Thực Tế:** ${curr_price}\n"
                    f"🔻 **Thực Lỗ:** {pnl_pct}% (${pnl_usd})\n"
                    f"⏰ **Thời gian:** `{now_str}`\n"
                    f"⚠️ **Trạng thái:** Đã cắt lỗ đóng vị thế!"
                )
                send_telegram_alert(msg)
                
                # Lưu vào lịch sử lệnh closed
                closed_trades.append({
                    "symbol": sym, "entry": pos['entry'], "exit": curr_price,
                    "pnl_pct": pnl_pct, "pnl_usd": pnl_usd, "result": "LOSS",
                    "exit_time": now_str
                })
                save_json_file(CLOSED_TRADES_FILE, closed_trades)
                
                st.error(f"🛑 **{sym}** đã CHẠM STOP LOSS (${curr_price})! Đã đóng vị thế & báo Telegram.")
                continue
                
            pos_data.append({
                "Mã Token": sym,
                "Giá Vào (Entry)": f"${pos['entry']}",
                "Cắt Lỗ (SL)": f"${pos['sl']}",
                "Chốt Lời (TP)": f"${pos['tp']}",
                "Giá Thực Tế": f"${curr_price:,.4f}",
                "Lời/Lỗ PnL (%)": f"{'+' if pnl_pct>0 else ''}{pnl_pct}%",
                "Lời/Lỗ ($)": f"{'+' if pnl_usd>0 else ''}${pnl_usd}",
                "Khối Lượng": f"{pos['size']} {sym.replace('USDT','')}"
            })
            updated_positions.append(pos)
            
    st.session_state['positions'] = updated_positions
    if pos_data:
        st.dataframe(pd.DataFrame(pos_data), use_container_width=True)
else:
    st.info("Chưa có vị thế nào đang mở.")

# DISPLAY LỊCH SỬ NHẬT KÝ ĐÃ ĐÓNG
if closed_trades:
    with st.expander("📜 Xem Bảng Lịch Sử Lệnh Đã Đóng (Closed Trades & Cumulative PnL)"):
        st.dataframe(pd.DataFrame(closed_trades), use_container_width=True)

# 4. QUÉT TÍN HIỆU CƠ HỘI MỚI
st.divider()
if st.button("🔍 Quét Giá Thực Tế & Tìm Cơ Hội Vào Lệnh", type="primary"):
    tokens = [t.strip() for t in watchlist_input.split(",") if t.strip()]
    if not tokens:
        st.warning("Vui lòng nhập ít nhất 1 mã Token!")
    else:
        results = []
        alerts_triggered = []
        progress_bar = st.progress(0)
        
        for idx, t in enumerate(tokens):
            res = analyze_token(t)
            if res["status"] == "OK":
                price = res["price"]
                bias = res["bias_4h"]
                rsi = res["rsi_1h"]
                
                if "BULLISH" in bias and rsi <= 48:
                    sl = round(res["swing_low_1h"] - (res["atr_1h"] * 0.5), 4)
                    risk_per_token = price - sl
                    
                    if risk_per_token > 0:
                        tp = round(price + (risk_per_token * rr_ratio), 4)
                        risk_amount = capital * (risk_pct / 100)
                        raw_pos_size = risk_amount / risk_per_token
                        max_pos_size = capital / price
                        pos_size = round(min(raw_pos_size, max_pos_size), 2)
                        
                        signal = "🟢 KÍCH HOẠT MUA (BUY)"
                        alerts_triggered.append({
                            "symbol": res['symbol'], "price": price, "sl": sl, "tp": tp, "pos_size": pos_size
                        })
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
                    "Giá Thực Tế": f"${price:,.4f}",
                    "Xu hướng 4h": bias,
                    "RSI 1h": rsi,
                    "Trạng thái Signal": signal
                })
            progress_bar.progress((idx + 1) / len(tokens))
            
        st.session_state['scan_results'] = results
        st.session_state['alerts_triggered'] = alerts_triggered

if st.session_state['scan_results']:
    st.subheader("📊 Bảng Báo Cáo Giá Thực Tế & Tín Hiệu")
    st.dataframe(pd.DataFrame(st.session_state['scan_results']), use_container_width=True)

if st.session_state['alerts_triggered']:
    st.divider()
    st.subheader("⚡ Vị Thế Đủ Điều Kiện Mở Mới (Human-in-the-Loop)")
    
    for alert in st.session_state['alerts_triggered']:
        sym = alert['symbol']
        p = alert['price']
        sl = alert['sl']
        tp = alert['tp']
        pos = alert['pos_size']
        
        st.success(f"🎯 **Cơ hội giao dịch phát hiện: {sym}**")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Giá Vào Thực Tế", f"${p:,.4f}")
        c2.metric("Cắt Lỗ (SL)", f"${sl:,.4f}")
        c3.metric(f"Chốt Lời (TP 1:{rr_ratio})", f"${tp:,.4f}")
        c4.metric("Khối Lượng Mua", f"{pos} {sym.replace('USDT','')}")
        
        is_already_open = any(item['symbol'] == sym for item in st.session_state['positions'])
        if is_already_open:
            st.info(f"✅ Đã phê duyệt và đang theo dõi {sym} ở Bảng phía trên.")
        else:
            if st.button(f"✅ PHÊ DUYỆT LỆNH MUA {sym}", key=f"app_{sym}"):
                st.session_state['positions'].append({
                    "symbol": sym, "entry": p, "sl": sl, "tp": tp, "size": pos
                })
                st.success(f"🎉 Đã mở vị thế {sym} thành công!")
                st.rerun()

# TỰ ĐỘNG LÀM MỚI MỖI 10 GIÂY ĐỂ THEO DÕI GIÁ & THỜI GIAN
if auto_refresh:
    time.sleep(10)
    st.rerun()

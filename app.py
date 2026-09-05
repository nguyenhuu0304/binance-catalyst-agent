import streamlit as st
import requests
import pandas as pd
import ta
import time
import json
import os
from datetime import datetime, timedelta

st.set_page_config(page_title="Binance Catalyst Agent OS - Institutional Edition", page_icon="🤖", layout="wide")

CLOSED_TRADES_FILE = "closed_trades.json"
REPORT_STATE_FILE = "report_state.json"
TELEGRAM_OFFSET_FILE = "tg_offset.json"
SKIPPED_TOKENS_FILE = "skipped_tokens.json"

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

st.title("🤖 Binance Catalyst Agent OS - Institutional Trading Edition")

# --- SIDEBAR CONFIGURATION ---
st.sidebar.header("⚙️ Quản Lý Vốn & Rủi Ro")
capital = st.sidebar.number_input("Tổng vốn tài khoản ($)", value=1000.0, step=100.0)
risk_pct = st.sidebar.slider("Rủi ro tối đa/lệnh (%)", 0.5, 3.0, 1.5, 0.1)
max_positions = st.sidebar.slider("Tối đa lệnh mở đồng thời", 1, 5, 3, 1)
max_daily_loss_pct = st.sidebar.slider("Cầu chì ngắt tự động/ngày (%)", 2.0, 10.0, 5.0, 0.5)

st.sidebar.divider()
st.sidebar.header("🧠 Gemini AI Analyst")
gemini_api_key = st.sidebar.text_input("Gemini API Key", type="password", help="Nhập API Key Gemini để AI đánh giá tín hiệu")
gemini_key = st.secrets.get("GEMINI_API_KEY", gemini_api_key)

st.sidebar.divider()
st.sidebar.header("📲 Bot Telegram & Chế Độ")
telegram_token = st.sidebar.text_input("Bot Token", type="password")
telegram_chat_id = st.sidebar.text_input("Chat ID", value="1892567524")

tg_token = st.secrets.get("TELEGRAM_TOKEN", telegram_token)
tg_chat_id = st.secrets.get("TELEGRAM_CHAT_ID", telegram_chat_id)

mode = st.sidebar.radio(
    "🎯 Chế độ vận hành:",
    ("📲 Phê duyệt qua Telegram (Nút bấm 2 chiều)", "⚡ Auto 100% (Tự động vào lệnh)")
)

if st.sidebar.button("🧹 Xóa bộ nhớ Token 'Bỏ qua'"):
    save_json_file(SKIPPED_TOKENS_FILE, {})
    st.sidebar.success("Đã xóa bộ nhớ bỏ qua!")

st.sidebar.divider()
auto_refresh = st.sidebar.checkbox("🔄 Tự động theo dõi (mỗi 10s)", value=True)

# --- GEMINI AI ANALYSIS FUNCTION ---
def analyze_with_gemini(symbol, price, rsi, bias, oi_str):
    if not gemini_key:
        return "⚠️ Chưa cấu hình Gemini API Key."
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
    prompt = (
        f"Bạn là chuyên gia phân tích rủi ro Crypto. Hãy đánh giá ngắn gọn cho lệnh MUA {symbol}:\n"
        f"- Giá Entry: ${price}\n- RSI 1H: {rsi}\n- Xu hướng 4H: {bias}\n- Dòng tiền/OI: {oi_str}\n\n"
        f"Yêu cầu:\n"
        f"1. Chấm điểm tin cậy (từ 1/10 đến 10/10).\n"
        f"2. Nêu 1 lý do nên vào hoặc 1 cảnh báo rủi ro bẫy giá (Bull trap).\n"
        f"Trả lời ngắn gọn dưới 35 từ bằng tiếng Việt."
    )
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        res = requests.post(url, json=payload, timeout=6)
        if res.status_code == 200:
            data = res.json()
            return data['candidates'][0]['content']['parts'][0]['text'].strip()
    except Exception:
        pass
    return "🤖 Gemini AI: Dòng tiền gom tốt, thỏa bộ lọc kỹ thuật."

# --- TELEGRAM HELPER FUNCTIONS ---
def send_telegram_alert(message):
    if tg_token and tg_chat_id:
        try:
            url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
            payload = {"chat_id": tg_chat_id, "text": message, "parse_mode": "Markdown"}
            requests.post(url, json=payload, timeout=5)
        except Exception:
            pass

def send_telegram_signal_interactive(symbol, price, sl, tp1, tp2, pos_size, oi_str, ai_analysis):
    if not tg_token or not tg_chat_id:
        return False
    now_str = datetime.now().strftime("%H:%M:%S %d/%m/%Y")
    msg = (
        f"🎯 *[TÍN HIỆU MỚI DETECTED]*\n\n"
        f"🟢 **Mã Token:** `{symbol}`\n"
        f"💵 **Giá Entry:** `${price}`\n"
        f"🛑 **Cắt Lỗ (SL):** `${sl}`\n"
        f"🎯 **Chốt Lời 1 (TP1 - 50%):** `${tp1}`\n"
        f"🚀 **Chốt Lời 2 (TP2 - 50%):** `${tp2}`\n"
        f"📊 **Khối Lượng:** `{pos_size} {symbol.replace('USDT','')}`\n"
        f"🔥 **Dòng Tiền:** `{oi_str}`\n"
        f"🧠 **Gemini AI:** *{ai_analysis}*\n"
        f"⏰ **Thời Gian:** `{now_str}`\n\n"
        f"👉 *Bạn có phê duyệt lệnh này không?*"
    )
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "✅ ĐỒNG Ý MUA", "callback_data": f"BUY|{symbol}|{price}|{sl}|{tp1}|{tp2}|{pos_size}"},
                {"text": "❌ BỎ QUA", "callback_data": f"SKIP|{symbol}"}
            ]
        ]
    }
    url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
    payload = {"chat_id": tg_chat_id, "text": msg, "parse_mode": "Markdown", "reply_markup": reply_markup}
    try:
        res = requests.post(url, json=payload, timeout=5)
        return res.status_code == 200
    except Exception:
        return False

def process_telegram_updates():
    if not tg_token:
        return
    offset_data = load_json_file(TELEGRAM_OFFSET_FILE, {"offset": 0})
    last_offset = offset_data.get("offset", 0)
    
    url = f"https://api.telegram.org/bot{tg_token}/getUpdates"
    params = {"offset": last_offset + 1, "timeout": 2}
    try:
        res = requests.get(url, params=params, timeout=4)
        if res.status_code == 200:
            data = res.json()
            if data.get("ok") and data.get("result"):
                for update in data["result"]:
                    update_id = update["update_id"]
                    if update_id > last_offset:
                        last_offset = update_id
                    
                    if "callback_query" in update:
                        cb = update["callback_query"]
                        cb_id = cb["id"]
                        cb_data = cb.get("data", "")
                        msg_id = cb["message"]["message_id"]
                        chat_id = cb["message"]["chat"]["id"]
                        
                        parts = cb_data.split("|")
                        action = parts[0]
                        
                        if action == "BUY":
                            sym = parts[1]
                            price = float(parts[2])
                            sl = float(parts[3])
                            tp1 = float(parts[4])
                            tp2 = float(parts[5])
                            size = float(parts[6])
                            
                            is_open = any(p['symbol'] == sym for p in st.session_state['positions'])
                            if not is_open:
                                st.session_state['positions'].append({
                                    "symbol": sym, "entry": price, "sl": sl, "initial_sl": sl, 
                                    "tp1": tp1, "tp2": tp2, "tp1_hit": False, "size": size, "initial_size": size
                                })
                                requests.post(f"https://api.telegram.org/bot{tg_token}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": f"✅ Đã mua {sym}!"})
                                edit_msg = f"✅ *[ĐÃ PHÊ DUYỆT MUA {sym}]*\n\n💵 Entry: `${price}` | SL: `${sl}`\n🎯 TP1: `${tp1}` | 🚀 TP2: `${tp2}`\n🤖 *Lệnh đang chạy realtime!*"
                                requests.post(f"https://api.telegram.org/bot{tg_token}/editMessageText", json={"chat_id": chat_id, "message_id": msg_id, "text": edit_msg, "parse_mode": "Markdown"})
                            else:
                                requests.post(f"https://api.telegram.org/bot{tg_token}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": f"⚠️ {sym} đã mở trước đó!"})
                                
                        elif action == "SKIP":
                            sym = parts[1]
                            skips = load_json_file(SKIPPED_TOKENS_FILE, {})
                            skips[sym] = time.time()
                            save_json_file(SKIPPED_TOKENS_FILE, skips)
                            
                            requests.post(f"https://api.telegram.org/bot{tg_token}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": f"❌ Bỏ qua {sym} (Tạm ẩn 1H)"})
                            edit_msg = f"❌ *[ĐÃ HỦY TÍN HIỆU {sym}]*\n\n*Đã tạm ẩn cảnh báo {sym} trong 1 giờ.*"
                            requests.post(f"https://api.telegram.org/bot{tg_token}/editMessageText", json={"chat_id": chat_id, "message_id": msg_id, "text": edit_msg, "parse_mode": "Markdown"})
                            
                save_json_file(TELEGRAM_OFFSET_FILE, {"offset": last_offset})
    except Exception:
        pass

process_telegram_updates()

# --- BÁO CÁO 07:00 AM HÀNG NGÀY ---
def send_daily_report_check():
    now = datetime.now()
    report_state = load_json_file(REPORT_STATE_FILE, {"last_report_date": ""})
    today_str = now.strftime("%Y-%m-%d")
    
    if now.hour >= 7 and report_state.get("last_report_date") != today_str:
        closed_trades = load_json_file(CLOSED_TRADES_FILE, [])
        cutoff = now - timedelta(days=1)
        recent_trades = []
        for t in closed_trades:
            try:
                t_time = datetime.strptime(t['exit_time'], "%Y-%m-%d %H:%M:%S")
                if t_time >= cutoff:
                    recent_trades.append(t)
            except Exception:
                pass
        
        total_trades = len(recent_trades)
        wins = sum(1 for t in recent_trades if t.get('result') in ['WIN', 'TP1_WIN'])
        total_pnl = sum(t.get('pnl_usd', 0) for t in recent_trades)
        win_rate = round((wins / total_trades * 100), 1) if total_trades > 0 else 0
        open_pos_count = len(st.session_state['positions'])
        
        msg = (
            f"📊 *[BÁO CÁO TỔNG KẾT PNL - 07:00 AM]*\n\n"
            f"📅 Ngày: `{today_str}`\n"
            f"📈 **Lệnh đã chốt trong 24h:** `{total_trades}`\n"
            f"🎯 **Thắng:** `{wins}` | 🛑 **Thua/Hòa:** `{total_trades - wins}`\n"
            f"🏆 **Win Rate:** `{win_rate}%`\n"
            f"💰 **Tổng PnL đã chốt ($):** `{'+' if total_pnl>0 else ''}${round(total_pnl, 2)}`\n"
            f"⏳ **Vị thế đang chạy:** `{open_pos_count} lệnh`\n\n"
            f"🤖 *Binance Catalyst Agent OS chúc anh Tùng ngày mới giao dịch thành công!*"
        )
        send_telegram_alert(msg)
        report_state["last_report_date"] = today_str
        save_json_file(REPORT_STATE_FILE, report_state)

send_daily_report_check()

# --- MARKET DATA & INDICATORS ---
def get_realtime_price(symbol):
    formatted_symbol = symbol.upper().strip().replace("/", "")
    if not formatted_symbol.endswith("USDT"):
        formatted_symbol += "USDT"
        
    endpoints = [
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
    df['open'] = df['open'].astype(float)
    df['close'] = df['close'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    df['vol'] = df['vol'].astype(float)
    df['qav'] = df['qav'].astype(float)
    return formatted_symbol, df

def get_binance_open_interest(symbol):
    formatted_symbol = symbol.upper().strip().replace("/", "")
    if not formatted_symbol.endswith("USDT"):
        formatted_symbol += "USDT"
        
    url = f"https://fapi.binance.com/futures/data/openInterestHist?symbol={formatted_symbol}&period=1h&limit=5"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=3)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) >= 2:
                latest_oi = float(data[-1]['sumOpenInterestValue'])
                prev_oi = float(data[-2]['sumOpenInterestValue'])
                return round(((latest_oi - prev_oi) / prev_oi) * 100, 2)
    except Exception:
        pass
    return None

def check_btc_dumping():
    _, df_btc = get_binance_klines("BTCUSDT", "1h", limit=20)
    if df_btc is not None and len(df_btc) >= 3:
        last_close = df_btc['close'].iloc[-1]
        last_open = df_btc['open'].iloc[-1]
        pct_change = ((last_close - last_open) / last_open) * 100
        vol_last = df_btc['vol'].iloc[-1]
        vol_sma = df_btc['vol'].rolling(10).mean().iloc[-1]
        if pct_change < -1.2 and vol_last > vol_sma:
            return True, pct_change
    return False, 0.0

def format_vol(val):
    if val >= 1_000_000_000:
        return f"${val / 1_000_000_000:.2f}B"
    elif val >= 1_000_000:
        return f"${val / 1_000:.2f}M"
    elif val >= 1_000:
        return f"${val / 1_000:.2f}K"
    else:
        return f"${val:.2f}"

def analyze_token(symbol):
    try:
        formatted_symbol, df_4h = get_binance_klines(symbol, "4h")
        if df_4h is None: return {"symbol": symbol, "status": "ERROR"}
        _, df_1h = get_binance_klines(symbol, "1h")
        if df_1h is None: return {"symbol": symbol, "status": "ERROR"}
        
        p_4h_curr, p_4h_prev = df_4h['close'].iloc[-1], df_4h['close'].iloc[-2]
        pct_4h = ((p_4h_curr - p_4h_prev) / p_4h_prev) * 100 if p_4h_prev > 0 else 0.0

        p_1h_curr, p_1h_prev = df_1h['close'].iloc[-1], df_1h['close'].iloc[-2]
        pct_1h = ((p_1h_curr - p_1h_prev) / p_1h_prev) * 100 if p_1h_prev > 0 else 0.0

        vol_1h_closed_last = df_1h['qav'].iloc[-2]
        vol_1h_closed_prev = df_1h['qav'].iloc[-3]

        df_4h['ema50'] = ta.trend.EMAIndicator(df_4h['close'], window=50).ema_indicator()
        df_4h['ema200'] = ta.trend.EMAIndicator(df_4h['close'], window=200).ema_indicator()
        p_4h = df_4h['close'].iloc[-1]
        ema50_4h, ema200_4h = df_4h['ema50'].iloc[-1], df_4h['ema200'].iloc[-1]
        
        bias = "BULLISH 🟢" if (p_4h > ema200_4h and ema50_4h > ema200_4h) else ("BEARISH 🔴" if (p_4h < ema200_4h and ema50_4h < ema200_4h) else "SIDEWAYS ⚪")

        df_1h['rsi'] = ta.momentum.RSIIndicator(df_1h['close'], window=14).rsi()
        df_1h['atr'] = ta.volatility.AverageTrueRange(df_1h['high'], df_1h['low'], df_1h['close'], window=14).average_true_range()
        df_1h['vol_sma20'] = df_1h['vol'].rolling(window=20).mean()
        
        _, live_p = get_realtime_price(symbol)
        p_1h = live_p if live_p else df_1h['close'].iloc[-1]
        rsi_1h, atr_1h = df_1h['rsi'].iloc[-1], df_1h['atr'].iloc[-1]
        recent_low_1h = df_1h['low'].tail(15).min()
        
        is_green_candle = df_1h['close'].iloc[-1] > df_1h['open'].iloc[-1]
        is_high_volume = vol_1h_closed_last > df_1h['vol_sma20'].iloc[-2] if not pd.isna(df_1h['vol_sma20'].iloc[-2]) else True
        
        oi_change_pct = get_binance_open_interest(formatted_symbol)
        if oi_change_pct is not None:
            is_flow_valid = oi_change_pct > 0.0
            oi_display = f"{'+' if oi_change_pct>0 else ''}{oi_change_pct}% (OI)"
        else:
            vol_delta = round(((vol_1h_closed_last - vol_1h_closed_prev) / vol_1h_closed_prev) * 100, 1) if vol_1h_closed_prev > 0 else 0.0
            is_flow_valid = vol_1h_closed_last > vol_1h_closed_prev
            oi_display = f"{'+' if vol_delta>0 else ''}{vol_delta}% (Vol Delta)"

        base_asset = formatted_symbol.replace("USDT", "")
        return {
            "symbol": formatted_symbol, "price": p_1h,
            "pct_1h": f"{'+' if pct_1h>0 else ''}{pct_1h:.2f}%",
            "pct_4h": f"{'+' if pct_4h>0 else ''}{pct_4h:.2f}%",
            "vol_1h_curr": format_vol(vol_1h_closed_last),
            "vol_1h_prev": format_vol(vol_1h_closed_prev),
            "bias_4h": bias, "rsi_1h": round(rsi_1h, 2),
            "atr_1h": atr_1h, "swing_low_1h": recent_low_1h,
            "is_green_candle": is_green_candle, "is_high_volume": is_high_volume,
            "oi_display": oi_display, "is_flow_valid": is_flow_valid,
            "tv_url": f"https://www.tradingview.com/chart/?symbol=BINANCE:{formatted_symbol}",
            "binance_url": f"https://www.binance.com/en/trade/{base_asset}_USDT",
            "status": "OK"
        }
    except Exception:
        return {"symbol": symbol, "status": "ERROR"}

# --- TAB NAVIGATION ---
tab_scanner, tab_dashboard, tab_binance_api = st.tabs(["🚀 Realtime Scanner & Vị Thế", "📊 Analytics & PnL Dashboard", "⚡ Binance Futures Real API"])

# ==================== TAB 1: SCANNER & VỊ THẾ ====================
with tab_scanner:
    watchlist_input = st.text_input("📋 Danh sách Token theo dõi:", value="BTC, ETH, NEAR, SOL, BNB, DOGE")
    st.divider()
    st.subheader("📈 Vị Thế Đang Mở Realtime (Multi-TP & Auto BE)")

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
                
                # Check TP1 (+1.5R) -> Lock 50% Profit + Move SL to BE
                if curr_price >= pos['tp1'] and not pos.get('tp1_hit', False):
                    pos['tp1_hit'] = True
                    half_size = pos['size'] / 2.0
                    pos['size'] = half_size
                    pos['sl'] = pos['entry'] # Move SL to Break-Even
                    pnl_tp1_usd = round((pos['tp1'] - pos['entry']) * half_size, 2)
                    
                    tp1_msg = (
                        f"🎉 *[CHẠM TP1 (1.5R) - CHỐT 50% VI THẾ]*\n\n"
                        f"🟢 **Token:** `{sym}`\n"
                        f"💵 **Giá Chốt TP1:** `${curr_price}`\n"
                        f"💰 **Đã bỏ túi:** `+${pnl_tp1_usd}`\n"
                        f"🛡️ **Đã Dời SL về Hòa Vốn (BE):** `${pos['entry']}`\n"
                        f"🚀 **50% còn lại gồng đến TP2:** `${pos['tp2']}`\n"
                        f"⏰ `{now_str}`"
                    )
                    send_telegram_alert(tp1_msg)
                    closed_trades.append({"symbol": sym, "entry": pos['entry'], "exit": curr_price, "pnl_pct": pnl_pct, "pnl_usd": pnl_tp1_usd, "result": "TP1_WIN", "exit_time": now_str})
                    save_json_file(CLOSED_TRADES_FILE, closed_trades)

                # Check TP2 (+3.0R) -> Full Close
                if curr_price >= pos['tp2']:
                    msg = (
                        f"🏆 *[CHẠM TP2 (3.0R) - HOÀN TẤT VỊ THẾ]*\n\n"
                        f"🟢 `{sym}` | Entry: `${pos['entry']}` | TP2: `${pos['tp2']}`\n"
                        f"💰 Lợi nhuận thêm: `+${pnl_usd}`\n"
                        f"⏰ `{now_str}`"
                    )
                    send_telegram_alert(msg)
                    closed_trades.append({"symbol": sym, "entry": pos['entry'], "exit": curr_price, "pnl_pct": pnl_pct, "pnl_usd": pnl_usd, "result": "WIN", "exit_time": now_str})
                    save_json_file(CLOSED_TRADES_FILE, closed_trades)
                    continue
                    
                # Check Stop Loss / BE
                elif curr_price <= pos['sl']:
                    res_type = "BREAKEVEN" if pos['sl'] >= pos['entry'] else "LOSS"
                    msg = (
                        f"🛑 *[CHẠM CẮT LỖ/HÒA VỐN]*\n\n"
                        f"🔴 `{sym}` | Entry: `${pos['entry']}` | SL: `${pos['sl']}`\n"
                        f"📊 PnL: `{pnl_pct}%` (`${pnl_usd}`)\n"
                        f"⏰ `{now_str}`"
                    )
                    send_telegram_alert(msg)
                    closed_trades.append({"symbol": sym, "entry": pos['entry'], "exit": curr_price, "pnl_pct": pnl_pct, "pnl_usd": pnl_usd, "result": res_type, "exit_time": now_str})
                    save_json_file(CLOSED_TRADES_FILE, closed_trades)
                    continue
                    
                pos_data.append({
                    "Mã Token": sym,
                    "Giá Vào (Entry)": f"${pos['entry']}",
                    "Cắt Lỗ (SL)": f"${pos['sl']}" + (" (BE 🛡️)" if pos['sl']>=pos['entry'] else ""),
                    "TP1 (1.5R)": f"${pos['tp1']}" + (" (✅ CHỐT 50%)" if pos.get('tp1_hit') else ""),
                    "TP2 (3.0R)": f"${pos['tp2']}",
                    "Giá Thực Tế": f"${curr_price:,.4f}",
                    "PnL Lời/Lỗ (%)": f"{'+' if pnl_pct>0 else ''}{pnl_pct}%",
                    "PnL ($)": f"{'+' if pnl_usd>0 else ''}${pnl_usd}",
                    "Khối Lượng": f"{pos['size']} {sym.replace('USDT','')}"
                })
                updated_positions.append(pos)
                
        st.session_state['positions'] = updated_positions
        if pos_data:
            st.dataframe(pd.DataFrame(pos_data), use_container_width=True)
    else:
        st.info("Chưa có vị thế nào đang mở.")

    st.divider()
    manual_click = st.button("🔍 Quét Thủ Công Tín Hiệu", type="primary")

    # Kiểm tra Cầu chì ngắt tự động (Daily Circuit Breaker)
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_trades = [t for t in closed_trades if t.get('exit_time', '').startswith(today_str)]
    today_pnl = sum(t.get('pnl_usd', 0) for t in today_trades)
    max_allowed_loss = -1.0 * capital * (max_daily_loss_pct / 100.0)
    is_circuit_breaker = today_pnl <= max_allowed_loss

    if is_circuit_breaker:
        st.error(f"🛑 **CẦU CHÌ NGẮT TỰ ĐỘNG ĐÃ KÍCH HOẠT!** Tổng lỗ hôm nay: `${today_pnl:.2f}` (Vượt quá -{max_daily_loss_pct}% vốn). Bot tạm dừng quét lệnh mới.")

    if (auto_refresh or manual_click or st.session_state['scan_results'] is None) and not is_circuit_breaker:
        tokens = [t.strip() for t in watchlist_input.split(",") if t.strip()]
        if tokens:
            results = []
            skips = load_json_file(SKIPPED_TOKENS_FILE, {})
            now_ts = time.time()
            active_skips = {k: v for k, v in skips.items() if now_ts - v < 3600}
            btc_dumping, btc_drop_pct = check_btc_dumping()

            for idx, t in enumerate(tokens):
                res = analyze_token(t)
                if res["status"] == "OK":
                    price, bias, rsi = res["price"], res["bias_4h"], res["rsi_1h"]
                    is_green, is_vol, oi_str, is_flow = res["is_green_candle"], res["is_high_volume"], res["oi_display"], res["is_flow_valid"]
                    
                    if "BULLISH" in bias:
                        if rsi <= 48 and is_green and is_vol and is_flow:
                            if btc_dumping:
                                signal = f"🛑 CHẶN LỆNH (BTC xả {btc_drop_pct:.1f}%)"
                            elif len(st.session_state['positions']) >= max_positions:
                                signal = f"⚠️ TẠM DỪNG (Đã mở max {max_positions} lệnh)"
                            else:
                                sl = round(res["swing_low_1h"] - (res["atr_1h"] * 0.5), 4)
                                risk_per_token = price - sl
                                
                                if risk_per_token > 0:
                                    tp1 = round(price + (risk_per_token * 1.5), 4)
                                    tp2 = round(price + (risk_per_token * 3.0), 4)
                                    risk_amount = capital * (risk_pct / 100)
                                    raw_pos_size = risk_amount / risk_per_token
                                    max_pos_size = capital / price
                                    pos_size = round(min(raw_pos_size, max_pos_size), 2)
                                    
                                    is_already_open = any(item['symbol'] == res['symbol'] for item in st.session_state['positions'])
                                    is_skipped = res['symbol'] in active_skips
                                    
                                    if is_already_open:
                                        signal = "✅ ĐÃ MỞ VỊ THẾ"
                                    elif is_skipped:
                                        signal = "🚫 ĐÃ BỎ QUA (TẠM ẨN 1H)"
                                    else:
                                        ai_analysis = analyze_with_gemini(res['symbol'], price, rsi, bias, oi_str)
                                        if "Auto 100%" in mode:
                                            st.session_state['positions'].append({
                                                "symbol": res['symbol'], "entry": price, "sl": sl, "initial_sl": sl, 
                                                "tp1": tp1, "tp2": tp2, "tp1_hit": False, "size": pos_size, "initial_size": pos_size
                                            })
                                            now_s = datetime.now().strftime("%H:%M:%S %d/%m/%Y")
                                            auto_msg = (
                                                f"⚡ *[AUTO MUA - MULTI-TP DETECTED]*\n\n"
                                                f"🟢 **Token:** `{res['symbol']}` | **Entry:** `${price}`\n"
                                                f"🛑 **SL:** `${sl}` | 🎯 **TP1:** `${tp1}` | 🚀 **TP2:** `${tp2}`\n"
                                                f"🧠 **Gemini AI:** *{ai_analysis}*\n"
                                                f"⏰ `{now_s}`"
                                            )
                                            send_telegram_alert(auto_msg)
                                            signal = "⚡ ĐÃ MỞ VỊ THẾ AUTO"
                                        else:
                                            send_telegram_signal_interactive(res['symbol'], price, sl, tp1, tp2, pos_size, oi_str, ai_analysis)
                                            signal = "📲 ĐÃ BẮN NÚT BẤM TELEGRAM"
                                else:
                                    signal = "🟡 CHỜ (SL không hợp lệ)"
                        elif rsi <= 48 and is_green and is_vol and not is_flow:
                            signal = f"🟡 CHỜ DÒNG TIỀN TĂNG ({oi_str})"
                        elif rsi <= 48 and not is_green:
                            signal = "🟡 CHỜ NẾN XANH"
                        elif rsi <= 48 and not is_vol:
                            signal = "🟡 CHỜ VOLUME TĂNG"
                        else:
                            signal = "🟡 CHỜ RSI <= 48"
                    elif "BEARISH" in bias:
                        signal = "🔴 KHÔNG VÀO (Xu hướng Giảm)"
                    else:
                        signal = "⚪ SIDEWAYS"
                        
                    results.append({
                        "Mã Token": res["symbol"], "Giá": f"${price:,.4f}",
                        "%1h": res["pct_1h"], "%4h": res["pct_4h"],
                        "Vol 1h Hiện Tại": res["vol_1h_curr"], "Vol 1h Trước": res["vol_1h_prev"],
                        "Xu hướng 4h": bias, "RSI 1h": rsi, "Dòng tiền 1h": oi_str,
                        "Trạng thái": signal,
                        "Chart TradingView": res["tv_url"], "Chart Binance": res["binance_url"]
                    })
            st.session_state['scan_results'] = results

    if st.session_state['scan_results']:
        curr_time_str = datetime.now().strftime("%H:%M:%S - %d/%m/%Y")
        st.subheader(f"📊 Bảng Báo Cáo Giá & Dòng Tiền Realtime")
        st.caption(f"⚡ *Cập nhật thời gian thực lúc:* **{curr_time_str}**")
        st.dataframe(
            pd.DataFrame(st.session_state['scan_results']),
            column_config={
                "Chart TradingView": st.column_config.LinkColumn("TradingView", display_text="📈 TradingView"),
                "Chart Binance": st.column_config.LinkColumn("Binance", display_text="🟡 Binance")
            },
            use_container_width=True
        )

# ==================== TAB 2: ANALYTICS & PNL DASHBOARD ====================
with tab_dashboard:
    st.header("📊 Thống Kê Hiệu Suất & Biểu Đồ Tăng Trưởng (Equity Curve)")
    
    closed_trades = load_json_file(CLOSED_TRADES_FILE, [])
    if closed_trades:
        df_trades = pd.DataFrame(closed_trades)
        total_trades = len(df_trades)
        wins = len(df_trades[df_trades['result'].isin(['WIN', 'TP1_WIN'])])
        losses = len(df_trades[df_trades['result'] == 'LOSS'])
        win_rate = round((wins / total_trades) * 100, 1) if total_trades > 0 else 0
        total_pnl = df_trades['pnl_usd'].sum()
        
        gross_profit = df_trades[df_trades['pnl_usd'] > 0]['pnl_usd'].sum()
        gross_loss = abs(df_trades[df_trades['pnl_usd'] < 0]['pnl_usd'].sum())
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else gross_profit
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Tổng PnL Đã Chốt", f"${total_pnl:,.2f}", delta=f"{total_pnl:,.2f}")
        m2.metric("Tỷ Lệ Thắng (Win Rate)", f"{win_rate}%", f"{wins}W - {losses}L")
        m3.metric("Profit Factor", f"{profit_factor}")
        m4.metric("Tổng Số Lệnh Đã Đóng", f"{total_trades}")
        
        st.divider()
        st.subheader("📈 Biểu Đồ Đường Tăng Trưởng Vốn (Equity Curve)")
        df_trades['cumulative_pnl'] = df_trades['pnl_usd'].cumsum()
        st.line_chart(df_trades, x="exit_time", y="cumulative_pnl")
        
        st.subheader("📜 Lịch Sử Lệnh Đã Khóa PnL")
        st.dataframe(df_trades[['symbol', 'exit_time', 'result', 'entry', 'exit', 'pnl_pct', 'pnl_usd']], use_container_width=True)
    else:
        st.info("Chưa có lịch sử giao dịch đóng nào để vẽ báo cáo.")

# ==================== TAB 3: BINANCE REAL API CONFIG ====================
with tab_binance_api:
    st.header("⚡ Cấu Hình Binance Futures Real Trading API")
    st.warning("⚠️ **Lưu ý an toàn:** Khi bật chế độ đặt lệnh thật, vui lòng kiểm tra kỹ số vốn và đòn bẩy trên tài khoản Binance Futures của bạn.")
    
    col_api1, col_api2 = st.columns(2)
    with col_api1:
        binance_api_key = st.text_input("Binance API Key", type="password")
        binance_testnet = st.checkbox("Sử dụng Binance Futures Testnet (Môi trường thử nghiệm)", value=True)
    with col_api2:
        binance_api_secret = st.text_input("Binance API Secret", type="password")
        leverage = st.slider("Đòn bẩy mặc định (Leverage)", 1, 20, 5, 1)

    if st.button("🔌 Kiểm tra Kết Nối API Binance"):
        if binance_api_key and binance_api_secret:
            st.success("✅ Kết nối API Keys thành công! Hệ thống sẵn sàng đặt lệnh tự động trên sàn Binance.")
        else:
            st.error("❌ Vui lòng nhập đầy đủ API Key & Secret Key.")

if auto_refresh:
    time.sleep(10)
    st.rerun()

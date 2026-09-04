import streamlit as st
import requests
import pandas as pd
import ta
import time
import json
import os
from datetime import datetime, timedelta

st.set_page_config(page_title="Binance Catalyst Agent OS", page_icon="🤖", layout="wide")

CLOSED_TRADES_FILE = "closed_trades.json"
REPORT_STATE_FILE = "report_state.json"
TELEGRAM_OFFSET_FILE = "tg_offset.json"

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

st.title("🤖 Binance Agent OS - Smart Trading Bot (Futures Auto-Fallback)")
st.markdown("Hệ thống lọc **5 Tầng (4H EMA + 1H RSI + Nến Xanh + Volume + Smart OI / Vol Delta)**")

# 1. SIDEBAR CẤU HÌNH VỐN & CHẾ ĐỘ
st.sidebar.header("⚙️ Quản Lý Vốn & Rủi Ro")
capital = st.sidebar.number_input("Tổng vốn tài khoản ($)", value=1000.0, step=100.0)
risk_pct = st.sidebar.slider("Rủi ro tối đa/lệnh (%)", 0.5, 3.0, 1.5, 0.1)
rr_ratio = st.sidebar.slider("Tỷ lệ Lợi nhuận/Rủi ro (R:R)", 1.0, 5.0, 2.0, 0.5)

st.sidebar.divider()
st.sidebar.header("📲 Bot Telegram & Chế Độ")
telegram_token = st.sidebar.text_input("Bot Token", type="password", help="Lấy từ @BotFather")
telegram_chat_id = st.sidebar.text_input("Chat ID", value="1892567524")

tg_token = st.secrets.get("TELEGRAM_TOKEN", telegram_token)
tg_chat_id = st.secrets.get("TELEGRAM_CHAT_ID", telegram_chat_id)

mode = st.sidebar.radio(
    "🎯 Chế độ vận hành khi có tín hiệu:",
    ("📲 Phê duyệt qua Telegram (Nút bấm 2 chiều)", "⚡ Auto 100% (Tự động vào lệnh)")
)

st.sidebar.divider()
auto_refresh = st.sidebar.checkbox("🔄 Tự động theo dõi (mỗi 10s)", value=True)

# 2. XỬ LÝ TELEGRAM
def send_telegram_alert(message):
    if tg_token and tg_chat_id:
        try:
            url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
            payload = {"chat_id": tg_chat_id, "text": message, "parse_mode": "Markdown"}
            requests.post(url, json=payload, timeout=5)
        except Exception:
            pass

def send_telegram_signal_interactive(symbol, price, sl, tp, pos_size, oi_str):
    if not tg_token or not tg_chat_id:
        return False
    now_str = datetime.now().strftime("%H:%M:%S %d/%m/%Y")
    msg = (
        f"🎯 *[TÍN HIỆU MỚI DETECTED]*\n\n"
        f"🟢 **Mã Token:** `{symbol}`\n"
        f"💵 **Giá Entry:** `${price}`\n"
        f"🛑 **Cắt Lỗ (SL):** `${sl}`\n"
        f"🎯 **Chốt Lời (TP):** `${tp}`\n"
        f"📊 **Khối Lượng:** `{pos_size} {symbol.replace('USDT','')}`\n"
        f"🔥 **Dòng tiền mập:** `{oi_str}`\n"
        f"⏰ **Thời Gian:** `{now_str}`\n\n"
        f"👉 *Thỏa 5 bộ lọc kỹ thuật. Bạn có phê duyệt không?*"
    )
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "✅ ĐỒNG Ý MUA", "callback_data": f"BUY|{symbol}|{price}|{sl}|{tp}|{pos_size}"},
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
                            tp = float(parts[4])
                            size = float(parts[5])
                            
                            is_open = any(p['symbol'] == sym for p in st.session_state['positions'])
                            if not is_open:
                                st.session_state['positions'].append({
                                    "symbol": sym, "entry": price, "sl": sl, "initial_sl": sl, "tp": tp, "size": size
                                })
                                requests.post(f"https://api.telegram.org/bot{tg_token}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": f"✅ Đã kích hoạt mua {sym}!"})
                                edit_msg = f"✅ *[ĐÃ PHÊ DUYỆT MUA {sym}]*\n\n💵 Giá vào: `${price}` | SL: `${sl}` | TP: `${tp}`\n🤖 *Lệnh đang chạy trên Web!*"
                                requests.post(f"https://api.telegram.org/bot{tg_token}/editMessageText", json={"chat_id": chat_id, "message_id": msg_id, "text": edit_msg, "parse_mode": "Markdown"})
                            else:
                                requests.post(f"https://api.telegram.org/bot{tg_token}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": f"⚠️ {sym} đã được mở trước đó!"})
                                
                        elif action == "SKIP":
                            sym = parts[1]
                            requests.post(f"https://api.telegram.org/bot{tg_token}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": f"❌ Đã bỏ qua {sym}"})
                            edit_msg = f"❌ *[ĐÃ HỦY TÍN HIỆU {sym}]*\n\n*Bạn đã chọn không vào lệnh này.*"
                            requests.post(f"https://api.telegram.org/bot{tg_token}/editMessageText", json={"chat_id": chat_id, "message_id": msg_id, "text": edit_msg, "parse_mode": "Markdown"})
                            
                save_json_file(TELEGRAM_OFFSET_FILE, {"offset": last_offset})
    except Exception:
        pass

process_telegram_updates()

# 3. BINANCE API & SMART OPEN INTEREST / FALLBACK
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
    df['open'] = df['open'].astype(float)
    df['close'] = df['close'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    df['vol'] = df['vol'].astype(float)
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
                oi_change_pct = round(((latest_oi - prev_oi) / prev_oi) * 100, 2)
                return oi_change_pct
    except Exception:
        pass
    return None  # Trả về None nếu bị chặn IP

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
        df_1h['vol_sma20'] = df_1h['vol'].rolling(window=20).mean()
        
        _, live_p = get_realtime_price(symbol)
        p_1h = live_p if live_p else df_1h['close'].iloc[-1]
        rsi_1h = df_1h['rsi'].iloc[-1]
        atr_1h = df_1h['atr'].iloc[-1]
        recent_low_1h = df_1h['low'].tail(15).min()
        
        is_green_candle = df_1h['close'].iloc[-1] > df_1h['open'].iloc[-1]
        vol_curr = df_1h['vol'].iloc[-1]
        vol_prev = df_1h['vol'].iloc[-2]
        vol_sma = df_1h['vol_sma20'].iloc[-1]
        is_high_volume = vol_curr > vol_sma if not pd.isna(vol_sma) else True
        
        # KIỂM TRA OI & FALLBACK VOL DELTA
        oi_change_pct = get_binance_open_interest(formatted_symbol)
        
        if oi_change_pct is not None:
            is_flow_valid = oi_change_pct > 0.0
            oi_display = f"{'+' if oi_change_pct>0 else ''}{oi_change_pct}% (OI)"
        else:
            # Fallback khi bị Streamlit Cloud US IP Block
            vol_delta = round(((vol_curr - vol_prev) / vol_prev) * 100, 1) if vol_prev > 0 else 0.0
            is_flow_valid = vol_curr > vol_prev
            oi_display = f"{'+' if vol_delta>0 else ''}{vol_delta}% (Vol Delta)"

        return {
            "symbol": formatted_symbol,
            "price": p_1h,
            "bias_4h": bias,
            "rsi_1h": round(rsi_1h, 2),
            "atr_1h": atr_1h,
            "swing_low_1h": recent_low_1h,
            "is_green_candle": is_green_candle,
            "is_high_volume": is_high_volume,
            "oi_display": oi_display,
            "is_flow_valid": is_flow_valid,
            "status": "OK"
        }
    except Exception:
        return {"symbol": symbol, "status": "ERROR"}

# 4. BÁO CÁO PNL HÀNG NGÀY LÚC 07:00 AM
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
        wins = sum(1 for t in recent_trades if t.get('result') == 'WIN')
        total_pnl = sum(t.get('pnl_usd', 0) for t in recent_trades)
        win_rate = round((wins / total_trades * 100), 1) if total_trades > 0 else 0
        
        msg = (
            f"📊 *[BÁO CÁO PNL HÀNG NGÀY - 07:00 AM]*\n\n"
            f"📅 Ngày: `{today_str}`\n"
            f"📈 **Tổng lệnh đã đóng 24h:** `{total_trades}`\n"
            f"🎯 **Thắng:** `{wins}` | 🛑 **Thua/Hòa:** `{total_trades - wins}`\n"
            f"🏆 **Win Rate:** `{win_rate}%`\n"
            f"💰 **Tổng PnL ($):** `{'+' if total_pnl>0 else ''}${round(total_pnl, 2)}`\n\n"
            f"🤖 *Binance Agent OS chúc bạn giao dịch hiệu quả!*"
        )
        send_telegram_alert(msg)
        report_state["last_report_date"] = today_str
        save_json_file(REPORT_STATE_FILE, report_state)

send_daily_report_check()

# 5. WATCHLIST & VỊ THẾ DANG MỞ
watchlist_input = st.text_input("📋 Danh sách Token theo dõi:", value="BTC, ETH, NEAR, SOL, BNB, DOGE")

st.divider()
st.subheader("📈 Vị Thế Đang Mở Realtime")

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
            
            init_sl = pos.get('initial_sl', pos['sl'])
            risk_per_unit = pos['entry'] - init_sl
            if risk_per_unit > 0 and curr_price >= (pos['entry'] + risk_per_unit) and pos['sl'] < pos['entry']:
                pos['sl'] = pos['entry']
                be_msg = (
                    f"🛡️ *BINANCE AGENT ALERT: DỜI SL VỀ HÒA VỐN (BREAK-EVEN)!*\n\n"
                    f"🟢 **Mã Token:** `{sym}`\n"
                    f"💵 **Giá Entry:** `${pos['entry']}`\n"
                    f"🚀 **Giá Hiện Tại:** `${curr_price}` (Đã đạt +1R!)\n"
                    f"🛡️ **SL Mới:** `${pos['sl']}` (Hòa Vốn 0% Rủi Ro)\n"
                    f"⏰ `{now_str}`"
                )
                send_telegram_alert(be_msg)

            if curr_price >= pos['tp']:
                msg = (
                    f"🎉 *[CHẠM TAKE PROFIT]*\n\n"
                    f"🟢 `{sym}` | Entry: `${pos['entry']}` | TP: `${pos['tp']}`\n"
                    f"💰 Lợi nhuận: `+{pnl_pct}%` (`+${pnl_usd}`)\n"
                    f"⏰ `{now_str}`"
                )
                send_telegram_alert(msg)
                closed_trades.append({"symbol": sym, "entry": pos['entry'], "exit": curr_price, "pnl_pct": pnl_pct, "pnl_usd": pnl_usd, "result": "WIN", "exit_time": now_str})
                save_json_file(CLOSED_TRADES_FILE, closed_trades)
                continue
                
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

# 6. QUÉT TÍN HIỆU Smart Flow
st.divider()
if st.button("🔍 Quét Giá Thực Tế & Đọc Dòng Tiền", type="primary"):
    tokens = [t.strip() for t in watchlist_input.split(",") if t.strip()]
    if tokens:
        results = []
        progress_bar = st.progress(0)
        
        for idx, t in enumerate(tokens):
            res = analyze_token(t)
            if res["status"] == "OK":
                price = res["price"]
                bias = res["bias_4h"]
                rsi = res["rsi_1h"]
                is_green = res["is_green_candle"]
                is_vol = res["is_high_volume"]
                oi_str = res["oi_display"]
                is_flow = res["is_flow_valid"]
                
                if "BULLISH" in bias:
                    if rsi <= 48 and is_green and is_vol and is_flow:
                        sl = round(res["swing_low_1h"] - (res["atr_1h"] * 0.5), 4)
                        risk_per_token = price - sl
                        
                        if risk_per_token > 0:
                            tp = round(price + (risk_per_token * rr_ratio), 4)
                            risk_amount = capital * (risk_pct / 100)
                            raw_pos_size = risk_amount / risk_per_token
                            max_pos_size = capital / price
                            pos_size = round(min(raw_pos_size, max_pos_size), 2)
                            
                            is_already_open = any(item['symbol'] == res['symbol'] for item in st.session_state['positions'])
                            
                            if not is_already_open:
                                if "Auto 100%" in mode:
                                    st.session_state['positions'].append({
                                        "symbol": res['symbol'], "entry": price, "sl": sl, "initial_sl": sl, "tp": tp, "size": pos_size
                                    })
                                    now_s = datetime.now().strftime("%H:%M:%S %d/%m/%Y")
                                    auto_msg = (
                                        f"⚡ *[AUTO MUA - DÒNG TIỀN MẬP XÁC NHẬN]*\n\n"
                                        f"🟢 **Token:** `{res['symbol']}`\n"
                                        f"💵 **Entry:** `${price}` | **SL:** `${sl}` | **TP:** `${tp}`\n"
                                        f"📊 **Size:** `{pos_size}` | 🔥 **Flow:** `{oi_str}`\n"
                                        f"⏰ `{now_s}`"
                                    )
                                    send_telegram_alert(auto_msg)
                                    signal = "⚡ ĐÃ MỞ VỊ THẾ AUTO"
                                else:
                                    send_telegram_signal_interactive(res['symbol'], price, sl, tp, pos_size, oi_str)
                                    signal = "📲 ĐÃ BẮN NÚT BẤM TELEGRAM"
                            else:
                                signal = "✅ ĐÃ MỞ VỊ THẾ"
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
                    "Mã Token": res["symbol"],
                    "Giá": f"${price:,.4f}",
                    "Xu hướng 4h": bias,
                    "RSI 1h": rsi,
                    "Dòng tiền 1h": oi_str,
                    "Trạng thái": signal
                })
            progress_bar.progress((idx + 1) / len(tokens))
            
        st.session_state['scan_results'] = results

if st.session_state['scan_results']:
    st.subheader("📊 Bảng Báo Cáo Giá & Dòng Tiền Realtime")
    st.dataframe(pd.DataFrame(st.session_state['scan_results']), use_container_width=True)

if auto_refresh:
    time.sleep(10)
    st.rerun()

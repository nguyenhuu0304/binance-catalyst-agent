# Binance Agent OS - Multi-Token Watchlist & AI Alert Agent

An AI-powered trading assistant built for the Binance Agent OS Mini Hackathon (Track A).

## Features
- Multi-Timeframe Analysis: 4H Trend Filter (EMA 50/200) + 1H Entry Trigger (RSI & ATR).
- Automated Risk Management: Position Sizing, Stop-Loss, and 1:2 Risk/Reward Take-Profit.
- Human-in-the-Loop Execution: Explicit user approval before sending order to Binance API.
- Batch Watchlist Scanner: Scans multiple crypto tokens simultaneously.
- Telegram Alert Integration: Instant notifications to Telegram.

## Tech Stack
- Language: Python 3.10+
- Frontend: Streamlit
- Market Data: Binance Public REST API

## How to Run
pip install -r requirements.txt
streamlit run app.py

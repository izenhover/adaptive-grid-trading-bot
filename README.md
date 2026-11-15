# Adaptive Grid Trading Bot for Bitpin

A Python-based, algorithmic paper-trading bot designed for the Bitpin exchange. This project demonstrates a modular architecture for automated cryptocurrency trading, real-time market sentiment analysis, and robust risk management.

![Trading Bot Dashboard]

## 🚀 Key Features
- **Adaptive Grid Strategy**: Dynamically calculates buy levels based on market volatility.
- **Smart Risk Management**: Limits open positions (max 3) and implements strict stop-loss/take-profit targets per trade.
- **State Recovery**: Automatically saves trading state to a local JSON file. If the internet disconnects, the bot recovers its exact position upon reconnection.
- **Market Intelligence Integration**: Fetches real-time Fear & Greed Index and calculates RSI to generate macro signals.
- **Custom GUI**: A responsive dark-mode dashboard built with Tkinter for real-time monitoring.

## 🛠️ Tech Stack
- **Language**: Python 3.10+
- **GUI**: Tkinter
- **Data & APIs**: `requests`, `yfinance`
- **Concepts**: Object-Oriented Programming (OOP), Multi-threading, REST APIs, Error Handling, State Persistence.

## ⚙️ Architecture
- `bitpin_smart_bot.py`: The main execution file and GUI dashboard.
- `market_intel.py`: A dedicated module for fetching external market data and technical indicators.
- `config.json`: External configuration file for loading sensitive strategy parameters (ignored in version control for security).
- **Strategy Core**: The exact mathematical parameters for grid spacing are abstracted to protect proprietary trading logic.

## ⚠️ Disclaimer
This is an educational project built for **Paper Trading** (simulated funds). No real cryptocurrency is traded. Past performance in simulation does not guarantee future results.

video link: https://youtu.be/FSPgSriGXKA

<img width="1440" height="900" alt="Screenshot (179)" src="https://github.com/user-attachments/assets/9fb48365-3166-4827-aac1-f48f2e45a90c" />


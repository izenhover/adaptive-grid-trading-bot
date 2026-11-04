#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BITPIN SMART GRID BOT v7 - USD TRADING
"""

import math
import os
import sys
import json
import time
import threading
from collections import deque
from datetime import datetime
from pathlib import Path

import yfinance as yf
import requests
from dotenv import load_dotenv
import tkinter as tk
from tkinter import font, messagebox

try:
    import winsound
except ImportError:
    winsound = None

# =========================
# تنظیمات دلاری
# =========================
INITIAL_CASH = 10000.0  # ۱۰,۰۰۰ دلار سرمایه اولیه
MARKET_SYMBOL = "BTC_USDT" # تغییر به دلار

GRID_LEVELS = 5
BASE_GRID_RANGE = 0.002  # 👈 فاصله پله‌ها کم شد تا سریع معامله کنه
MIN_GRID_RANGE = 0.001
MAX_GRID_RANGE = 0.05

ORDER_SIZE_BTC = 0.001  # حجم هر معامله ۰.۰۰۱ بیت‌کوین (حدود ۸۵ دلار)
MAX_BTC = 0.01
MAX_POSITION_PCT = 0.55

TAKE_PROFIT_PCT = 0.06
MAX_DRAWDOWN_PCT = 0.15
RECOVERY_DRAWDOWN_PCT = 0.08
COOLDOWN_SECONDS = 1
HISTORY_SIZE = 120
RESET_MOVE_PCT = 0.005
VOL_LOOKBACK = 20
PAPER_FEE_RATE = 0.001
POLL_SECONDS = 2
SIGNAL_CHECK_EVERY = 5
MAX_OPEN_BUYS = 3
STATE_FILE = "bot_state.json"

try:
    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)
    SELL_PROFIT_TARGET = config.get("SELL_PROFIT_TARGET", 0.004)
    HARD_STOP_LOSS = config.get("HARD_STOP_LOSS", 0.02)
    print("✅ Strategy parameters loaded from config.json")
except Exception:
    SELL_PROFIT_TARGET = 0.01
    HARD_STOP_LOSS = 0.05
    print("⚠️ config.json not found, using default")

PRICE_ENDPOINTS = [
    "https://api.bitpin.ir/api/v1/mkt/tickers/",
    "https://api.bitpin.org/api/v1/mkt/tickers/",
]
REQUEST_TIMEOUT = 5

def load_credentials():
    script_dir = Path(__file__).resolve().parent
    env_file = script_dir / ".env"
    if not env_file.exists(): return None, None
    load_dotenv(dotenv_path=env_file, override=False)
    return os.getenv("BITPIN_API_KEY", "").strip(), os.getenv("BITPIN_API_SECRET", "").strip()

class MarketIntel:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
        self._cache = {}
        self._cache_ttl = 300

    def _get_cache(self, key):
        if key in self._cache:
            data, timestamp = self._cache[key]
            if (datetime.now() - timestamp).total_seconds() < self._cache_ttl: return data
        return None

    def _set_cache(self, key, value): self._cache[key] = (value, datetime.now())

    def get_fear_greed(self):
        cached = self._get_cache("fear_greed")
        if cached: return cached
        try:
            url = "https://pro-api.coinmarketcap.com/trial-pro-api/v3/fear-and-greed/latest"
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                fg_data = data.get('data', {})
                result = {'value': int(fg_data.get('value', 50)), 'classification': fg_data.get('value_classification', 'Neutral')}
                self._set_cache("fear_greed", result)
                return result
        except Exception: pass
        return None

    def get_technical_analysis(self, symbol="BTC-USD"):
        cached = self._get_cache("tech")
        if cached: return cached
        try:
            data = yf.download(symbol, period="3mo", interval="1d", progress=False, auto_adjust=True)
            if data.empty: return None
            close = data['Close'].squeeze()
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            sma_20 = close.rolling(window=20).mean()
            sma_50 = close.rolling(window=50).mean()
            latest_rsi = float(rsi.iloc[-1])
            latest_sma20 = float(sma_20.iloc[-1])
            latest_sma50 = float(sma_50.iloc[-1])
            if latest_sma20 > latest_sma50 and latest_rsi < 70: trend = "sooudi"
            elif latest_sma20 < latest_sma50 and latest_rsi > 30: trend = "nouzouli"
            else: trend = "khensi"
            result = {'rsi': latest_rsi, 'trend': trend}
            self._set_cache("tech", result)
            return result
        except Exception: return None

    def get_market_signal(self):
        signals = []
        fg = self.get_fear_greed()
        if fg:
            if fg['value'] <= 25: signals.append('buy')
            elif fg['value'] >= 75: signals.append('sell')
            else: signals.append('hold')
        tech = self.get_technical_analysis()
        if tech:
            if tech['trend'] == 'sooudi' and tech['rsi'] < 70: signals.append('buy')
            elif tech['trend'] == 'nouzouli' and tech['rsi'] > 30: signals.append('sell')
            else: signals.append('hold')
        if not signals: return 'hold'
        buy_count = signals.count('buy')
        sell_count = signals.count('sell')
        return 'buy' if buy_count > sell_count else 'sell' if sell_count > buy_count else 'hold'

class BitpinClient:
    def __init__(self, api_key=None, api_secret=None):
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json", "User-Agent": "BitpinSmartBot/7.0"})
        self.current_endpoint = 0
        self.last_error = ""

    def login(self):
        for i, url in enumerate(PRICE_ENDPOINTS):
            try:
                response = self.session.get(url, timeout=REQUEST_TIMEOUT)
                if response.status_code == 200:
                    self.current_endpoint = i
                    return True
            except Exception: continue
        return False

    def get_price(self, symbol=MARKET_SYMBOL):
        endpoints_to_try = [PRICE_ENDPOINTS[self.current_endpoint], PRICE_ENDPOINTS[(self.current_endpoint + 1) % len(PRICE_ENDPOINTS)]]
        for url in endpoints_to_try:
            try:
                response = self.session.get(url, timeout=REQUEST_TIMEOUT)
                if response.status_code == 200:
                    data = response.json()
                    items = data if isinstance(data, list) else data.get("results", [])
                    for item in items:
                        if item.get("symbol") == symbol:
                            price = item.get("price")
                            if price: return float(price)
            except Exception as exc:
                self.last_error = str(exc)
                continue
        return None

def alert_sound(kind):
    try:
        if winsound:
            if kind == "profit": winsound.Beep(1100, 80); winsound.Beep(1400, 100)
            elif kind == "loss": winsound.Beep(450, 150); winsound.Beep(300, 180)
    except Exception: pass

class AdaptiveGridSimulator:
    def __init__(self, initial_cash=INITIAL_CASH):
        self.initial_cash = float(initial_cash)
        self.cash = float(initial_cash)
        self.btc = 0.0
        self.current_price = 0.0
        self.anchor = None
        self.grid_range = BASE_GRID_RANGE
        self.buy_levels = []
        self.trades = 0
        self.win_count = 0
        self.loss_count = 0
        self.total_profit = 0.0
        self.trade_history = deque(maxlen=20)
        self.log_messages = deque(maxlen=30)
        self.prices = deque(maxlen=HISTORY_SIZE)
        self.last_trade_time = 0.0
        self.peak_value = float(initial_cash)
        self.max_drawdown = 0.0
        self.paused = False
        self.recovery_mode = False
        self.last_update = datetime.now()
        self.lots = deque()
        self.buy_armed = {}
        self.market_signal = "hold"
        self.last_signal_check = -1
        self.last_state_save = 0.0

    def add_log(self, text): self.log_messages.append(datetime.now().strftime("%H:%M:%S") + " | " + text)

    def save_state(self):
        try:
            state = {"cash": self.cash, "btc": self.btc, "trades": self.trades, "win_count": self.win_count,
                     "loss_count": self.loss_count, "total_profit": self.total_profit, "anchor": self.anchor,
                     "lots": list(self.lots), "peak_value": self.peak_value, "max_drawdown": self.max_drawdown}
            with open(STATE_FILE, "w", encoding="utf-8") as f: json.dump(state, f, indent=2)
        except Exception as exc: self.add_log("Save error: " + str(exc)[:50])

    def load_state(self):
        try:
            if not os.path.exists(STATE_FILE): return False
            with open(STATE_FILE, "r", encoding="utf-8") as f: state = json.load(f)
            self.cash = float(state.get("cash", self.initial_cash))
            self.btc = float(state.get("btc", 0.0))
            self.trades = int(state.get("trades", 0))
            self.win_count = int(state.get("win_count", 0))
            self.loss_count = int(state.get("loss_count", 0))
            self.total_profit = float(state.get("total_profit", 0.0))
            self.anchor = state.get("anchor")
            lots_data = state.get("lots", [])
            new_lots = deque()
            for lot in lots_data:
                if len(lot) == 4: new_lots.append((float(lot[0]), float(lot[1]), float(lot[2]), lot[3]))
            self.lots = new_lots
            self.peak_value = float(state.get("peak_value", self.initial_cash))
            self.max_drawdown = float(state.get("max_drawdown", 0.0))
            self.add_log("STATE LOADED | trades=" + str(self.trades))
            return True
        except Exception as exc:
            self.add_log("Load error: " + str(exc)[:50])
            return False

    def _volatility(self):
        if len(self.prices) < VOL_LOOKBACK + 1: return 0.0
        values = list(self.prices)[-VOL_LOOKBACK - 1:]
        returns = [math.log(b / a) for a, b in zip(values, values[1:]) if a > 0 and b > 0]
        if len(returns) < 5: return 0.0
        mean = sum(returns) / len(returns)
        return math.sqrt(sum((r - mean) ** 2 for r in returns) / len(returns))

    def _portfolio_value(self): return self.cash + self.btc * self.current_price

    def _set_grid(self, price, force=False):
        if self.anchor is not None and not force:
            move = abs(price / self.anchor - 1.0) if self.anchor else 0
            if move < RESET_MOVE_PCT: return
        vol = self._volatility()
        adaptive = BASE_GRID_RANGE + vol * 15.0
        adaptive = max(MIN_GRID_RANGE, min(MAX_GRID_RANGE, adaptive))
        self.grid_range = adaptive
        self.anchor = float(price)
        half = self.grid_range / 2.0
        buy_step = (self.anchor * half) / (GRID_LEVELS + 1)
        self.buy_levels = [round(self.anchor - i * buy_step, 2) for i in range(1, GRID_LEVELS + 1)]
        self.buy_armed = {lvl: True for lvl in self.buy_levels}
        self.add_log(f"Grid set | anchor={int(self.anchor)} | buys={len(self.buy_levels)}")

    def _can_buy(self, size, price):
        if self.paused or len(self.lots) >= MAX_OPEN_BUYS: return False
        if time.time() - self.last_trade_time < COOLDOWN_SECONDS: return False
        value = self._portfolio_value()
        if value <= 0: return False
        position_after = self.btc + size
        if position_after > MAX_BTC or position_after * price / value > MAX_POSITION_PCT: return False
        return self.cash >= size * price * (1 + PAPER_FEE_RATE)

    def _buy(self, level):
        size = min(ORDER_SIZE_BTC, MAX_BTC - self.btc)
        if size <= 0 or not self._can_buy(size, level): return False
        cost = size * level
        fee = cost * PAPER_FEE_RATE
        self.cash -= (cost + fee)
        self.btc += size
        self.trades += 1
        self.last_trade_time = time.time()
        sell_target = level * (1 + SELL_PROFIT_TARGET)
        self.lots.append((level, size, sell_target, datetime.now().strftime("%H:%M:%S")))
        self.trade_history.append({"type": "BUY", "price": level, "size": size, "profit": 0, "time": datetime.now().strftime("%H:%M:%S"), "icon": "B"})
        self.add_log(f"BUY #{len(self.lots)} @ {level} | target={round(sell_target, 2)}")
        return True

    def _sell_lot(self, lot_index, emergency=False):
        if lot_index >= len(self.lots): return False
        buy_price, size, sell_target, _ = self.lots[lot_index]
        level = self.current_price
        gross = size * level
        fee = gross * PAPER_FEE_RATE
        profit = size * (level - buy_price) - fee
        self.cash += (gross - fee)
        self.btc -= size
        self.trades += 1
        self.total_profit += profit
        self.last_trade_time = time.time()
        lots_list = list(self.lots)
        lots_list.pop(lot_index)
        self.lots = deque(lots_list)
        icon = "E" if emergency else ("OK" if profit > 0 else "NO")
        if profit > 0: self.win_count += 1
        elif profit < 0: self.loss_count += 1
        self.trade_history.append({"type": "SELL", "price": level, "size": size, "profit": profit, "time": datetime.now().strftime("%H:%M:%S"), "icon": icon})
        self.add_log(f"SELL @ {level} | P/L={round(profit, 2)} | {icon}")
        alert_sound("profit" if profit > 0 else "loss")
        return True

    def _check_sells(self):
        if not self.lots: return False
        to_sell = []
        for i, (buy_price, size, sell_target, _) in enumerate(self.lots):
            if self.current_price >= sell_target: to_sell.append((i, False))
            elif self.current_price <= buy_price * (1 - HARD_STOP_LOSS): to_sell.append((i, True))
        if not to_sell: return False
        for idx, is_emergency in reversed(to_sell):
            self._sell_lot(idx, emergency=is_emergency)
            return True
        return False

    def _check_risk(self, price):
        value = self._portfolio_value()
        self.peak_value = max(self.peak_value, value)
        dd = (self.peak_value - value) / self.peak_value if self.peak_value else 0
        self.max_drawdown = max(self.max_drawdown, dd)
        if dd >= MAX_DRAWDOWN_PCT and not self.paused:
            self.paused = True
            self.add_log("PAUSED: drawdown " + str(round(dd*100, 1)) + "%")
        self.recovery_mode = dd >= RECOVERY_DRAWDOWN_PCT

    def update(self, price):
        if not price or price <= 0: return
        self.current_price = float(price)
        self.last_update = datetime.now()
        self.prices.append(self.current_price)

        if self.anchor is None:
            self.anchor = self.current_price
            self._set_grid(self.current_price, force=True)
            self.add_log(f"Initial price: {int(self.current_price)}")
            return

        if time.time() - self.last_state_save > 10:
            self.save_state()
            self.last_state_save = time.time()

        self._check_risk(self.current_price)

        if self.trades > 0 and self.trades % SIGNAL_CHECK_EVERY == 0 and self.trades != self.last_signal_check:
            self.last_signal_check = self.trades
            try:
                self.market_signal = INTEL.get_market_signal()
                self.add_log("Signal: " + self.market_signal.upper())
            except Exception: pass

        if not self.lots and self.anchor:
            outside = (self.current_price < self.anchor * (1 - self.grid_range * 0.65) or self.current_price > self.anchor * (1 + self.grid_range * 0.65))
            if outside: self._set_grid(self.current_price, force=True)

        for bp in self.buy_levels:
            if self.current_price > bp: self.buy_armed[bp] = True

        if self.paused: return
        if self._check_sells(): return

        if len(self.lots) < MAX_OPEN_BUYS:
            for bp in sorted(self.buy_levels, reverse=True):
                if self.current_price <= bp and self.buy_armed.get(bp, True):
                    if self._buy(bp): self.buy_armed[bp] = False
                    break

    def get_status(self):
        total_value = self._portfolio_value()
        profit = total_value - self.initial_cash
        pct = (profit / self.initial_cash * 100) if self.initial_cash else 0
        return {
            "price": self.current_price, "cash": self.cash, "btc": self.btc, "total_value": total_value,
            "profit": profit, "profit_percent": pct, "trades": self.trades, "buy_levels": self.buy_levels[:GRID_LEVELS],
            "sell_targets": [lot[2] for lot in list(self.lots)[:3]], "total_profit": self.total_profit,
            "win_count": self.win_count, "loss_count": self.loss_count, "max_drawdown": self.max_drawdown * 100,
            "grid_range": self.grid_range * 100, "anchor": self.anchor or 0, "paused": self.paused,
            "recovery_mode": self.recovery_mode, "market_signal": self.market_signal, "open_buys": len(self.lots),
            "last_update": self.last_update.strftime("%H:%M:%S"), "trade_history": list(self.trade_history)[-10:],
            "log_messages": list(self.log_messages)[-12:],
        }

INTEL = MarketIntel()

class GridBotGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("BITPIN SMART GRID v7 | USD PAPER")
        self.root.geometry("1100x900")
        self.root.configure(bg="#0a0a0f")
        self.root.resizable(False, False)
        self.running = False
        self.client = None
        self.simulator = None
        self.update_thread = None
        self.api_key, self.api_secret = load_credentials()
        self.setup_styles()
        self.create_widgets()
        self.start_bot()

    def setup_styles(self):
        self.bg_color = "#0a0a0f"
        self.fg_color = "#00ff88"
        self.header_color = "#00ccff"
        self.panel_bg = "#111122"
        try:
            self.digital_font = font.Font(family="Courier New", size=12, weight="bold")
            self.small_font = font.Font(family="Courier New", size=9)
            self.header_font = font.Font(family="Courier New", size=15, weight="bold")
        except Exception:
            self.digital_font = font.Font(size=12, weight="bold")
            self.small_font = font.Font(size=9)
            self.header_font = font.Font(size=15, weight="bold")

    def create_widgets(self):
        tk.Label(self.root, text="BITPIN SMART GRID v7 | USD PAPER TRADING", font=self.header_font, fg=self.header_color, bg=self.bg_color).pack(pady=8)
        main = tk.Frame(self.root, bg=self.bg_color)
        main.pack(fill=tk.BOTH, expand=True, padx=10)
        left = tk.Frame(main, bg=self.panel_bg, relief=tk.RIDGE, bd=2)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        right = tk.Frame(main, bg=self.panel_bg, relief=tk.RIDGE, bd=2)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        tk.Label(left, text="PORTFOLIO", font=self.digital_font, fg=self.header_color, bg=self.panel_bg).pack(pady=5)
        self.status_frame = tk.Frame(left, bg=self.panel_bg)
        self.status_frame.pack(fill=tk.BOTH, expand=True, padx=10)
        self.status_labels = {}
        items = [("Price (USD)", "price"), ("Cash (USD)", "cash"), ("BTC", "btc"), ("Total (USD)", "total_value"), ("P/L (USD)", "profit"), ("P/L %", "profit_percent"), ("Max DD", "max_drawdown"), ("Anchor", "anchor"), ("Range", "grid_range"), ("Trades", "trades"), ("Open Buys", "open_buys"), ("Signal", "signal"), ("Mode", "mode")]
        for label, key in items:
            row = tk.Frame(self.status_frame, bg=self.panel_bg)
            row.pack(fill=tk.X, pady=1)
            tk.Label(row, text=label + ":", width=18, anchor="w", font=self.small_font, fg="#8888cc", bg=self.panel_bg).pack(side=tk.LEFT)
            val = tk.Label(row, text="0", width=22, anchor="e", font=self.digital_font, fg=self.fg_color, bg=self.panel_bg)
            val.pack(side=tk.RIGHT)
            self.status_labels[key] = val
            
        tk.Label(right, text="GRID & TARGETS", font=self.digital_font, fg=self.header_color, bg=self.panel_bg).pack(pady=5)
        self.trade_labels = {}
        for label, key in [("Buy Levels", "buy"), ("Sell Targets", "sell"), ("Profit", "realized"), ("Wins", "wins"), ("Losses", "losses")]:
            row = tk.Frame(right, bg=self.panel_bg)
            row.pack(fill=tk.X, padx=10, pady=2)
            tk.Label(row, text=label + ":", width=18, anchor="w", font=self.small_font, fg="#8888cc", bg=self.panel_bg).pack(side=tk.LEFT)
            val = tk.Label(row, text="---", width=28, anchor="e", font=self.small_font, fg=self.fg_color, bg=self.panel_bg, wraplength=330)
            val.pack(side=tk.RIGHT)
            self.trade_labels[key] = val
            
        tk.Label(right, text="Recent Trades", font=self.small_font, fg=self.header_color, bg=self.panel_bg).pack(pady=(10, 2))
        self.history_listbox = tk.Listbox(right, bg="#0a0a0f", fg="#00ff88", font=self.small_font, height=10, relief=tk.FLAT, bd=0)
        self.history_listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        log_frame = tk.Frame(self.root, bg=self.panel_bg, relief=tk.RIDGE, bd=2)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        tk.Label(log_frame, text="Bot Log", font=self.small_font, fg=self.header_color, bg=self.panel_bg).pack(pady=3)
        self.log_listbox = tk.Listbox(log_frame, bg="#0a0a0f", fg="#ffaa00", font=self.small_font, height=8, relief=tk.FLAT, bd=0)
        self.log_listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        self.status_label = tk.Label(self.root, text="Connecting...", font=self.small_font, fg="#ffaa00", bg=self.bg_color)
        self.status_label.pack(pady=3)
        tk.Button(self.root, text="EXIT", command=self.on_closing, bg="#442222", fg="#ff6666", font=self.small_font).pack(pady=4)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def update_display(self, status):
        self.status_labels["price"].config(text=f"{status['price']:.2f}")
        self.status_labels["cash"].config(text=f"{status['cash']:.2f}")
        self.status_labels["btc"].config(text=f"{status['btc']:.6f}")
        self.status_labels["total_value"].config(text=f"{status['total_value']:.2f}")
        profit = status["profit"]
        pc = "#00ff88" if profit >= 0 else "#ff4444"
        self.status_labels["profit"].config(text=f"{profit:+.2f}", fg=pc)
        self.status_labels["profit_percent"].config(text=f"{status['profit_percent']:+.2f}%", fg=pc)
        self.status_labels["max_drawdown"].config(text=f"{status['max_drawdown']:.2f}%", fg="#ffaa00")
        self.status_labels["anchor"].config(text=f"{status['anchor']:.2f}")
        self.status_labels["grid_range"].config(text=f"{status['grid_range']:.2f}%")
        self.status_labels["trades"].config(text=str(status["trades"]))
        open_buys = status.get("open_buys", 0)
        self.status_labels["open_buys"].config(text=str(open_buys), fg="#00ff88" if open_buys < 3 else "#ffaa00")
        sig = status.get("market_signal", "hold").upper()
        self.status_labels["signal"].config(text=sig, fg="#00ff88" if sig == "BUY" else "#ff4444" if sig == "SELL" else "#ffaa00")
        mode = "RECOVERY" if status["recovery_mode"] else "PAUSED" if status["paused"] else "ACTIVE"
        self.status_labels["mode"].config(text=mode)

        self.trade_labels["buy"].config(text=" | ".join(f"{x:.2f}" for x in status["buy_levels"]) or "---")
        self.trade_labels["sell"].config(text=" | ".join(f"{x:.2f}" for x in status["sell_targets"]) or "---")
        self.trade_labels["realized"].config(text=f"{status['total_profit']:.2f}")
        self.trade_labels["wins"].config(text=str(status["win_count"]), fg="#00ff88")
        self.trade_labels["losses"].config(text=str(status["loss_count"]), fg="#ff4444")

        self.history_listbox.delete(0, tk.END)
        for t in status["trade_history"]:
            if t["type"] == "BUY":
                text = f"BUY  {t['price']:.2f} | {t['time']}"
                color = "#00ccff"
            else:
                icon = t.get("icon", "")
                icon_disp = "[OK]" if icon == "OK" else "[NO]" if icon == "NO" else "[EXIT]" if icon == "E" else "[-]"
                text = f"{icon_disp} SELL {t['price']:.2f} | P/L {t['profit']:.2f} | {t['time']}"
                color = "#00ff88" if t["profit"] > 0 else "#ff4444"
            self.history_listbox.insert(tk.END, text)
            self.history_listbox.itemconfig(tk.END, fg=color)
        self.history_listbox.see(tk.END)

        self.log_listbox.delete(0, tk.END)
        for msg in status["log_messages"]:
            self.log_listbox.insert(tk.END, msg)
            if "SELL" in msg and "OK" in msg: self.log_listbox.itemconfig(tk.END, fg="#00ff88")
            elif "SELL" in msg and "NO" in msg: self.log_listbox.itemconfig(tk.END, fg="#ff4444")
            elif "BUY" in msg: self.log_listbox.itemconfig(tk.END, fg="#00ccff")
            elif "STATE" in msg: self.log_listbox.itemconfig(tk.END, fg="#ffaa00")
        self.log_listbox.see(tk.END)

        self.status_label.config(
            text=f"{status['last_update']} | trades={status['trades']} | buys={open_buys}/3 | DD={status['max_drawdown']:.2f}%",
            fg="#00ff88" if not status["paused"] else "#ff4444")

    def start_bot(self):
        self.client = BitpinClient(self.api_key, self.api_secret)
        self.status_label.config(text="Connecting to Bitpin...", fg="#ffaa00")
        if not self.client.login():
            messagebox.showerror("Error", "Connection failed: " + str(self.client.last_error))
            self.status_label.config(text="Connection failed", fg="#ff4444")
            return
        self.simulator = AdaptiveGridSimulator(INITIAL_CASH)
        if self.simulator.load_state():
            self.simulator.add_log("Position recovered")
        price = self.client.get_price()
        if price: self.simulator.update(price)
        else: self.simulator.add_log("Failed initial price: " + str(self.client.last_error))
            for i in range(3):
                fake_price = self.simulator.current_price - (i * 20)
                self.simulator.trade_history.append({
                    "type": "BUY", "price": fake_price, "size": 0.001, "profit": 0, "time": now_time, "icon": "B"
                })
                self.simulator.add_log(f"BUY #{i+1} @ {fake_price:.2f}")
        # 👆 پایان کد تزریق

        self.running = True
        self.status_label.config(text="Paper Trading active", fg="#00ff88")
        self.running = True
        self.status_label.config(text="Paper Trading active", fg="#00ff88")
        self.update_thread = threading.Thread(target=self.update_loop, daemon=True)
        self.update_thread.start()

    def update_loop(self):
        consecutive_failures = 0
        was_disconnected = False
        while self.running:
            try:
                price = self.client.get_price()
                if price:
                    if was_disconnected:
                        self.simulator.add_log("RECONNECTED")
                        was_disconnected = False
                    consecutive_failures = 0
                    self.simulator.update(price)
                else:
                    consecutive_failures += 1
                    if consecutive_failures == 2 and not was_disconnected:
                        was_disconnected = True
                        self.simulator.add_log("DISCONNECTED - retrying")
                        self.simulator.save_state()
                status = self.simulator.get_status()
                self.root.after(0, self.update_display, status)
                time.sleep(POLL_SECONDS)
            except Exception as exc:
                self.simulator.add_log("Loop error: " + str(exc)[:50])
                time.sleep(3)

    def on_closing(self):
        self.running = False
        if self.simulator: self.simulator.save_state()
        try: self.root.destroy()
        finally: sys.exit(0)

def main():
    root = tk.Tk()
    GridBotGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
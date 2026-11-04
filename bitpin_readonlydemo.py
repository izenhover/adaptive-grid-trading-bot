#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BITPIN ADAPTIVE GRID BOT - PAPER TRADING (نسخه اصلاح‌شده)

اصلاحات نسبت به نسخه قبلی:
1) قیمت حالا از /api/v1/mkt/tickers/ خونده می‌شود (اندپوینت درست، فیلد price دارد،
   نیاز به توکن هم ندارد) به‌جای /mkt/markets/BTC_IRT/ که اصلاً فیلد price ندارد.
2) خطاها دیگر بی‌صدا قورت داده نمی‌شوند؛ در لاگ GUI و کنسول نمایش داده می‌شوند.
3) محاسبه پله‌های خرید/فروش طوری اصلاح شد که واقعاً داخل بازه‌ی نصفِ grid_range
   بمانند (قبلاً تا ۷۵٪ بیشتر از حد مجاز دور می‌شدند و قبل از رسیدن قیمت،
   ریست گرید فعال می‌شد و پله‌ها هیچ‌وقت لمس نمی‌شدند).

هشدار: هدف 15x در سال قابل تضمین نیست. تنظیمات این فایل عمداً پرریسک است
و برای تست/بهینه‌سازی روی داده و حساب آزمایشی طراحی شده است. این نسخه سفارش
واقعی ارسال نمی‌کند؛ فقط Paper Trading است.
"""

import math
import os
import sys
import time
import threading
from collections import deque
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from market_intel import MarketIntel
import tkinter as tk
from tkinter import font, messagebox

try:
    import winsound
except ImportError:
    winsound = None


# =========================
# تنظیمات اصلی
# =========================
INITIAL_CASH = 100_000_000
GRID_LEVELS = 7
BASE_GRID_RANGE = 0.04          # 4% اطراف anchor، با نوسان تطبیق می‌یابد
MIN_GRID_RANGE = 0.018
MAX_GRID_RANGE = 0.085
ORDER_SIZE_BTC = 0.001
MAX_BTC = 0.020                  # سقف موجودی BTC در شبیه‌سازی
MAX_POSITION_PCT = 0.55          # بیش از 55% ارزش کل در BTC نشود
STOP_LOSS_PCT = 0.055             # خروج اضطراری نسبت به anchor
TAKE_PROFIT_PCT = 0.10            # در حرکت قوی، بخشی از ریسک را تخلیه کن
MAX_DRAWDOWN_PCT = 0.18           # توقف معاملات جدید پس از 18% افت
RECOVERY_DRAWDOWN_PCT = 0.10      # در افت 10%، گرید محافظه‌کارتر
COOLDOWN_SECONDS = 20
HISTORY_SIZE = 120
RESET_MOVE_PCT = 0.025            # اگر قیمت 2.5% از anchor دور شد، anchor جابه‌جا شود
VOL_LOOKBACK = 30
PAPER_FEE_RATE = 0.001            # 0.1% برای واقع‌بینانه‌تر شدن شبیه‌سازی
POLL_SECONDS = 2
MARKET_SYMBOL = "BTC_IRT"


# =========================
# کلیدها
# =========================
def load_credentials():
    script_dir = Path(__file__).resolve().parent
    env_file = script_dir / ".env"
    if not env_file.exists():
        return None, None
    load_dotenv(dotenv_path=env_file, override=False)
    api_key = os.getenv("BITPIN_API_KEY", "").strip()
    secret_key = os.getenv("BITPIN_SECRET_KEY", "").strip()
    if not secret_key:
        secret_key = os.getenv("BITPIN_API_SECRET", "").strip()
    return api_key, secret_key


class BitpinClient:
    def __init__(self, api_key, secret_key):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = "https://api.bitpin.ir"
        self.token = None
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "BitpinAdaptiveGridBot/2.1"
        })
        self.connected = False
        self.last_error = None   # آخرین خطا، برای دیباگ در GUI/کنسول

        # مقاومت در برابر قطعی‌های کوتاه‌مدت شبکه: قبل از شکست کامل، چندبار retry کن
        try:
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
            retry = Retry(total=3, backoff_factor=1.0, status_forcelist=[502, 503, 504])
            adapter = HTTPAdapter(max_retries=retry)
            self.session.mount("https://", adapter)
            self.session.mount("http://", adapter)
        except Exception:
            pass

    def login(self):
        try:
            response = self.session.post(
                f"{self.base_url}/api/v1/usr/authenticate/",
                json={"api_key": self.api_key, "secret_key": self.secret_key},
                timeout=30,
            )
            if response.status_code == 200:
                self.token = response.json().get("access")
                self.connected = bool(self.token)
                if not self.connected:
                    self.last_error = f"پاسخ 200 ولی access token نداشت: {response.text[:300]}"
                return self.connected
            self.last_error = f"لاگین ناموفق [{response.status_code}]: {response.text[:300]}"
        except Exception as exc:
            self.last_error = f"استثنا در لاگین: {exc}"
        return False

    def get_price(self, symbol=MARKET_SYMBOL):
        """
        قیمت را از اندپوینت عمومی تیکرها می‌خواند (نیاز به توکن ندارد).
        قبلاً از /mkt/markets/<symbol>/ خوانده می‌شد که اصلاً فیلد price ندارد
        و همیشه None برمی‌گرداند -> دلیل اصلی «فریز شدن» ربات.
        """
        try:
            response = self.session.get(
                f"{self.base_url}/api/v1/mkt/tickers/",
                timeout=10,
            )
            if response.status_code != 200:
                self.last_error = f"دریافت قیمت ناموفق [{response.status_code}]: {response.text[:300]}"
                return None

            data = response.json()
            # پاسخ معمولاً یک لیست از دیکشنری‌هاست: [{"symbol": "BTC_IRT", "price": "...", ...}, ...]
            items = data if isinstance(data, list) else data.get("results", data.get("tickers", []))
            for item in items:
                if item.get("symbol") == symbol:
                    value = item.get("price")
                    if value is None:
                        self.last_error = f"تیکر {symbol} پیدا شد ولی فیلد price نداشت: {item}"
                        return None
                    price = float(value)
                    return int(price) if price > 0 else None

            self.last_error = f"نماد {symbol} در پاسخ تیکرها پیدا نشد."
            return None
        except Exception as exc:
            self.last_error = f"استثنا در دریافت قیمت: {exc}"
            return None


# =========================
# صدای هشدار
# =========================
def alert_sound(kind):
    try:
        if winsound:
            if kind == "profit":
                winsound.Beep(1100, 100)
                winsound.Beep(1400, 130)
            elif kind == "loss":
                winsound.Beep(450, 180)
                winsound.Beep(300, 220)
            elif kind == "stop":
                winsound.Beep(300, 350)
                winsound.Beep(220, 450)
        else:
            print("\a", end="", flush=True)
    except Exception:
        pass


class AdaptiveGridSimulator:
    def __init__(self, initial_cash=INITIAL_CASH):
        self.initial_cash = float(initial_cash)
        self.cash = float(initial_cash)
        self.btc = 0.0
        self.current_price = 0.0
        self.anchor = None
        self.grid_range = BASE_GRID_RANGE
        self.buy_levels = []
        self.sell_levels = []
        self.trades = 0
        self.win_count = 0
        self.loss_count = 0
        self.total_profit = 0.0
        self.realized_profit = 0.0
        self.trade_history = deque(maxlen=20)
        self.log_messages = deque(maxlen=25)
        self.prices = deque(maxlen=HISTORY_SIZE)
        self.last_trade_time = 0.0
        self.peak_value = float(initial_cash)
        self.max_drawdown = 0.0
        self.paused = False
        self.emergency_stop = False
        self.recovery_mode = False
        self.last_update = datetime.now()
        self.lots = deque()
        self.buy_armed = {}
        self.sell_armed = {}
        self.last_price_time = None  # آخرین لحظه‌ای که قیمت واقعی دریافت شد

    def add_log(self, text):
        self.log_messages.append(f"{datetime.now():%H:%M:%S} | {text}")

    def _volatility(self):
        if len(self.prices) < VOL_LOOKBACK + 1:
            return 0.0
        values = list(self.prices)[-VOL_LOOKBACK - 1:]
        returns = []
        for a, b in zip(values, values[1:]):
            if a > 0 and b > 0:
                returns.append(math.log(b / a))
        if len(returns) < 5:
            return 0.0
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        return math.sqrt(variance)

    def _portfolio_value(self):
        return self.cash + self.btc * self.current_price

    def _set_grid(self, price, force=False):
        if self.anchor is not None and not force:
            move = abs(price / self.anchor - 1.0) if self.anchor else 0
            if move < RESET_MOVE_PCT:
                return

        vol = self._volatility()
        adaptive = BASE_GRID_RANGE + vol * 12.0
        adaptive = max(MIN_GRID_RANGE, min(MAX_GRID_RANGE, adaptive))
        if self.recovery_mode:
            adaptive = min(MAX_GRID_RANGE, adaptive * 1.35)
        self.grid_range = adaptive
        self.anchor = float(price)

        # اصلاح‌شده: پله‌های خرید/فروش هرکدام جداگانه و داخل نصف دامنه (half)
        # ساخته می‌شوند تا هیچ‌وقت از محدوده‌ی مجاز (که reset روی آن حساب می‌شود) فراتر نروند.
        half = self.grid_range / 2.0
        buy_step = (self.anchor * half) / (GRID_LEVELS + 1)
        sell_step = (self.anchor * half) / (GRID_LEVELS + 1)
        self.buy_levels = [round(self.anchor - i * buy_step) for i in range(1, GRID_LEVELS + 1)]
        self.sell_levels = [round(self.anchor + i * sell_step) for i in range(1, GRID_LEVELS + 1)]
        # هر پله بعد از ساخت گرید جدید «آماده» است. بعد از هر معامله روی یک پله،
        # آن پله قفل می‌شود تا قیمت دوباره از سمت مخالف عبور کند (re-arm) —
        # وگرنه در بازار رنج، ربات مدام روی یک پله معامله می‌کند و فقط کارمزد می‌سوزاند.
        self.buy_armed = {lvl: True for lvl in self.buy_levels}
        self.sell_armed = {lvl: True for lvl in self.sell_levels}
        self.add_log(f"🧭 گرید جدید | anchor={self.anchor:,.0f} | دامنه={self.grid_range*100:.2f}%")

    def _can_trade(self, size, price):
        if self.paused or self.emergency_stop:
            return False
        if time.time() - self.last_trade_time < COOLDOWN_SECONDS:
            return False
        value = self._portfolio_value()
        if value <= 0:
            return False
        position_after = self.btc + size
        if position_after > MAX_BTC:
            return False
        if position_after * price / value > MAX_POSITION_PCT:
            return False
        return self.cash >= size * price * (1 + PAPER_FEE_RATE)

    def _buy(self, level):
        size = min(ORDER_SIZE_BTC, MAX_BTC - self.btc)
        if size <= 0 or not self._can_trade(size, level):
            return False
        cost = size * level
        fee = cost * PAPER_FEE_RATE
        self.cash -= cost + fee
        self.btc += size
        self.trades += 1
        self.last_trade_time = time.time()
        self.lots.append((level, size))
        self.trade_history.append({
            "type": "BUY", "price": level, "size": size,
            "profit": 0, "time": datetime.now().strftime("%H:%M:%S"), "icon": "🔄"
        })
        self.add_log(f"🔴 خرید | {level:,.0f} | {size:.4f} BTC")
        return True

    def _sell(self, level, emergency=False):
        size = min(ORDER_SIZE_BTC, self.btc)
        if size <= 0:
            return False

        # محافظ ضدِ قفل‌شدن روی ضرر: یک فروشِ عادی (غیراضطراری) هرگز نباید زیر
        # قیمت خریدِ همان لات انجام شود — حتی اگر anchor/گرید ریست شده باشد.
        # این دقیقاً همان سناریویی است که بعد از یک جهش قیمت (مثلاً بعد از قطعی
        # اتصال طولانی) لات‌های گران‌تر را با ضرر می‌فروخت.
        if not emergency and self.lots:
            buy_price = self.lots[0][0]
            min_acceptable = buy_price * (1 + 2 * PAPER_FEE_RATE)  # کارمزد خرید+فروش را هم پوشش بده
            if level < min_acceptable:
                return False

        gross = size * level
        fee = gross * PAPER_FEE_RATE
        if self.lots:
            buy_price, lot_size = self.lots[0]
            used = min(size, lot_size)
            profit = used * (level - buy_price) - fee
            lot_size -= used
            if lot_size <= 1e-12:
                self.lots.popleft()
            else:
                self.lots[0] = (buy_price, lot_size)
        else:
            profit = -fee

        self.cash += gross - fee
        self.btc -= size
        self.trades += 1
        self.realized_profit += profit
        self.total_profit += profit
        self.last_trade_time = time.time()
        icon = "⚠️" if emergency else ("✅" if profit > 0 else "❌" if profit < 0 else "➖")
        if profit > 0:
            self.win_count += 1
        elif profit < 0:
            self.loss_count += 1
        self.trade_history.append({
            "type": "SELL", "price": level, "size": size,
            "profit": profit, "time": datetime.now().strftime("%H:%M:%S"), "icon": icon
        })
        self.add_log(f"🟢 فروش | {level:,.0f} | سود={profit:+,.0f} | {icon}")
        alert_sound("profit" if profit > 0 else "loss")
        return True

    def _check_risk(self, price):
        value = self._portfolio_value()
        self.peak_value = max(self.peak_value, value)
        dd = (self.peak_value - value) / self.peak_value if self.peak_value else 0
        self.max_drawdown = max(self.max_drawdown, dd)

        if dd >= MAX_DRAWDOWN_PCT and not self.paused:
            self.paused = True
            self.add_log(f"🛑 توقف حفاظتی: افت سرمایه {dd*100:.1f}%")
            alert_sound("stop")

        self.recovery_mode = dd >= RECOVERY_DRAWDOWN_PCT

        if self.anchor and price <= self.anchor * (1 - STOP_LOSS_PCT) and self.btc > 0:
            sold = 0
            while self.btc > 0 and sold < 3:
                if self._sell(price, emergency=True):
                    sold += 1
                else:
                    break
            self.add_log("⚠️ خروج اضطراری مرحله‌ای برای کنترل سقوط")

        if self.anchor and price >= self.anchor * (1 + TAKE_PROFIT_PCT) and self.btc > 0:
            self._sell(price, emergency=False)

    def update(self, price):
        if not price or price <= 0:
            return
        self.current_price = float(price)
        now = time.time()
        gap_seconds = (now - self.last_price_time) if self.last_price_time else 0
        self.last_price_time = now
        self.last_update = datetime.now()
        self.prices.append(self.current_price)
        if self.anchor is None:
            self.anchor = self.current_price
            self._set_grid(self.current_price, force=True)
            self.add_log(f"✅ قیمت اولیه: {self.current_price:,.0f}")
            return

        # بعد از یک قطعی طولانی (مثلاً بیش از ۲ دقیقه بدون قیمت)، اولین قیمتی که
        # می‌رسد ممکن است یک جهش مصنوعی باشد نه یک حرکت واقعی بازار. به‌جای اینکه
        # گرید را روی این جهش ریست و بلافاصله معامله کنیم، فقط anchor/گرید را
        # همگام‌سازی می‌کنیم و این تیک را از منطق معامله رد می‌کنیم.
        STALE_GAP_SECONDS = 120
        if gap_seconds > STALE_GAP_SECONDS:
            self.add_log(f"⏱ قطعی {gap_seconds:.0f} ثانیه‌ای شناسایی شد؛ فقط sync (بدون معامله)")
            self._set_grid(self.current_price, force=True)
            return

        self._check_risk(self.current_price)

        if self.anchor:
            outside = (
                self.current_price < self.anchor * (1 - self.grid_range * 0.65) or
                self.current_price > self.anchor * (1 + self.grid_range * 0.65)
            )
            if outside and not self.emergency_stop:
                self._set_grid(self.current_price, force=True)

        # re-arm: هر پله‌ی خریدی که قیمت از بالایش رد شده دوباره آماده می‌شود،
        # و هر پله‌ی فروشی که قیمت از پایینش رد شده دوباره آماده می‌شود.
        for bp in self.buy_levels:
            if self.current_price > bp:
                self.buy_armed[bp] = True
        for sp in self.sell_levels:
            if self.current_price < sp:
                self.sell_armed[sp] = True

        if self.paused or self.emergency_stop:
            return

        for bp in sorted(self.buy_levels, reverse=True):
            if self.current_price <= bp and self.buy_armed.get(bp, True):
                if self._buy(bp):
                    self.buy_armed[bp] = False
                break

        for sp in sorted(self.sell_levels):
            if self.current_price >= sp and self.btc > 0 and self.sell_armed.get(sp, True):
                if self._sell(sp):
                    self.sell_armed[sp] = False
                break

    def get_status(self):
        total_value = self._portfolio_value()
        profit = total_value - self.initial_cash
        pct = (profit / self.initial_cash * 100) if self.initial_cash else 0
        return {
            "price": self.current_price,
            "cash": self.cash,
            "btc": self.btc,
            "total_value": total_value,
            "profit": profit,
            "profit_percent": pct,
            "trades": self.trades,
            "buy_levels": self.buy_levels[:GRID_LEVELS],
            "sell_levels": self.sell_levels[:GRID_LEVELS],
            "total_profit": self.total_profit,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "max_drawdown": self.max_drawdown * 100,
            "grid_range": self.grid_range * 100,
            "anchor": self.anchor or 0,
            "paused": self.paused,
            "recovery_mode": self.recovery_mode,
            "last_update": self.last_update.strftime("%H:%M:%S"),
            "trade_history": list(self.trade_history)[-10:],
            "log_messages": list(self.log_messages)[-10:],
        }


class GridBotGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🤖 BITPIN ADAPTIVE GRID BOT | PAPER")
        self.root.geometry("1050x850")
        self.root.configure(bg="#0a0a0f")
        self.root.resizable(False, False)
        self.running = False
        self.client = None
        self.simulator = None
        self.update_thread = None
        self.api_key, self.secret_key = load_credentials()
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
        tk.Label(self.root, text="🤖 BITPIN ADAPTIVE GRID | PAPER TRADING | HIGH RISK",
                 font=self.header_font, fg=self.header_color, bg=self.bg_color).pack(pady=8)

        main = tk.Frame(self.root, bg=self.bg_color)
        main.pack(fill=tk.BOTH, expand=True, padx=10)

        left = tk.Frame(main, bg=self.panel_bg, relief=tk.RIDGE, bd=2)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        right = tk.Frame(main, bg=self.panel_bg, relief=tk.RIDGE, bd=2)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))

        tk.Label(left, text="📊 وضعیت", font=self.digital_font, fg=self.header_color, bg=self.panel_bg).pack(pady=5)
        self.status_frame = tk.Frame(left, bg=self.panel_bg)
        self.status_frame.pack(fill=tk.BOTH, expand=True, padx=10)
        self.status_labels = {}
        items = [
            ("💰 قیمت", "price"), ("💵 نقد", "cash"), ("₿ BTC", "btc"),
            ("📊 ارزش کل", "total_value"), ("📈 سود/ضرر", "profit"),
            ("📊 سود/ضرر %", "profit_percent"), ("📉 بیشترین افت", "max_drawdown"),
            ("🧭 Anchor", "anchor"), ("📐 دامنه گرید", "grid_range"),
            ("🔄 معاملات", "trades"), ("⏸ وضعیت", "mode")
        ]
        for label, key in items:
            row = tk.Frame(self.status_frame, bg=self.panel_bg)
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text=label + ":", width=18, anchor="w", font=self.small_font,
                     fg="#8888cc", bg=self.panel_bg).pack(side=tk.LEFT)
            val = tk.Label(row, text="0", width=22, anchor="e", font=self.digital_font,
                           fg=self.fg_color, bg=self.panel_bg)
            val.pack(side=tk.RIGHT)
            self.status_labels[key] = val

        tk.Label(right, text="📈 گرید و معاملات", font=self.digital_font, fg=self.header_color, bg=self.panel_bg).pack(pady=5)
        self.trade_labels = {}
        for label, key in [("🔴 خرید", "buy"), ("🟢 فروش", "sell"), ("💰 سود تحقق‌یافته", "realized"), ("✅ برد", "wins"), ("❌ باخت", "losses")]:
            row = tk.Frame(right, bg=self.panel_bg)
            row.pack(fill=tk.X, padx=10, pady=2)
            tk.Label(row, text=label + ":", width=18, anchor="w", font=self.small_font,
                     fg="#8888cc", bg=self.panel_bg).pack(side=tk.LEFT)
            val = tk.Label(row, text="---", width=28, anchor="e", font=self.small_font,
                           fg=self.fg_color, bg=self.panel_bg, wraplength=330)
            val.pack(side=tk.RIGHT)
            self.trade_labels[key] = val

        tk.Label(right, text="📋 آخرین معاملات", font=self.small_font, fg=self.header_color, bg=self.panel_bg).pack(pady=(10, 2))
        self.history_listbox = tk.Listbox(right, bg="#0a0a0f", fg="#00ff88", font=self.small_font,
                                          height=8, relief=tk.FLAT, bd=0)
        self.history_listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        log_frame = tk.Frame(self.root, bg=self.panel_bg, relief=tk.RIDGE, bd=2)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        tk.Label(log_frame, text="📝 لاگ ربات", font=self.small_font, fg=self.header_color, bg=self.panel_bg).pack(pady=3)
        self.log_listbox = tk.Listbox(log_frame, bg="#0a0a0f", fg="#ffaa00", font=self.small_font,
                                      height=7, relief=tk.FLAT, bd=0)
        self.log_listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.status_label = tk.Label(self.root, text="🟡 در حال اتصال...", font=self.small_font,
                                     fg="#ffaa00", bg=self.bg_color)
        self.status_label.pack(pady=3)
        tk.Button(self.root, text="❌ خروج", command=self.on_closing, bg="#442222", fg="#ff6666",
                  font=self.small_font).pack(pady=4)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def update_display(self, status):
        self.status_labels["price"].config(text=f"{status['price']:,.0f}")
        self.status_labels["cash"].config(text=f"{status['cash']:,.0f}")
        self.status_labels["btc"].config(text=f"{status['btc']:.4f}")
        self.status_labels["total_value"].config(text=f"{status['total_value']:,.0f}")
        profit = status["profit"]
        pc = "#00ff88" if profit >= 0 else "#ff4444"
        self.status_labels["profit"].config(text=f"{profit:+,.0f}", fg=pc)
        self.status_labels["profit_percent"].config(text=f"{status['profit_percent']:+.2f}%", fg=pc)
        self.status_labels["max_drawdown"].config(text=f"{status['max_drawdown']:.2f}%", fg="#ffaa00")
        self.status_labels["anchor"].config(text=f"{status['anchor']:,.0f}")
        self.status_labels["grid_range"].config(text=f"{status['grid_range']:.2f}%")
        self.status_labels["trades"].config(text=str(status["trades"]))
        mode = "🛡 RECOVERY" if status["recovery_mode"] else "⏸ PAUSED" if status["paused"] else "🟢 ACTIVE"
        self.status_labels["mode"].config(text=mode)

        self.trade_labels["buy"].config(text=" | ".join(f"{x:,}" for x in status["buy_levels"]))
        self.trade_labels["sell"].config(text=" | ".join(f"{x:,}" for x in status["sell_levels"]))
        self.trade_labels["realized"].config(text=f"{status['total_profit']:+,.0f}")
        self.trade_labels["wins"].config(text=str(status["win_count"]))
        self.trade_labels["losses"].config(text=str(status["loss_count"]))

        self.history_listbox.delete(0, tk.END)
        for t in status["trade_history"]:
            if t["type"] == "BUY":
                text = f"🔄 BUY  {t['price']:,.0f} | {t['size']:.4f} | {t['time']}"
                color = "#00ccff"
            else:
                text = f"{t['icon']} SELL {t['price']:,.0f} | P/L {t['profit']:+,.0f} | {t['time']}"
                color = "#00ff88" if t["profit"] > 0 else "#ff4444"
            self.history_listbox.insert(tk.END, text)
            self.history_listbox.itemconfig(tk.END, fg=color)
        self.history_listbox.see(tk.END)

        self.log_listbox.delete(0, tk.END)
        for msg in status["log_messages"]:
            self.log_listbox.insert(tk.END, msg)
        self.log_listbox.see(tk.END)

        self.status_label.config(
            text=f"🟢 {status['last_update']} | معاملات={status['trades']} | افت حداکثر={status['max_drawdown']:.2f}%",
            fg="#00ff88" if not status["paused"] else "#ff4444"
        )

    def start_bot(self):
        if not self.api_key or not self.secret_key:
            messagebox.showerror("خطا", "کلیدهای API در فایل .env پیدا نشد!")
            return
        self.client = BitpinClient(self.api_key, self.secret_key)
        self.status_label.config(text="🟡 در حال اتصال به بیت‌پین...", fg="#ffaa00")
        if not self.client.login():
            messagebox.showerror("خطا", f"اتصال به بیت‌پین ناموفق!\n{self.client.last_error}")
            self.status_label.config(text="🔴 اتصال ناموفق", fg="#ff4444")
            return
        self.simulator = AdaptiveGridSimulator(INITIAL_CASH)
        price = self.client.get_price()
        if price:
            self.simulator.update(price)
        else:
            self.simulator.add_log(f"⚠️ دریافت قیمت اولیه ناموفق: {self.client.last_error}")
        self.running = True
        self.status_label.config(text="🟢 Paper Trading فعال شد", fg="#00ff88")
        self.update_thread = threading.Thread(target=self.update_loop, daemon=True)
        self.update_thread.start()

    def update_loop(self):
        consecutive_failures = 0
        while self.running:
            try:
                price = self.client.get_price()
                if price:
                    consecutive_failures = 0
                    self.simulator.update(price)
                else:
                    consecutive_failures += 1
                    self.simulator.add_log(f"⚠️ قیمت دریافت نشد ({consecutive_failures}): {self.client.last_error}")
                    if consecutive_failures % 5 == 0:
                        # هر ۵ شکست پیاپی یک بار دوباره لاگین کن، شاید توکن منقضی شده
                        self.client.login()
                status = self.simulator.get_status()
                self.root.after(0, self.update_display, status)
                time.sleep(POLL_SECONDS)
            except Exception as exc:
                self.simulator.add_log(f"⚠️ خطای حلقه: {exc}")
                time.sleep(5)

    def on_closing(self):
        self.running = False
        try:
            self.root.destroy()
        finally:
            sys.exit(0)


def main():
    root = tk.Tk()
    GridBotGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
🤖 BITPIN GRID BOT - PAPER TRADING
نسخه گرافیکی - خارج از Visual Studio
فقط خواندنی - هیچ معامله واقعی انجام نمی‌شود
"""

import os
import sys
import time
import json
import threading
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, font
from tkinter import messagebox

import requests
from dotenv import load_dotenv

# =============================================================
# 📥 بارگذاری کلیدها از .env
# =============================================================

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

# =============================================================
# 🔑 کلاس فقط خواندنی بیت‌پین
# =============================================================

class BitpinClient:
    def __init__(self, api_key, secret_key):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = "https://api.bitpin.ir"
        self.token = None
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "BitpinGridBot/1.0"
        })
        self.connected = False

    def login(self):
        url = f"{self.base_url}/api/v1/usr/authenticate/"
        payload = {"api_key": self.api_key, "secret_key": self.secret_key}

        try:
            response = self.session.post(url, json=payload, timeout=30)
            if response.status_code == 200:
                data = response.json()
                self.token = data.get("access")
                self.connected = True
                return True
            return False
        except:
            return False

    def get_price(self):
        if not self.token:
            return None

        url = f"{self.base_url}/api/v1/mkt/markets/BTC_IRT/"
        headers = {"Authorization": f"Bearer {self.token}"}

        try:
            response = self.session.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return int(data.get("price", 0))
            return None
        except:
            return None

# =============================================================
# 🎯 شبیه‌ساز ربات گرید
# =============================================================

class GridSimulator:
    def __init__(self, initial_cash=100_000_000, grid_count=10, grid_range=0.03):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.btc = 0.0
        self.grid_count = grid_count
        self.grid_range = grid_range
        self.trades = 0
        self.buy_levels = []
        self.sell_levels = []
        self.current_price = 0
        self.total_profit = 0
        self.buy_prices = []
        self.trade_history = []
        self.last_update = datetime.now()

    def update(self, price):
        if price is None or price == 0:
            return

        self.current_price = price
        self.last_update = datetime.now()
        self._calculate_grid(price)
        self._simulate_trade(price)

    def _calculate_grid(self, price):
        upper = price * (1 + self.grid_range / 2)
        lower = price * (1 - self.grid_range / 2)
        step = (upper - lower) / self.grid_count

        self.buy_levels = []
        self.sell_levels = []

        for i in range(1, self.grid_count // 2 + 1):
            buy_price = price - i * step
            sell_price = price + i * step

            if buy_price >= lower:
                self.buy_levels.append(round(buy_price))
            if sell_price <= upper:
                self.sell_levels.append(round(sell_price))

    def _simulate_trade(self, price):
        # خرید
        for bp in self.buy_levels:
            if price <= bp and self.cash > 0:
                size = 0.0001
                cost = size * bp
                if self.cash >= cost:
                    self.btc += size
                    self.cash -= cost
                    self.buy_prices.append(bp)
                    self.trades += 1
                    self.trade_history.append({
                        'type': 'BUY',
                        'price': bp,
                        'time': datetime.now().strftime('%H:%M:%S')
                    })
                break

        # فروش
        for sp in self.sell_levels:
            if price >= sp and self.btc > 0:
                size = min(0.0001, self.btc)
                if self.buy_prices:
                    buy_price = self.buy_prices.pop(0)
                    profit = size * (sp - buy_price)
                    self.total_profit += profit
                else:
                    profit = 0

                self.cash += size * sp
                self.btc -= size
                self.trades += 1
                self.trade_history.append({
                    'type': 'SELL',
                    'price': sp,
                    'profit': profit,
                    'time': datetime.now().strftime('%H:%M:%S')
                })
                break

    def get_status(self):
        total_value = self.cash + self.btc * self.current_price

        return {
            'price': self.current_price,
            'cash': self.cash,
            'btc': self.btc,
            'total_value': total_value,
            'profit': total_value - self.initial_cash,
            'profit_percent': ((total_value - self.initial_cash) / self.initial_cash) * 100 if self.initial_cash else 0,
            'trades': self.trades,
            'buy_levels': self.buy_levels[:5],
            'sell_levels': self.sell_levels[:5],
            'total_profit': self.total_profit,
            'last_update': self.last_update.strftime('%H:%M:%S'),
            'trade_history': self.trade_history[-5:] if self.trade_history else []
        }

# =============================================================
# 📊 رابط گرافیکی اصلی
# =============================================================

class GridBotGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🤖 BITPIN GRID BOT")
        self.root.geometry("900x650")
        self.root.configure(bg='#0a0a0f')
        self.root.resizable(False, False)

        # تنظیم آیکون و استایل
        self.setup_styles()

        # متغیرها
        self.client = None
        self.simulator = None
        self.running = False
        self.update_thread = None

        # بارگذاری کلیدها
        self.api_key, self.secret_key = load_credentials()

        # ساخت ویجت‌ها
        self.create_widgets()

        # شروع خودکار
        self.start_bot()

    def setup_styles(self):
        """تنظیمات استایل"""
        self.bg_color = '#0a0a0f'
        self.fg_color = '#00ff88'
        self.header_color = '#00ccff'
        self.panel_bg = '#111122'
        self.border_color = '#223366'

        # فونت‌های دیجیتالی
        try:
            self.digital_font = font.Font(family='Courier New', size=14, weight='bold')
            self.small_font = font.Font(family='Courier New', size=10)
            self.header_font = font.Font(family='Courier New', size=16, weight='bold')
        except:
            self.digital_font = font.Font(size=14, weight='bold')
            self.small_font = font.Font(size=10)
            self.header_font = font.Font(size=16, weight='bold')

    def create_widgets(self):
        """ساخت ویجت‌های رابط کاربری"""

        # --- هدر ---
        header_frame = tk.Frame(self.root, bg=self.bg_color)
        header_frame.pack(fill=tk.X, pady=5)

        header_label = tk.Label(
            header_frame,
            text="🤖 BITPIN GRID BOT  |  PAPER TRADING",
            font=self.header_font,
            fg=self.header_color,
            bg=self.bg_color
        )
        header_label.pack()

        # --- فریم اصلی ---
        main_frame = tk.Frame(self.root, bg=self.bg_color)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # ستون چپ (اطلاعات پرتفوی)
        left_frame = tk.Frame(main_frame, bg=self.panel_bg, relief=tk.RIDGE, bd=2)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        tk.Label(
            left_frame,
            text="📊 وضعیت پرتفوی",
            font=self.digital_font,
            fg=self.header_color,
            bg=self.panel_bg
        ).pack(pady=5)

        # جدول اطلاعات
        self.status_frame = tk.Frame(left_frame, bg=self.panel_bg)
        self.status_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.create_status_labels()

        # --- ستون راست (معاملات و پله‌ها) ---
        right_frame = tk.Frame(main_frame, bg=self.panel_bg, relief=tk.RIDGE, bd=2)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))

        tk.Label(
            right_frame,
            text="📈 معاملات و پله‌ها",
            font=self.digital_font,
            fg=self.header_color,
            bg=self.panel_bg
        ).pack(pady=5)

        # اطلاعات معاملاتی
        self.trade_frame = tk.Frame(right_frame, bg=self.panel_bg)
        self.trade_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.create_trade_labels()

        # --- فوتر ---
        footer_frame = tk.Frame(self.root, bg=self.bg_color)
        footer_frame.pack(fill=tk.X, pady=5)

        self.status_label = tk.Label(
            footer_frame,
            text="🟡 در حال اتصال...",
            font=self.small_font,
            fg='#ffaa00',
            bg=self.bg_color
        )
        self.status_label.pack()

        # دکمه خروج
        exit_btn = tk.Button(
            footer_frame,
            text="❌ خروج",
            command=self.on_closing,
            bg='#442222',
            fg='#ff6666',
            font=self.small_font,
            relief=tk.RAISED,
            bd=2
        )
        exit_btn.pack(pady=5)

        # بستن پنجره با X
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_status_labels(self):
        """ساخت لیبل‌های وضعیت پرتفوی"""
        # قالب: (برچسب, مقدار, کلید)
        self.status_items = [
            ("💰 قیمت لحظه‌ای", "0", 'price'),
            ("💵 موجودی نقد", "0", 'cash'),
            ("₿ بیت‌کوین", "0", 'btc'),
            ("📊 ارزش کل", "0", 'total_value'),
            ("📈 سود/ضرر", "0", 'profit'),
            ("📊 سود/ضرر %", "0%", 'profit_percent'),
        ]

        self.status_labels = {}

        for i, (label, default, key) in enumerate(self.status_items):
            row = tk.Frame(self.status_frame, bg=self.panel_bg)
            row.pack(fill=tk.X, pady=2)

            lbl = tk.Label(
                row,
                text=label + ":",
                font=self.small_font,
                fg='#8888cc',
                bg=self.panel_bg,
                width=18,
                anchor='w'
            )
            lbl.pack(side=tk.LEFT)

            val = tk.Label(
                row,
                text=default,
                font=self.digital_font,
                fg=self.fg_color,
                bg=self.panel_bg,
                width=20,
                anchor='e'
            )
            val.pack(side=tk.RIGHT)
            self.status_labels[key] = val

    def create_trade_labels(self):
        """ساخت لیبل‌های اطلاعات معاملاتی"""
        trade_items = [
            ("📋 تعداد معاملات", "0", 'trades'),
            ("💰 سود کل معاملات", "0", 'total_profit'),
            ("🔴 پله‌های خرید", "---", 'buy_levels'),
            ("🟢 پله‌های فروش", "---", 'sell_levels'),
        ]

        self.trade_labels = {}

        for i, (label, default, key) in enumerate(trade_items):
            row = tk.Frame(self.trade_frame, bg=self.panel_bg)
            row.pack(fill=tk.X, pady=2)

            lbl = tk.Label(
                row,
                text=label + ":",
                font=self.small_font,
                fg='#8888cc',
                bg=self.panel_bg,
                width=18,
                anchor='w'
            )
            lbl.pack(side=tk.LEFT)

            val = tk.Label(
                row,
                text=default,
                font=self.small_font,
                fg=self.fg_color,
                bg=self.panel_bg,
                width=20,
                anchor='e',
                wraplength=300
            )
            val.pack(side=tk.RIGHT)
            self.trade_labels[key] = val

    def update_display(self, status):
        """به‌روزرسانی نمایشگر"""
        # به‌روزرسانی وضعیت پرتفوی
        self.status_labels['price'].config(text=f"{status['price']:,}")
        self.status_labels['cash'].config(text=f"{status['cash']:,.0f}")
        self.status_labels['btc'].config(text=f"{status['btc']:.6f}")
        self.status_labels['total_value'].config(text=f"{status['total_value']:,.0f}")

        profit = status['profit']
        profit_color = '#00ff88' if profit >= 0 else '#ff4444'
        self.status_labels['profit'].config(text=f"{profit:+,.0f}", fg=profit_color)

        profit_pct = status['profit_percent']
        self.status_labels['profit_percent'].config(text=f"{profit_pct:+.2f}%", fg=profit_color)

        # به‌روزرسانی معاملات
        self.trade_labels['trades'].config(text=f"{status['trades']}")
        self.trade_labels['total_profit'].config(text=f"{status['total_profit']:,.0f}")

        buy_str = " | ".join([f"{p:,}" for p in status['buy_levels']]) or "---"
        sell_str = " | ".join([f"{p:,}" for p in status['sell_levels']]) or "---"

        self.trade_labels['buy_levels'].config(text=buy_str, fg='#ff6666')
        self.trade_labels['sell_levels'].config(text=sell_str, fg='#66ff66')

        # به‌روزرسانی وضعیت
        self.status_label.config(
            text=f"🟢 فعال | بروزرسانی: {status['last_update']} | معاملات: {status['trades']}",
            fg='#00ff88'
        )

    def start_bot(self):
        """شروع ربات"""
        if not self.api_key or not self.secret_key:
            messagebox.showerror("خطا", "کلیدهای API در فایل .env پیدا نشد!")
            return

        self.status_label.config(text="🟡 در حال اتصال به بیت‌پین...", fg='#ffaa00')

        # اتصال به بیت‌پین
        self.client = BitpinClient(self.api_key, self.secret_key)
        if not self.client.login():
            messagebox.showerror("خطا", "اتصال به بیت‌پین ناموفق!\nکلیدها را بررسی کن.")
            self.status_label.config(text="🔴 اتصال ناموفق", fg='#ff4444')
            return

        # راه‌اندازی شبیه‌ساز
        self.simulator = GridSimulator(initial_cash=100_000_000, grid_count=10, grid_range=0.03)

        # دریافت قیمت اولیه
        price = self.client.get_price()
        if price:
            self.simulator.update(price)

        self.running = True
        self.status_label.config(text="🟢 در حال اجرا...", fg='#00ff88')

        # شروع ترد آپدیت
        self.update_thread = threading.Thread(target=self.update_loop, daemon=True)
        self.update_thread.start()

    def update_loop(self):
        """حلقه آپدیت در ترد جداگانه"""
        while self.running:
            try:
                price = self.client.get_price()
                if price:
                    self.simulator.update(price)

                status = self.simulator.get_status()
                self.root.after(0, self.update_display, status)

                time.sleep(2)
            except Exception as e:
                time.sleep(5)

    def on_closing(self):
        """بستن برنامه"""
        self.running = False
        self.root.destroy()
        sys.exit(0)

# =============================================================
# 🚀 اجرا
# =============================================================

def main():
    root = tk.Tk()
    app = GridBotGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
# grid_bot_btc_optimize.py
import pandas as pd
import yfinance as yf
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

def get_data(symbol='BTC-USD', days=30):
    end = datetime.now()
    start = end - timedelta(days=days)
    df = yf.download(symbol, start=start, end=end, progress=False)
    close = df['Close'].values.astype(float).flatten()
    return close, df.index

def grid_strategy_with_stop_loss(close_prices, dates,
                                 grid_count=35,
                                 grid_range=0.03,
                                 order_size=0.005,
                                 leverage=25,
                                 stop_loss=0.05,
                                 trailing_stop=0.03,
                                 initial_cash=10000):
    
    close = close_prices
    cash = initial_cash
    btc = 0
    trades = 0
    wins = 0
    buy_prices = []
    equity = []
    total_profit = 0
    max_price = 0
    entry_price = 0
    
    current_price = close[0]
    
    def get_grid_levels(price):
        upper = price * (1 + grid_range / 2)
        lower = price * (1 - grid_range / 2)
        step = (upper - lower) / grid_count
        buy_levels = []
        sell_levels = []
        for i in range(1, grid_count // 2 + 1):
            b_price = round(price - i * step, 2)
            s_price = round(price + i * step, 2)
            if b_price >= lower:
                buy_levels.append(b_price)
            if s_price <= upper:
                sell_levels.append(s_price)
        return buy_levels, sell_levels
    
    buy_levels, sell_levels = get_grid_levels(current_price)
    buy_idx = 0
    sell_idx = 0
    
    for i in range(1, len(close)):
        price = close[i]
        
        # حد ضرر ثابت
        if btc > 0 and entry_price > 0:
            stop_loss_price = entry_price * (1 - stop_loss)
            if price < stop_loss_price:
                sell_size = btc
                profit = sell_size * (price - entry_price) * leverage
                cash += sell_size * price
                total_profit += profit
                if profit > 0:
                    wins += 1
                btc = 0
                buy_prices.clear()
                trades += 1
                buy_levels, sell_levels = get_grid_levels(price)
                buy_idx = 0
                sell_idx = 0
                entry_price = 0
                continue
        
        # حد ضرر متحرک
        if btc > 0 and price > max_price:
            max_price = price
            trailing_stop_price = max_price * (1 - trailing_stop)
            if price < trailing_stop_price:
                sell_size = btc
                profit = sell_size * (price - entry_price) * leverage
                cash += sell_size * price
                total_profit += profit
                if profit > 0:
                    wins += 1
                btc = 0
                buy_prices.clear()
                trades += 1
                buy_levels, sell_levels = get_grid_levels(price)
                buy_idx = 0
                sell_idx = 0
                entry_price = 0
                max_price = 0
                continue
        
        # سیگنال خرید
        if buy_idx < len(buy_levels) and price <= buy_levels[buy_idx]:
            size = order_size
            if cash >= size * price:
                btc += size * leverage
                cash -= size * price
                buy_prices.append(price)
                entry_price = price
                max_price = price
                buy_idx += 1
                trades += 1
                continue
        
        # سیگنال فروش
        if sell_idx < len(sell_levels) and price >= sell_levels[sell_idx] and btc > 0:
            sell_size = min(btc, order_size * leverage)
            profit = sell_size * (price - (buy_prices[0] if buy_prices else price))
            cash += sell_size * price
            total_profit += profit
            if profit > 0:
                wins += 1
            btc -= sell_size
            if buy_prices:
                buy_prices.pop(0)
            sell_idx += 1
            trades += 1
            entry_price = 0
            max_price = 0
            continue
        
        equity.append(cash + btc * price)
    
    final_value = cash + btc * close[-1]
    total_return = (final_value - initial_cash) / initial_cash * 100
    
    return {
        'final_value': final_value,
        'total_return': total_return,
        'net_profit': final_value - initial_cash,
        'trades': trades,
        'win_rate': (wins / trades * 100) if trades > 0 else 0,
        'total_profit': total_profit,
        'avg_profit': total_profit / trades if trades > 0 else 0,
    }

def test_btc_optimized():
    print("=" * 70)
    print("🚀 بهینه‌سازی برای بیت‌کوین (۳۰ روز)")
    print("=" * 70)
    
    close, dates = get_data('BTC-USD', days=30)
    print(f"✅ {len(close)} روز داده دریافت شد.")
    
    # تست ترکیب‌های مختلف
    configs = [
        # (پله‌ها, محدوده, حجم, اهرم, حدضرر, حدضرر متحرک)
        (35, 0.03, 0.005, 25, 0.05, 0.03),
        (30, 0.04, 0.006, 20, 0.05, 0.03),
        (40, 0.03, 0.004, 30, 0.05, 0.03),
        (35, 0.03, 0.005, 20, 0.04, 0.02),
        (40, 0.02, 0.004, 30, 0.06, 0.03),
        (30, 0.05, 0.006, 25, 0.05, 0.02),
        (50, 0.02, 0.003, 35, 0.06, 0.03),
        (45, 0.03, 0.004, 30, 0.05, 0.02),
    ]
    
    results = []
    best_return = -100
    best_params = None
    
    for gc, gr, os, lev, sl, ts in configs:
        try:
            r = grid_strategy_with_stop_loss(
                close, dates,
                grid_count=gc,
                grid_range=gr,
                order_size=os,
                leverage=lev,
                stop_loss=sl,
                trailing_stop=ts,
                initial_cash=10000
            )
            annual = ((1 + r['total_return']/100) ** (365/30) - 1) * 100
            
            results.append({
                'params': (gc, gr, os, lev, sl, ts),
                'return': r['total_return'],
                'annual': annual,
                'trades': r['trades'],
                'win_rate': r['win_rate'],
                'profit': r['net_profit']
            })
            
            status = "✅" if r['total_return'] > 0 else "❌"
            print(f"{status} پله‌ها={gc} | محدوده={gr} | حجم={os} | اهرم={lev} | SL={sl*100:.0f}% | TS={ts*100:.0f}%")
            print(f"   سود: {r['total_return']:.2f}% | سالانه: {annual:.0f}% | معاملات: {r['trades']}")
            print("-" * 70)
            
            if r['total_return'] > best_return:
                best_return = r['total_return']
                best_params = {
                    'grid_count': gc,
                    'grid_range': gr,
                    'order_size': os,
                    'leverage': lev,
                    'stop_loss': sl,
                    'trailing_stop': ts
                }
        except Exception as e:
            print(f"❌ خطا: {str(e)[:40]}")
    
    # بهترین نتیجه
    print("\n" + "=" * 70)
    print("🏆 بهترین نتیجه برای بیت‌کوین:")
    if best_params:
        print(f"   پله‌ها: {best_params['grid_count']}")
        print(f"   محدوده: {best_params['grid_range']}")
        print(f"   حجم: {best_params['order_size']}")
        print(f"   اهرم: {best_params['leverage']}")
        print(f"   حد ضرر: {best_params['stop_loss']*100:.0f}%")
        print(f"   حد ضرر متحرک: {best_params['trailing_stop']*100:.0f}%")
        print(f"📈 سود ۳۰ روز: {best_return:.2f}%")
        annual_best = ((1 + best_return/100) ** (365/30) - 1) * 100
        print(f"📈 سود سالانه: {annual_best:.0f}%")
    print("=" * 70)
    
    return best_params, best_return

if __name__ == "__main__":
    test_btc_optimized()
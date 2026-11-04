import requests
import yfinance as yf
from datetime import datetime


class MarketIntel:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        self._cache = {}
        self._cache_ttl = 300

    def _get_cache(self, key):
        if key in self._cache:
            data, timestamp = self._cache[key]
            if (datetime.now() - timestamp).total_seconds() < self._cache_ttl:
                return data
        return None

    def _set_cache(self, key, value):
        self._cache[key] = (value, datetime.now())

    def get_news(self, limit=5):
        """دریافت اخبار از 8tia.com"""
        cache_key = "news_" + str(limit)
        cached = self._get_cache(cache_key)
        if cached:
            return cached

        result = []

        # روش ۱: 8tia.com
        try:
            url = "https://8tia.com/api/news?limit=" + str(limit)
            response = self.session.get(url, timeout=15)
            if response.status_code == 200:
                data = response.json()
                articles = data.get('articles', [])
                for a in articles:
                    result.append({
                        'title': a.get('title', ''),
                        'source': a.get('source', ''),
                        'url': a.get('url', '')
                    })
                if result:
                    self._set_cache(cache_key, result)
                    return result
        except Exception as e:
            print("8tia error: " + str(e))

        # روش ۲: cryptocurrency.cv (پشتیبان)
        try:
            url = "https://cryptocurrency.cv/api/news?limit=" + str(limit)
            response = self.session.get(url, timeout=15)
            if response.status_code == 200:
                data = response.json()
                articles = data.get('articles', [])
                for a in articles:
                    result.append({
                        'title': a.get('title', ''),
                        'source': a.get('source', ''),
                        'url': a.get('link', '')
                    })
                if result:
                    self._set_cache(cache_key, result)
                    return result
        except Exception as e:
            print("cv error: " + str(e))

        return result

    def get_fear_greed(self):
        cache_key = "fear_greed"
        cached = self._get_cache(cache_key)
        if cached:
            return cached
        try:
            url = "https://pro-api.coinmarketcap.com/trial-pro-api/v3/fear-and-greed/latest"
            response = self.session.get(url, timeout=15)
            if response.status_code == 200:
                data = response.json()
                fg_data = data.get('data', {})
                result = {
                    'value': int(fg_data.get('value', 50)),
                    'classification': fg_data.get('value_classification', 'Neutral'),
                    'timestamp': fg_data.get('update_time', '')
                }
                self._set_cache(cache_key, result)
                return result
            return None
        except Exception as e:
            print("fg error: " + str(e))
            return None

    def get_technical_analysis(self, symbol="BTC-USD"):
        cache_key = "tech_" + symbol
        cached = self._get_cache(cache_key)
        if cached:
            return cached
        try:
            data = yf.download(symbol, period="3mo", interval="1d",
                               progress=False, auto_adjust=True)
            if data.empty:
                return None
            close = data['Close'].squeeze()
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            sma_20 = close.rolling(window=20).mean()
            sma_50 = close.rolling(window=50).mean()
            latest_price = float(close.iloc[-1])
            latest_rsi = float(rsi.iloc[-1])
            latest_sma20 = float(sma_20.iloc[-1])
            latest_sma50 = float(sma_50.iloc[-1])
            if latest_sma20 > latest_sma50 and latest_rsi < 70:
                trend = "sooudi"
            elif latest_sma20 < latest_sma50 and latest_rsi > 30:
                trend = "nouzouli"
            else:
                trend = "khensi"
            result = {
                'price': latest_price,
                'rsi': latest_rsi,
                'sma_20': latest_sma20,
                'sma_50': latest_sma50,
                'trend': trend,
            }
            self._set_cache(cache_key, result)
            return result
        except Exception as e:
            print("tech error: " + str(e))
            return None

    def get_market_signal(self):
        signals = []
        details = []
        fg = self.get_fear_greed()
        if fg:
            if fg['value'] <= 25:
                signals.append('buy')
                details.append("tars shadid -> kharid")
            elif fg['value'] >= 75:
                signals.append('sell')
                details.append("tama shadid -> foroush")
            else:
                signals.append('hold')
                details.append("ehsasat khensi")
        tech = self.get_technical_analysis()
        if tech:
            if tech['trend'] == 'sooudi' and tech['rsi'] < 70:
                signals.append('buy')
                details.append("ravand sooudi")
            elif tech['trend'] == 'nouzouli' and tech['rsi'] > 30:
                signals.append('sell')
                details.append("ravand nouzouli")
            else:
                signals.append('hold')
                details.append("ravand khensi")
        if not signals:
            return 'hold', ['dade ee nist']
        buy_count = signals.count('buy')
        sell_count = signals.count('sell')
        if buy_count > sell_count:
            final = 'buy'
        elif sell_count > buy_count:
            final = 'sell'
        else:
            final = 'hold'
        return final, details


if __name__ == "__main__":
    print("=" * 60)
    print("Test Market Intelligence")
    print("=" * 60)
    intel = MarketIntel()
    print("")
    print("Akhbar:")
    news = intel.get_news(limit=3)
    if news:
        for n in news:
            print("  - " + n['title'])
    else:
        print("  (khali)")
    print("")
    print("Tars va Tama:")
    fg = intel.get_fear_greed()
    if fg:
        print("  Meghdar: " + str(fg['value']) + " | " + fg['classification'])
    print("")
    print("Tahlil:")
    tech = intel.get_technical_analysis()
    if tech:
        print("  Gheymat: " + str(round(tech['price'], 2)))
        print("  RSI: " + str(round(tech['rsi'], 2)))
        print("  Ravand: " + tech['trend'])
    print("")
    print("Signal:")
    signal, details = intel.get_market_signal()
    print("  " + signal.upper())
    for d in details:
        print("  " + d)
    print("")
    print("=" * 60)
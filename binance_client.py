import time
import hmac
import hashlib
import requests
import json
from config import BINANCE_API_KEY, BINANCE_API_SECRET, BINANCE_REST_URL, BINANCE_DATA_URL, DRY_RUN

class BinanceClient:
    def __init__(self):
        self.api_key = BINANCE_API_KEY
        self.api_secret = BINANCE_API_SECRET
        self.dry_run = DRY_RUN or (not self.api_key or not self.api_secret)
        self.simulated_balance = 10000.0 # Virtual balance for dry run
        
    def _sign(self, params):
        query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return query_string + f"&signature={signature}"
        
    def get_ticker_price(self, pair):
        headers = {'User-Agent': 'Mozilla/5.0'}
        urls = [
            f"{BINANCE_DATA_URL}/api/v3/ticker/price?symbol={pair}",
            f"{BINANCE_REST_URL}/api/v3/ticker/price?symbol={pair}"
        ]
        for url in urls:
            try:
                r = requests.get(url, headers=headers, timeout=5)
                if r.status_code == 200:
                    return float(r.json()['price'])
            except Exception:
                continue
        return None

    def get_usdt_balance(self):
        if self.dry_run:
            return self.simulated_balance
            
        try:
            timestamp = int(time.time() * 1000)
            params = {'timestamp': timestamp}
            signed_query = self._sign(params)
            headers = {'X-MBX-APIKEY': self.api_key}
            url = f"{BINANCE_REST_URL}/api/v3/account?{signed_query}"
            
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                for b in data.get('balances', []):
                    if b['asset'] == 'USDT':
                        return float(b['free'])
        except Exception as e:
            print(f"Error fetching Binance balance: {e}")
        return 0.0

    def place_market_buy(self, pair, quote_amount_usdt):
        """Buys 'quote_amount_usdt' worth of crypto on Spot"""
        cur_price = self.get_ticker_price(pair)
        if not cur_price:
            return None, "فشل جلب السعر اللحظي من باينانس"
            
        if self.dry_run:
            qty = round(quote_amount_usdt / cur_price, 6)
            self.simulated_balance -= quote_amount_usdt
            return {
                'orderId': f"SIM_{int(time.time())}",
                'executedQty': qty,
                'cummulativeQuoteQty': quote_amount_usdt,
                'price': cur_price,
                'is_simulation': True
            }, "تم تنفيذ أمر شراء تجريبي (Paper Trade)"
            
        try:
            timestamp = int(time.time() * 1000)
            params = {
                'symbol': pair,
                'side': 'BUY',
                'type': 'MARKET',
                'quoteOrderQty': round(quote_amount_usdt, 2),
                'timestamp': timestamp
            }
            signed_query = self._sign(params)
            headers = {'X-MBX-APIKEY': self.api_key}
            url = f"{BINANCE_REST_URL}/api/v3/order?{signed_query}"
            
            r = requests.post(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                return data, "تم تنفيذ أمر الشراء بنجاح على باينانس"
            else:
                return None, f"خطأ من باينانس: {r.text}"
        except Exception as e:
            return None, f"خطأ اتصال: {e}"

    def place_market_sell(self, pair, quantity):
        """Sells 'quantity' on Spot"""
        cur_price = self.get_ticker_price(pair)
        if not cur_price:
            return None, "فشل جلب السعر اللحظي"
            
        if self.dry_run:
            usd_returned = quantity * cur_price
            self.simulated_balance += usd_returned
            return {
                'orderId': f"SIM_SELL_{int(time.time())}",
                'executedQty': quantity,
                'price': cur_price,
                'is_simulation': True
            }, "تم تنفيذ أمر بيع تجريبي"
            
        try:
            timestamp = int(time.time() * 1000)
            params = {
                'symbol': pair,
                'side': 'SELL',
                'type': 'MARKET',
                'quantity': quantity,
                'timestamp': timestamp
            }
            signed_query = self._sign(params)
            headers = {'X-MBX-APIKEY': self.api_key}
            url = f"{BINANCE_REST_URL}/api/v3/order?{signed_query}"
            
            r = requests.post(url, headers=headers, timeout=10)
            if r.status_code == 200:
                return r.json(), "تم تنفيذ البيع بنجاح"
            else:
                return None, f"خطأ باينانس: {r.text}"
        except Exception as e:
            return None, f"خطأ: {e}"

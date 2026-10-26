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
        self.simulated_balance = 10000.0
        
    def _sign(self, params):
        query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return query_string + f"&signature={signature}"

    def get_symbol_filters(self, pair):
        """Fetches lot size and price filters for exact precision on Binance"""
        try:
            r = requests.get(f"{BINANCE_DATA_URL}/api/v3/exchangeInfo?symbol={pair}", timeout=5)
            if r.status_code == 200:
                data = r.json()
                symbols = data.get('symbols', [])
                if symbols:
                    s = symbols[0]
                    step_size = 1.0
                    tick_size = 0.01
                    min_qty = 0.0
                    for f in s.get('filters', []):
                        if f['filterType'] == 'LOT_SIZE':
                            step_size = float(f['stepSize'])
                            min_qty = float(f['minQty'])
                        elif f['filterType'] == 'PRICE_FILTER':
                            tick_size = float(f['tickSize'])
                    return {'step_size': step_size, 'tick_size': tick_size, 'min_qty': min_qty}
        except Exception:
            pass
        return {'step_size': 0.0001, 'tick_size': 0.0001, 'min_qty': 0.0}

    def round_step(self, value, step_size):
        """Rounds a number to the nearest step size"""
        precision = 0
        if '.' in str(step_size):
            precision = len(str(step_size).rstrip('0').split('.')[1])
        return round(value - (value % step_size), precision)

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

    def check_connection(self):
        if self.dry_run:
            return {
                'connected': True,
                'is_dry_run': True,
                'message': "🧪 <b>الوضع التجريبي (Dry Run) مُفعّل</b>\nالبوت متصل بالأسعار الحية لباينانس ولكنه يتداول بأموال افتراضية لحماية رأس مالك."
            }
            
        if not self.api_key or not self.api_secret:
            return {
                'connected': False,
                'is_dry_run': False,
                'message': "❌ <b>لم يتم إدخال مفاتيح باينانس (API Key & Secret)!</b>"
            }
            
        try:
            timestamp = int(time.time() * 1000)
            params = {'timestamp': timestamp}
            signed_query = self._sign(params)
            headers = {'X-MBX-APIKEY': self.api_key}
            url = f"{BINANCE_REST_URL}/api/v3/account?{signed_query}"
            
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                usdt_free = 0.0
                for b in data.get('balances', []):
                    if b['asset'] == 'USDT':
                        usdt_free = float(b['free'])
                        break
                can_trade = data.get('canTrade', False)
                trade_status = "مُفعّل وجاهز للتداول الفوري ✅" if can_trade else "غير مُفعّل (تحقق من الصلاحيات) ⚠️"
                
                return {
                    'connected': True,
                    'is_dry_run': False,
                    'usdt_balance': usdt_free,
                    'can_trade': can_trade,
                    'message': (
                        f"✅ <b>الاتصال بحساب باينانس الحقيقي ناجح 100%!</b>\n"
                        f"────────────────────\n"
                        f"• <b>حالة التداول:</b> {trade_status}\n"
                        f"• <b>رصيدك المتاح في Spot:</b> <code>{usdt_free:,.2f} USDT</code>\n"
                        f"• <b>المفاتيح:</b> صحيحة ومتطابقة مع حسابك."
                    )
                }
            else:
                err_msg = r.json().get('msg', r.text)
                return {
                    'connected': False,
                    'is_dry_run': False,
                    'message': f"❌ <b>فشل الاتصال بباينانس:</b>\n<code>{err_msg}</code>"
                }
        except Exception as e:
            return {
                'connected': False,
                'is_dry_run': False,
                'message': f"❌ <b>خطأ في الاتصال:</b> {e}"
            }

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

    def place_native_oco_order(self, pair, quantity, tp_price, sl_price):
        """
        Places a Native OCO Order directly on Binance exchange servers!
        Binance itself holds and executes the Take Profit (+10%) and Stop Loss (-6%)
        even if laptop, GitHub, and internet are 100% offline!
        """
        filters = self.get_symbol_filters(pair)
        step_size = filters['step_size']
        tick_size = filters['tick_size']
        
        qty_formatted = self.round_step(quantity, step_size)
        tp_formatted = self.round_step(tp_price, tick_size)
        sl_formatted = self.round_step(sl_price, tick_size)
        sl_limit_formatted = self.round_step(sl_price * 0.998, tick_size) # Limit slightly lower to guarantee execution
        
        if self.dry_run:
            return {
                'orderListId': f"SIM_OCO_{int(time.time())}",
                'is_simulation': True,
                'tp_price': tp_formatted,
                'sl_price': sl_formatted,
                'quantity': qty_formatted
            }, "تم تسجيل أمر OCO المزدوج تجريبياً"

        try:
            timestamp = int(time.time() * 1000)
            params = {
                'symbol': pair,
                'side': 'SELL',
                'quantity': f"{qty_formatted:f}".rstrip('0').rstrip('.'),
                'price': f"{tp_formatted:f}".rstrip('0').rstrip('.'),             # Target 1 (+10%)
                'stopPrice': f"{sl_formatted:f}".rstrip('0').rstrip('.'),         # Stop Trigger (-6%)
                'stopLimitPrice': f"{sl_limit_formatted:f}".rstrip('0').rstrip('.'),
                'stopLimitTimeInForce': 'GTC',
                'timestamp': timestamp
            }
            signed_query = self._sign(params)
            headers = {'X-MBX-APIKEY': self.api_key}
            url = f"{BINANCE_REST_URL}/api/v3/order/oco?{signed_query}"
            
            r = requests.post(url, headers=headers, timeout=10)
            if r.status_code == 200:
                return r.json(), "تم وضع أمر OCO المزدوج (هدف + وقف) على سيرفرات باينانس مباشرة ✅"
            else:
                return None, f"خطأ في وضع أمر OCO: {r.text}"
        except Exception as e:
            return None, f"خطأ اتصال OCO: {e}"

    def place_market_sell(self, pair, quantity):
        cur_price = self.get_ticker_price(pair)
        if not cur_price:
            return None, "فشل جلب السعر اللحظي"
            
        filters = self.get_symbol_filters(pair)
        qty_formatted = self.round_step(quantity, filters['step_size'])
        
        if self.dry_run:
            usd_returned = qty_formatted * cur_price
            self.simulated_balance += usd_returned
            return {
                'orderId': f"SIM_SELL_{int(time.time())}",
                'executedQty': qty_formatted,
                'price': cur_price,
                'is_simulation': True
            }, "تم تنفيذ أمر بيع تجريبي"
            
        try:
            timestamp = int(time.time() * 1000)
            params = {
                'symbol': pair,
                'side': 'SELL',
                'type': 'MARKET',
                'quantity': f"{qty_formatted:f}".rstrip('0').rstrip('.'),
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

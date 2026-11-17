import time
import hmac
import hashlib
import requests
import json
import config
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
        """Fetches lot size, price, and notional filters for exact precision on Binance"""
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
                    min_notional = 5.0
                    for f in s.get('filters', []):
                        if f['filterType'] == 'LOT_SIZE':
                            step_size = float(f['stepSize'])
                            min_qty = float(f['minQty'])
                        elif f['filterType'] == 'PRICE_FILTER':
                            tick_size = float(f['tickSize'])
                        elif f['filterType'] in ('NOTIONAL', 'MIN_NOTIONAL'):
                            min_notional = float(f.get('minNotional', f.get('notional', 5.0)))
                    return {
                        'step_size': step_size,
                        'tick_size': tick_size,
                        'min_qty': min_qty,
                        'min_notional': min_notional
                    }
        except Exception:
            pass
        return {'step_size': 0.0001, 'tick_size': 0.0001, 'min_qty': 0.0, 'min_notional': 5.0}

    def round_step(self, value, step_size):
        """Rounds a number to the nearest step size, properly handling scientific notation"""
        import decimal
        try:
            d_step = decimal.Decimal(f"{step_size:.10f}".rstrip('0'))
            d_val = decimal.Decimal(f"{value:.10f}")
            res = (d_val // d_step) * d_step
            return float(res)
        except Exception:
            return round(value, 4)

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
            timestamp = self._get_timestamp()
            params = {'timestamp': timestamp, 'recvWindow': 60000}
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
        return self.get_asset_free_balance('USDT')

    def place_market_buy(self, pair, quote_amount_usdt):
        if not getattr(config, 'AUTO_TRADE', False):
            return None, "التداول الآلي معطل (Advisory Mode)"
            
        cur_price = self.get_ticker_price(pair)
        if not cur_price:
            return None, "فشل جلب السعر اللحظي من باينانس"
            
        filters = self.get_symbol_filters(pair)
        min_notional = filters.get('min_notional', 5.0)
        if quote_amount_usdt < min_notional:
            return None, f"مبلغ الشراء ({quote_amount_usdt} USDT) أقل من الحد الأدنى المقبول في باينانس ({min_notional} USDT)"

        if self.dry_run:
            qty = round(quote_amount_usdt / cur_price, 6)
            self.simulated_balance -= quote_amount_usdt
            return {
                'orderId': f"SIM_{int(time.time())}",
                'executedQty': qty,
                'cummulativeQuoteQty': quote_amount_usdt,
                'price': cur_price,
                'avg_price': cur_price,
                'executed_qty': qty,
                'is_simulation': True
            }, "تم تنفيذ أمر شراء تجريبي (Paper Trade)"
            
        try:
            timestamp = self._get_timestamp()
            params = {
                'symbol': pair,
                'side': 'BUY',
                'type': 'MARKET',
                'quoteOrderQty': round(quote_amount_usdt, 2),
                'timestamp': timestamp,
                'recvWindow': 60000
            }
            signed_query = self._sign(params)
            headers = {'X-MBX-APIKEY': self.api_key}
            url = f"{BINANCE_REST_URL}/api/v3/order?{signed_query}"
            
            r = requests.post(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                executed_qty = float(data.get('executedQty', 0.0))
                cum_quote = float(data.get('cummulativeQuoteQty', 0.0))
                avg_price = (cum_quote / executed_qty) if executed_qty > 0 else cur_price
                data['avg_price'] = avg_price
                data['executed_qty'] = executed_qty
                return data, "تم تنفيذ أمر الشراء بنجاح على باينانس ✅"
            else:
                err_data = r.json() if 'json' in r.headers.get('content-type', '') else {}
                err_msg = err_data.get('msg', r.text)
                return None, f"خطأ من باينانس ({r.status_code}): {err_msg}"
        except Exception as e:
            return None, f"خطأ اتصال أثناء الشراء: {e}"

    def _get_timestamp(self):
        try:
            r = requests.get(f"{BINANCE_REST_URL}/api/v3/time", timeout=2)
            if r.status_code == 200:
                return r.json().get('serverTime', int(time.time() * 1000))
        except Exception:
            pass
        return int(time.time() * 1000)

    def get_open_orders(self, pair=None):
        """Fetches active open orders from Binance"""
        if self.dry_run:
            return []
        try:
            ts = self._get_timestamp()
            params = {'timestamp': ts, 'recvWindow': 60000}
            if pair:
                params['symbol'] = pair
            signed = self._sign(params)
            headers = {'X-MBX-APIKEY': self.api_key}
            r = requests.get(f"{BINANCE_REST_URL}/api/v3/openOrders?{signed}", headers=headers, timeout=8)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            print(f"Error fetching open orders: {e}")
        return []

    def get_symbol_recent_orders(self, pair, limit=10):
        """Fetches recently completed/canceled orders for a symbol"""
        if self.dry_run:
            return []
        try:
            ts = self._get_timestamp()
            params = {'symbol': pair, 'limit': limit, 'timestamp': ts, 'recvWindow': 60000}
            signed = self._sign(params)
            headers = {'X-MBX-APIKEY': self.api_key}
            r = requests.get(f"{BINANCE_REST_URL}/api/v3/allOrders?{signed}", headers=headers, timeout=8)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            print(f"Error fetching recent orders for {pair}: {e}")
        return []

    def place_stop_loss_limit(self, pair, quantity, stop_price):
        """Places a standalone Stop-Loss Limit order on Binance servers"""
        base_asset = pair.replace("USDT", "")
        actual_free = self.get_asset_free_balance(base_asset)
        if actual_free > 0 and quantity > actual_free:
            quantity = actual_free
            
        filters = self.get_symbol_filters(pair)
        step_size = filters['step_size']
        tick_size = filters['tick_size']
        
        qty_formatted = self.round_step(quantity, step_size)
        if qty_formatted > actual_free and actual_free > 0:
            import decimal
            d_qty = decimal.Decimal(f"{qty_formatted:.10f}".rstrip('0'))
            d_step = decimal.Decimal(f"{step_size:.10f}".rstrip('0'))
            qty_formatted = float(d_qty - d_step)
            
        sl_formatted = self.round_step(stop_price, tick_size)
        limit_formatted = self.round_step(stop_price * 0.998, tick_size)
        
        if self.dry_run:
            return {'orderId': f"SIM_SL_{int(time.time())}"}, "تم وضع أمر وقف الخسارة تجريبياً"
            
        try:
            ts = self._get_timestamp()
            params = {
                'symbol': pair,
                'side': 'SELL',
                'type': 'STOP_LOSS_LIMIT',
                'quantity': f"{qty_formatted:f}".rstrip('0').rstrip('.'),
                'price': f"{limit_formatted:f}".rstrip('0').rstrip('.'),
                'stopPrice': f"{sl_formatted:f}".rstrip('0').rstrip('.'),
                'timeInForce': 'GTC',
                'timestamp': ts,
                'recvWindow': 60000
            }
            signed_query = self._sign(params)
            headers = {'X-MBX-APIKEY': self.api_key}
            url = f"{BINANCE_REST_URL}/api/v3/order?{signed_query}"
            r = requests.post(url, headers=headers, timeout=10)
            if r.status_code == 200:
                return r.json(), "تم وضع أمر وقف الخسارة بنجاح على سيرفرات باينانس ✅"
            else:
                return None, f"خطأ أمر الوقف: {r.text}"
        except Exception as e:
            return None, f"خطأ اتصال أمر الوقف: {e}"

    def place_native_oco_order(self, pair, quantity, tp_price, sl_price):
        """
        Places a Native OCO Order directly on Binance exchange servers!
        Binance itself holds and executes the Take Profit and Stop Loss
        even if laptop, GitHub, and internet are 100% offline!
        """
        base_asset = pair.replace("USDT", "")
        actual_free = self.get_asset_free_balance(base_asset)
        if actual_free > 0 and quantity > actual_free:
            quantity = actual_free
            
        filters = self.get_symbol_filters(pair)
        step_size = filters['step_size']
        tick_size = filters['tick_size']
        
        qty_formatted = self.round_step(quantity, step_size)
        if qty_formatted > actual_free and actual_free > 0:
            import decimal
            d_qty = decimal.Decimal(f"{qty_formatted:.10f}".rstrip('0'))
            d_step = decimal.Decimal(f"{step_size:.10f}".rstrip('0'))
            qty_formatted = float(d_qty - d_step)
            
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
            timestamp = self._get_timestamp()
            params = {
                'symbol': pair,
                'side': 'SELL',
                'quantity': f"{qty_formatted:f}".rstrip('0').rstrip('.'),
                'price': f"{tp_formatted:f}".rstrip('0').rstrip('.'),
                'stopPrice': f"{sl_formatted:f}".rstrip('0').rstrip('.'),
                'stopLimitPrice': f"{sl_limit_formatted:f}".rstrip('0').rstrip('.'),
                'stopLimitTimeInForce': 'GTC',
                'timestamp': timestamp,
                'recvWindow': 60000
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

    def get_all_prices_map(self):
        """Fetches all Binance ticker prices in a single ultra-fast HTTP request"""
        try:
            r = requests.get(f"{BINANCE_REST_URL}/api/v3/ticker/price", timeout=5)
            if r.status_code == 200:
                return {item['symbol']: float(item['price']) for item in r.json()}
        except Exception:
            pass
        return {}

    def get_total_account_equity(self):
        """Calculates total spot portfolio value in USDT (Free USDT + All Coin Balances in USDT)"""
        if self.dry_run:
            return self.simulated_balance
            
        try:
            timestamp = self._get_timestamp()
            params = {'timestamp': timestamp, 'recvWindow': 60000}
            signed_query = self._sign(params)
            headers = {'X-MBX-APIKEY': self.api_key}
            url = f"{BINANCE_REST_URL}/api/v3/account?{signed_query}"
            
            r = requests.get(url, headers=headers, timeout=8)
            if r.status_code == 200:
                data = r.json()
                price_map = self.get_all_prices_map()
                total_usdt = 0.0
                for b in data.get('balances', []):
                    free = float(b['free'])
                    locked = float(b['locked'])
                    tot_qty = free + locked
                    if tot_qty <= 0.0001:
                        continue
                        
                    asset = b['asset']
                    if asset == 'USDT':
                        total_usdt += tot_qty
                    else:
                        price = price_map.get(f"{asset}USDT", 0.0)
                        if price > 0:
                            total_usdt += tot_qty * price
                return total_usdt if total_usdt > 0 else self.get_usdt_balance()
        except Exception as e:
            print(f"Error calculating total equity: {e}")
            
        return self.get_usdt_balance()

    def get_held_assets(self):
        """Returns list of symbols currently held in Binance wallet with value > 5 USDT"""
        if self.dry_run:
            return []
        try:
            timestamp = self._get_timestamp()
            params = {'timestamp': timestamp, 'recvWindow': 60000}
            signed_query = self._sign(params)
            headers = {'X-MBX-APIKEY': self.api_key}
            url = f"{BINANCE_REST_URL}/api/v3/account?{signed_query}"
            r = requests.get(url, headers=headers, timeout=8)
            if r.status_code == 200:
                data = r.json()
                price_map = self.get_all_prices_map()
                held = []
                for b in data.get('balances', []):
                    tot = float(b['free']) + float(b['locked'])
                    if tot <= 0.0001:
                        continue
                    asset = b['asset']
                    if asset in ['USDT', 'USDC', 'FDUSD', 'BNB']:
                        continue
                    price = price_map.get(f"{asset}USDT", 0.0)
                    val = tot * price
                    if val >= 5.0:
                        held.append(asset)
                return held
        except Exception:
            pass
        return []

    def get_asset_free_balance(self, asset):
        """Fetches the actual free balance of a specific asset in Spot wallet"""
        if self.dry_run:
            return 999999.0
        try:
            ts = self._get_timestamp()
            params = {'timestamp': ts, 'recvWindow': 60000}
            signed = self._sign(params)
            headers = {'X-MBX-APIKEY': self.api_key}
            r = requests.get(f"{BINANCE_REST_URL}/api/v3/account?{signed}", headers=headers, timeout=5)
            if r.status_code == 200:
                for b in r.json().get('balances', []):
                    if b['asset'] == asset:
                        return float(b['free'])
        except Exception as e:
            print(f"Error fetching free balance for {asset}: {e}")
        return 0.0

    def cancel_all_open_orders(self, pair):
        """Cancels all open orders (e.g. pending OCO) for a symbol before market sell"""
        if self.dry_run:
            return True, "تم إلغاء الأوامر تجريبياً"
        try:
            timestamp = self._get_timestamp()
            params = {'symbol': pair, 'timestamp': timestamp, 'recvWindow': 60000}
            signed_query = self._sign(params)
            headers = {'X-MBX-APIKEY': self.api_key}
            url = f"{BINANCE_REST_URL}/api/v3/openOrders?{signed_query}"
            r = requests.delete(url, headers=headers, timeout=8)
            if r.status_code == 200:
                return True, "تم إلغاء الأوامر المفتوحة بنجاح"
            else:
                return False, f"فشل إلغاء الأوامر: {r.text}"
        except Exception as e:
            return False, f"خطأ في الإلغاء: {e}"

    def place_market_sell(self, pair, quantity=None):
        if not getattr(config, 'AUTO_TRADE', False):
            return None, "التداول الآلي معطل (Advisory Mode)"
            
        cur_price = self.get_ticker_price(pair)
        if not cur_price:
            return None, "فشل جلب السعر اللحظي من باينانس"
            
        base_asset = pair.replace("USDT", "")
        
        # 1. Cancel any open pending orders (e.g. SL or OCO) to release locked balance
        if not self.dry_run:
            try:
                self.cancel_all_open_orders(pair)
                time.sleep(0.5)
            except Exception as e:
                print(f"Warning canceling open orders before sell: {e}")

        # 2. Query real free balance directly from Binance Spot wallet
        actual_free = self.get_asset_free_balance(base_asset)
        if actual_free <= 0.00000001:
            return None, f"لا يوجد رصيد حر متاح من عملة {base_asset} للبيع (الرصيد: 0)"

        # 3. Retrieve exchange filters
        filters = self.get_symbol_filters(pair)
        step_size = filters.get('step_size', 1.0)
        min_qty = filters.get('min_qty', 0.0)
        min_notional = filters.get('min_notional', 5.0)

        import decimal
        try:
            d_step = decimal.Decimal(f"{step_size:.10f}".rstrip('0'))
            d_free = decimal.Decimal(f"{actual_free:.10f}")
            # Max possible sellable quantity in wallet
            max_sellable = float((d_free // d_step) * d_step)
        except Exception:
            max_sellable = self.round_step(actual_free, step_size)

        if max_sellable <= 0 or max_sellable < min_qty:
            return None, f"الكمية المتاحة ({actual_free}) أقل من الحد الأدنى للطلب ({min_qty})"

        # Determine target sell quantity
        if quantity is None or quantity >= max_sellable:
            qty_to_sell = max_sellable
        else:
            try:
                d_target = decimal.Decimal(f"{quantity:.10f}")
                qty_to_sell = float((d_target // d_step) * d_step)
            except Exception:
                qty_to_sell = self.round_step(quantity, step_size)

            # Check if remaining dust would violate min_notional:
            remaining_qty = max_sellable - qty_to_sell
            remaining_val = remaining_qty * cur_price
            if remaining_val < min_notional:
                # To prevent leaving unsellable dust (< 5$), sell 100% of available coins!
                qty_to_sell = max_sellable

        # Check total notional value of order
        order_val = qty_to_sell * cur_price
        if order_val < min_notional:
            return None, f"قيمة البيع ({order_val:.2f} USDT) أقل من الحد الأدنى المقبول في باينانس ({min_notional:.2f} USDT)"

        if self.dry_run:
            usd_returned = qty_to_sell * cur_price
            self.simulated_balance += usd_returned
            return {
                'orderId': f"SIM_SELL_{int(time.time())}",
                'executedQty': qty_to_sell,
                'price': cur_price,
                'cummulativeQuoteQty': usd_returned,
                'is_simulation': True
            }, "تم تنفيذ أمر بيع تجريبي (Paper Trade)"

        try:
            timestamp = self._get_timestamp()
            # Format quantity with exact precision
            d_final = decimal.Decimal(f"{qty_to_sell:.10f}").normalize()
            qty_str = format(d_final, 'f')
            if '.' in qty_str:
                qty_str = qty_str.rstrip('0').rstrip('.')

            params = {
                'symbol': pair,
                'side': 'SELL',
                'type': 'MARKET',
                'quantity': qty_str,
                'timestamp': timestamp,
                'recvWindow': 60000
            }
            signed_query = self._sign(params)
            headers = {'X-MBX-APIKEY': self.api_key}
            url = f"{BINANCE_REST_URL}/api/v3/order?{signed_query}"

            r = requests.post(url, headers=headers, timeout=10)
            if r.status_code == 200:
                return r.json(), "تم تنفيذ أمر البيع بنجاح على باينانس ✅"
            else:
                err_data = r.json() if 'json' in r.headers.get('content-type', '') else {}
                err_msg = err_data.get('msg', r.text)
                return None, f"خطأ باينانس ({r.status_code}): {err_msg}"
        except Exception as e:
            return None, f"خطأ اتصال أثناء البيع: {e}"

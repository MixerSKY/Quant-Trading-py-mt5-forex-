import MetaTrader5 as mt5
import pandas as pd
import time
import sys
import os
import csv
import pytz
from datetime import datetime, timedelta

class MT5SMCEngineV4_1:
    def __init__(self, symbol="GBPJPY"):
        self.symbol = symbol

       # =====================================================================
        # [1] ARCHITEKTURA KAPITAŁU I RYZYKA (SKALOWALNA)
        # =====================================================================
        self.initial_balance = 10000.0   
        
        # Definicja parametrów procentowych (Skalowanie konta)
        self.risk_per_trade_pct = 0.005  # Ryzyko na trade (0.5%)
        self.daily_loss_pct = 0.04       # Dzienny bufor bezpieczeństwa (4.0% - chroni przed 5% Prop Firmy)
        self.total_loss_pct = 0.09       # Całkowity bufor bezpieczeństwa (8.0% - chroni przed 10% Prop Firmy)
        
        # Matematyczna kompilacja na twarde dolary (Zawsze od bazy!)
        self.base_risk_usd = self.initial_balance * self.risk_per_trade_pct
        self.daily_loss_limit = -(self.initial_balance * self.daily_loss_pct)
        self.total_loss_limit = self.initial_balance * (1.0 - self.total_loss_pct)

        self.max_lot_cap = 0.3 #Max lota, można dostosować do wymagań brokera lub preferencji
        self.max_daily_trades = 2 #Maksymalna liczba tradeów

        # Ścieżki
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.log_file = os.path.join(script_dir, f"live_trade_journal_{self.symbol}.csv")
        
        # =====================================================================
        # [2] INICJALIZACJA I PAMIĘĆ (PERSISTENCE)
        # =====================================================================
        print(f"⚙️ Inicjalizacja Głównego Inżyniera V4.1 (True SMC) dla {self.symbol}...")
        if not mt5.initialize():
            print(f"🛑 BŁĄD MT5: {mt5.last_error()}"); sys.exit()
        if not mt5.symbol_select(self.symbol, True):
            print(f"🛑 BŁĄD: Symbol {self.symbol} nie znaleziony."); mt5.shutdown(); sys.exit()
            
        self.digits = mt5.symbol_info(self.symbol).digits
        self.setup_logger()
        
        # Twardy odczyt stanu konta i dzisiejszych transakcji z CSV
        self.virtual_balance, self.daily_pnl, self.daily_trades_count = self.load_state_from_csv()
        self.current_day = datetime.now().day
        
        # Zmienne SMC
        self.midnight_price = None       
        self.asr_high = None             
        self.asr_low = None              
        self.liquidity_swept = None
        self.structural_point = None     # Zapisany poziom pęknięcia struktury
        self.sweep_extremum = None       # Zapisany absolutny dołek/szczyt po wybiciu
        
        self.in_position = False
        self.position_type = ""
        self.entry_price = 0.0
        self.sl_price = 0.0
        self.tp_price = 0.0
        self.actual_lots = 0.0
        self.entry_time = None
        self.breakeven_activated = False
        
        print(f"✅ Maszyna gotowa. Pamięć: {self.daily_trades_count}/2 trade'ów dzisiaj. Bilans dzienny: {self.daily_pnl}$")

    # =====================================================================
    # [MODUŁ PAMIĘCI I ZABEZPIECZEŃ]
    # =====================================================================
    def setup_logger(self):
        if not os.path.isfile(self.log_file):
            with open(self.log_file, mode='w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(["Entry_Time", "Exit_Time", "Type", "Lots", "Entry_Price", 
                                 "Exit_Price", "Result", "PnL", "Balance_After", "Daily_PnL"])

    def load_state_from_csv(self):
        """Żelazna pamięć. Odtwarza stan konta i liczy dzisiejsze operacje, uodparniając na resety."""
        balance = self.initial_balance
        d_pnl = 0.0
        trades_today = 0
        
        if os.path.exists(self.log_file):
            try:
                df = pd.read_csv(self.log_file)
                if not df.empty:
                    balance = float(df['Balance_After'].iloc[-1])
                    
                    # Liczymy transakcje tylko z dzisiaj
                    df['Exit_Time'] = pd.to_datetime(df['Exit_Time'])
                    today_str = datetime.now().strftime('%Y-%m-%d')
                    today_trades = df[df['Exit_Time'].dt.strftime('%Y-%m-%d') == today_str]
                    
                    trades_today = len(today_trades)
                    d_pnl = today_trades['PnL'].sum()
            except Exception as e:
                print(f"⚠️ Błąd odczytu CSV: {e}")
                
        return balance, d_pnl, trades_today

    def check_daily_reset(self):
        now = datetime.now()
        if now.day != self.current_day:
            print(f"\n🌅 NOWY DZIEŃ. Resetowanie limitów z wczoraj.")
            self.daily_pnl = 0.0
            self.daily_trades_count = 0
            self.current_day = now.day
            self.midnight_price, self.asr_high, self.asr_low = None, None, None
            self.liquidity_swept, self.structural_point, self.sweep_extremum = None, None, None

    def get_ny_time(self):
        return datetime.now(pytz.utc).astimezone(pytz.timezone('America/New_York'))

    # =====================================================================
    # [MODUŁ GEOMETRII RYNKU - SILNIK SMC V4.1]
    # =====================================================================
    def update_market_context(self):
        rates = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_M5, 0, 300)
        if rates is None: return False
        df = pd.DataFrame(rates)
        
        daily_rates = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_D1, 0, 1)
        if daily_rates is not None:
            self.midnight_price = daily_rates[0]['open']

        # Zasięg Azji
        asian_df = df.iloc[-80:-20]
        self.asr_high = asian_df['high'].max()
        self.asr_low = asian_df['low'].min()

        # Detekcja zebrania płynności
        current_price = df.iloc[-1]['close']
        recent_high = df.iloc[-20:]['high'].max()
        recent_low = df.iloc[-20:]['low'].min()
        
        # BULLISH SWEEP: Zeszli pod dołek z Azji, wycięli płynność
        if recent_low < self.asr_low and current_price > self.asr_low:
            self.liquidity_swept = "BULLISH"
            # Znajdujemy absolutny dołek tego wybicia (tu wyląduje nasz SL)
            self.sweep_extremum = recent_low
            
            # Szukamy struktury do wybicia: najwyższy punkt po zebraniu płynności a przed aktualną świecą
            sweep_index = df[df['low'] == self.sweep_extremum].index[-1]
            if sweep_index < len(df) - 1:
                self.structural_point = df.iloc[sweep_index:-1]['high'].max()
                
        # BEARISH SWEEP: Wyszli nad szczyt z Azji, wycięli płynność
        elif recent_high > self.asr_high and current_price < self.asr_high:
            self.liquidity_swept = "BEARISH"
            # Znajdujemy absolutny szczyt tego wybicia (tu wyląduje nasz SL)
            self.sweep_extremum = recent_high
            
            # Szukamy struktury do wybicia: najniższy punkt po zebraniu płynności a przed aktualną świecą
            sweep_index = df[df['high'] == self.sweep_extremum].index[-1]
            if sweep_index < len(df) - 1:
                self.structural_point = df.iloc[sweep_index:-1]['low'].min()
                
        return df

    def detect_market_structure_shift(self, df):
        """Prawdziwa detekcja łamania struktury z PDFa."""
        if not self.liquidity_swept or not self.structural_point: return None
        
        c = df.iloc[-2] # Ostatnia zamknięta świeca
        
        if self.liquidity_swept == "BULLISH":
            if self.midnight_price and c['close'] < self.midnight_price:
                # Jeśli cena zamyka się fizycznie nad lokalną strukturą = MSS Potwierdzone
                if c['close'] > self.structural_point:
                    return "BUY"
                    
        elif self.liquidity_swept == "BEARISH":
            if self.midnight_price and c['close'] > self.midnight_price:
                # Jeśli cena zamyka się fizycznie pod lokalną strukturą = MSS Potwierdzone
                if c['close'] < self.structural_point:
                    return "SELL"
        return None

    # =====================================================================
    # [MODUŁ EGZEKUCJI I KALKULACJI LOTA]
    # =====================================================================
    def is_trading_allowed(self):
        if self.virtual_balance <= self.total_loss_limit:
            return False, f"TOTAL DRAWDOWN REACHED (${self.virtual_balance:.2f})"
        if self.daily_pnl <= self.daily_loss_limit:
            return False, f"DAILY LIMIT REACHED ({-self.daily_pnl}$)"
        if self.daily_trades_count >= self.max_daily_trades:
            return False, "MAX 2 TRADES/DAY REACHED"
            
        ny_time = self.get_ny_time()
        if not (1 <= ny_time.hour < 5):
            return False, "OUTSIDE LONDON KILLZONE (01:00-05:00 NY)"
        if ny_time.weekday() == 4 and ny_time.hour >= 12:
            return False, "FRIDAY AFTERNOON FLAT"
            
        return True, "KILLZONE ACTIVE"

    def execute_virtual_trade(self, order_type, current_price):
        self.in_position = True
        self.position_type = order_type
        self.entry_price = current_price
        self.entry_time = datetime.now()
        self.breakeven_activated = False
        self.daily_trades_count += 1 
        
        sym_info = mt5.symbol_info(self.symbol)
        
        # SL leży dokładnie na ekstremum wybicia (SMC Rule) + minimalny bufor ochronny
        buffer = sym_info.trade_tick_size * 20 # mały spread bufor
        
        if order_type == "BUY":
            self.sl_price = self.sweep_extremum - buffer
            dist = self.entry_price - self.sl_price
            # Zabezpieczenie przed mikroskopijnym SL
            if dist < (sym_info.trade_tick_size * 50): 
                dist = sym_info.trade_tick_size * 50
                self.sl_price = self.entry_price - dist
            self.tp_price = self.entry_price + (dist * 2.0)
        else:
            self.sl_price = self.sweep_extremum + buffer
            dist = self.sl_price - self.entry_price
            if dist < (sym_info.trade_tick_size * 50): 
                dist = sym_info.trade_tick_size * 50
                self.sl_price = self.entry_price + dist
            self.tp_price = self.entry_price - (dist * 2.0)
            
        # Prawidłowa kalkulacja lota dostosowana do MT5
        ticks_at_risk = dist / sym_info.trade_tick_size
        monetary_risk_per_lot = ticks_at_risk * sym_info.trade_tick_value
        
        if monetary_risk_per_lot > 0:
            calculated_lots = self.base_risk_usd / monetary_risk_per_lot
        else:
            calculated_lots = 0.01
            
        # Ograniczanie kagańcem i krokami brokera
        self.actual_lots = min(calculated_lots, self.max_lot_cap)
        self.actual_lots = max(self.actual_lots, sym_info.volume_min)
        # Zaokrąglenie do właściwego kroku lota
        step = sym_info.volume_step
        self.actual_lots = round(self.actual_lots / step) * step
        
        print("\n" + "🔥"*10)
        print(f"🚨 SMC WEJŚCIE: {order_type} @ {self.entry_price:.{self.digits}f}")
        print(f"📊 Loty: {self.actual_lots:.2f} | Ryzyko teoretyczne: ~${(self.actual_lots * monetary_risk_per_lot):.2f}")
        print(f"🛡️ SL: {self.sl_price:.{self.digits}f} | TP: {self.tp_price:.{self.digits}f}")
        print("🔥"*10 + "\n")

    def manage_position(self, tick):
        if not self.in_position: return
        current_price = tick.bid if self.position_type == "BUY" else tick.ask
        
        if not self.breakeven_activated:
            dist_to_sl = abs(self.entry_price - self.sl_price)
            if self.position_type == "BUY" and current_price >= self.entry_price + dist_to_sl:
                self.sl_price = self.entry_price
                self.breakeven_activated = True
                print("🛡️ PRZESUNIĘTO SL NA PUNKT WEJŚCIA (BREAK EVEN)")
            elif self.position_type == "SELL" and current_price <= self.entry_price - dist_to_sl:
                self.sl_price = self.entry_price
                self.breakeven_activated = True
                print("🛡️ PRZESUNIĘTO SL NA PUNKT WEJŚCIA (BREAK EVEN)")

        if self.position_type == "BUY":
            if current_price <= self.sl_price: self.close_position(tick, "SL_HIT")
            elif current_price >= self.tp_price: self.close_position(tick, "TP_HIT")
        else:
            if current_price >= self.sl_price: self.close_position(tick, "SL_HIT")
            elif current_price <= self.tp_price: self.close_position(tick, "TP_HIT")

    def close_position(self, tick, reason):
        exit_price = tick.bid if self.position_type == "BUY" else tick.ask
        sym_info = mt5.symbol_info(self.symbol)
        
        points_moved = abs(exit_price - self.entry_price) / sym_info.trade_tick_size
        usd_moved = self.actual_lots * points_moved * sym_info.trade_tick_value
        
        if self.position_type == "BUY": pnl = usd_moved if exit_price > self.entry_price else -usd_moved
        else: pnl = usd_moved if exit_price < self.entry_price else -usd_moved

        self.virtual_balance += pnl
        self.daily_pnl += pnl
        self.liquidity_swept, self.structural_point, self.sweep_extremum = None, None, None
        
        with open(self.log_file, mode='a', newline='') as file:
            csv.writer(file).writerow([
                self.entry_time.strftime('%Y-%m-%d %H:%M:%S'), datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                self.position_type, self.actual_lots, round(self.entry_price, self.digits), round(exit_price, self.digits),
                reason, round(pnl, 2), round(self.virtual_balance, 2), round(self.daily_pnl, 2)
            ])
            
        icon = "🟢" if pnl > 0 else "🔴"
        print(f"\n{icon} SMC TRADE ZAMKNIĘTY ({reason})")
        print(f"PnL: ${pnl:.2f} | Dzisiejszy bilans: ${self.daily_pnl:.2f}")
        print(f"Użyte próby: {self.daily_trades_count}/{self.max_daily_trades}\n")
        self.in_position = False

    def run(self):
        try:
            loop_counter = 0
            while True:
                self.check_daily_reset()
                tick = mt5.symbol_info_tick(self.symbol)
                if tick is None:
                    time.sleep(1)
                    continue
                
                self.manage_position(tick)
                
                if not self.in_position and loop_counter % 10 == 0:
                    allowed, reason = self.is_trading_allowed()
                    if allowed:
                        df = self.update_market_context()
                        if df is not False:
                            signal = self.detect_market_structure_shift(df)
                            if signal == "BUY": self.execute_virtual_trade("BUY", tick.ask)
                            elif signal == "SELL": self.execute_virtual_trade("SELL", tick.bid)
                
                if loop_counter % 20 == 0:
                    status = "W POZYCJI" if self.in_position else "NASŁUCH"
                    allowed, reason = self.is_trading_allowed()
                    mss_info = f" | Struktura: {self.structural_point:.{self.digits}f}" if self.structural_point else ""
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] {self.symbol} | ASR: {self.liquidity_swept or 'Brak'}{mss_info} | Śluza: {reason} | {status}")
                
                loop_counter += 1
                time.sleep(1)
                
        except KeyboardInterrupt:
            print(f"\n🛑 Zatrzymano V4.1 dla {self.symbol}.")
        finally:
            mt5.shutdown()

if __name__ == "__main__":
    target_symbol = sys.argv[1] if len(sys.argv) > 1 else "GBPJPY"
    bot = MT5SMCEngineV4_1(symbol=target_symbol)
    bot.run()
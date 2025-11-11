
"""
ULTRA-AGGRESSIVE XAUUSD M1 Scalping Bot - WITH MARGIN SAFETY
- 1.5% risk/trade, tight SL (400-800 pts), 3:1 RR, max 4 positions
- Trades 24/5, 15-25 trades/day expected
- Target: 120-150%/month | HIGH RISK: DEMO ONLY
- Margin-safe for $5K account at 1:100 leverage

Requirements: pip install MetaTrader5 numpy pandas
"""

import time
import math
import os
import numpy as np
import pandas as pd
from datetime import datetime, timezone

import MetaTrader5 as mt5

# ========= ACCOUNT CONFIG =========
LOGIN = 0                    # Leave 0 to use current MT5 account
PASSWORD = ""                 # Your password (only if LOGIN > 0)
SERVER = ""     # Exact server name from MT5

SYMBOL = "XAUUSDm"             # Adjust if "XAUUSDm" or similar

# ========= AGGRESSIVE RISK SETTINGS (MARGIN-SAFE) =========
USE_RISK_PERCENT = True
RISK_PERCENT = 1.5            # 1.5% per trade (~$75 on $5K) - margin-safe
FIXED_LOT = 0.05              # Fallback if risk calc fails

MAX_OPEN_POSITIONS = 4        # Max concurrent positions (prevents margin lock)

# ========= TIGHT SCALPING STOPS =========
USE_STRUCTURAL_SL = True      # Based on candle range
SL_POINTS_MIN = 400           # Minimum SL (points) - slightly wider
SL_POINTS_MAX = 1000          # Maximum SL (points)
RR = 3.0                      # 3:1 risk-reward

# ========= NO FILTERS (AGGRESSIVE) =========
MAX_SPREAD_POINTS = 500       # Basically unlimited
SESSION_FILTER = False        # Trade 24/5
VOLUME_FILTER = False         # No volume check
MIN_CANDLE_RANGE_POINTS = 25  # Skip only tiny candles

# ========= TRADE MANAGEMENT =========
MOVE_TO_BREAKEVEN_AT_R = 0.5  # Move to BE at 0.5R
PARTIAL_CLOSE_AT_R = 1.5      # Partial close at 1.5R
PARTIAL_CLOSE_FRACTION = 0.3  # Close 30% of position
COOLDOWN_MINUTES = 0          # No cooldown between trades

# ========= ENGINE =========
MAGIC = 88001199
DEVIATION_POINTS = 150
M1_BARS = 600
M5_BARS = 300
POLL_SECONDS = 0.5

# ========= PATTERN DETECTION (LOOSE) =========
SWEEP_LOOKBACK = 6            # Very recent swings
SWEEP_BUFFER_POINTS = 3       # Small buffer = more signals
REJECTION_MIN_WICK_FRAC = 0.15# Accept small wicks
M5_BIAS_STRICT = False        # Ignore M5 bias
REQUIRE_ENGULF = False        # No engulf required

DIAGNOSTICS = True            # Show skip reasons

# ========= MT5 CONNECTION (ROBUST) =========
POSSIBLE_MT5_PATHS = [
    "C:\\Program Files\\MetaTrader 5\\terminal64.exe",
    "C:\\Program Files\\Exness MetaTrader 5\\terminal64.exe",
    "C:\\Program Files (x86)\\MetaTrader 5\\terminal64.exe",
    "C:\\Program Files (x86)\\Exness MetaTrader 5\\terminal64.exe",
]

def log(msg):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {msg}")

def find_mt5_path():
    for path in POSSIBLE_MT5_PATHS:
        if os.path.exists(path):
            return path
    return None

def ensure_initialized():
    log("Connecting to MT5...")
    
    # Method 1: Auto-detect (if MT5 running)
    if mt5.initialize():
        log("✓ Connected (auto-detect)")
        return True
    
    err1 = mt5.last_error()
    log(f"Auto-detect failed: {err1}")
    
    # Method 2: Try known paths
    mt5_path = find_mt5_path()
    if mt5_path:
        log(f"Trying: {mt5_path}")
        if mt5.initialize(path=mt5_path):
            log("✓ Connected (explicit path)")
            return True
        log(f"Path failed: {mt5.last_error()}")
    
    # Final error
    raise RuntimeError(
        f"MT5 connection failed. Last error: {mt5.last_error()}\n"
        "Fix:\n"
        "1. Open MetaTrader 5 desktop app manually\n"
        "2. Login to your Exness demo account\n"
        "3. Run this script again"
    )

def login_if_needed():
    if LOGIN and LOGIN > 0:
        log(f"Logging into account {LOGIN}...")
        if mt5.login(LOGIN, password=PASSWORD, server=SERVER):
            log(f"✓ Logged into {LOGIN}")
        else:
            log(f"⚠ Login failed: {mt5.last_error()}")
            log("Continuing with current account")
    else:
        account = mt5.account_info()
        if account:
            log(f"Using account: {account.login} | Balance: ${account.balance:.2f}")
            log(f"Margin: Used ${account.margin:.2f} | Free ${account.margin_free:.2f} | Level {account.margin_level:.0f}%")
        else:
            log("⚠ No account info")

def ensure_symbol(symbol):
    info = mt5.symbol_info(symbol)
    if info and info.visible:
        return info
    
    # Try to enable in Market Watch
    if info and not info.visible:
        log(f"Enabling {symbol} in Market Watch...")
        if mt5.symbol_select(symbol, True):
            return mt5.symbol_info(symbol)
    
    # Suggest alternatives
    all_symbols = mt5.symbols_get()
    if all_symbols:
        cands = [s.name for s in all_symbols if "XAUUSDm" in s.name.upper() or "GOLD" in s.name.upper()]
        if cands:
            log(f"Symbol '{symbol}' not found. Try: {cands[:5]}")
    
    raise RuntimeError(f"Symbol '{symbol}' unavailable. Check Market Watch in MT5.")

def normalize_price(price, digits):
    factor = 10 ** digits
    return math.floor(price * factor + 0.5) / factor

def utc_now():
    return datetime.now(timezone.utc)

def get_rates(symbol, timeframe, count):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
    return rates if rates is not None else np.array([])

def get_tick(symbol):
    return mt5.symbol_info_tick(symbol)

def spread_points(symbol_info, tick):
    if tick is None:
        return 999
    return (tick.ask - tick.bid) / symbol_info.point

# ========= PRICE ACTION =========
def candle_parts(c):
    o, h, l, cl = c['open'], c['high'], c['low'], c['close']
    rng = max(h - l, 1e-9)
    bull = cl > o
    bear = cl < o
    upper_wick = h - max(o, cl)
    lower_wick = min(o, cl) - l
    body = abs(cl - o)
    return {
        "open": o, "high": h, "low": l, "close": cl,
        "range": rng, "bull": bull, "bear": bear,
        "upper_wick": upper_wick, "lower_wick": lower_wick,
        "body": body
    }

def m5_bias(symbol):
    if not M5_BIAS_STRICT:
        return 1  # Always allow both directions
    rates = get_rates(symbol, mt5.TIMEFRAME_M5, M5_BARS)
    if len(rates) < 5:
        return 0
    return 1 if rates[-1]['close'] > rates[-5]['close'] else -1

def swept_prior_low(m1_rates, c1, symbol_info):
    point = symbol_info.point
    lows = m1_rates['low'][-(SWEEP_LOOKBACK+2):-2]
    if lows.size == 0:
        return False
    prior_min = float(lows.min())
    return c1['low'] < prior_min - SWEEP_BUFFER_POINTS * point

def swept_prior_high(m1_rates, c1, symbol_info):
    point = symbol_info.point
    highs = m1_rates['high'][-(SWEEP_LOOKBACK+2):-2]
    if highs.size == 0:
        return False
    prior_max = float(highs.max())
    return c1['high'] > prior_max + SWEEP_BUFFER_POINTS * point

def last_closed_m1(symbol):
    rates = get_rates(symbol, mt5.TIMEFRAME_M1, M1_BARS)
    if len(rates) < SWEEP_LOOKBACK + 3:
        return None, None
    return rates, rates[-2]

# ========= ORDERS WITH MARGIN SAFETY =========
def get_open_positions(symbol):
    poss = mt5.positions_get(symbol=symbol)
    return poss if poss else []

def choose_filling_mode(symbol):
    info = mt5.symbol_info(symbol)
    tick = get_tick(symbol)
    if info is None or tick is None:
        return mt5.ORDER_FILLING_FOK
    
    test_price = tick.ask
    test_vol = max(info.volume_min, info.volume_step)
    
    for mode in [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]:
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": test_vol,
            "type": mt5.ORDER_TYPE_BUY,
            "price": test_price,
            "deviation": 20,
            "type_filling": mode,
            "type_time": mt5.ORDER_TIME_GTC,
        }
        chk = mt5.order_check(req)
        if chk and getattr(chk, "retcode", None) == mt5.TRADE_RETCODE_DONE:
            return mode
    
    return mt5.ORDER_FILLING_IOC

def compute_lot(symbol_info, sl_points, account_info):
    """Calculate lot size with margin safety checks"""
    if not USE_RISK_PERCENT:
        return FIXED_LOT
    
    # Risk-based calculation
    risk_money = account_info.balance * (RISK_PERCENT / 100.0)
    tick_size = symbol_info.trade_tick_size or symbol_info.point
    tick_value = symbol_info.trade_tick_value or 1.0
    
    if tick_size <= 0:
        tick_size = symbol_info.point
    
    value_per_point = tick_value / (tick_size / symbol_info.point)
    if value_per_point <= 0:
        value_per_point = 1.0
    
    lots = risk_money / max(sl_points * value_per_point, 1e-9)
    
    # Apply min/max/step
    lot_min = symbol_info.volume_min
    lot_max = symbol_info.volume_max
    lot_step = symbol_info.volume_step
    lots = max(lot_min, min(lots, lot_max))
    lots = round(lots / lot_step) * lot_step
    
    # MARGIN SAFETY: Reduce lot if insufficient free margin
    free_margin = account_info.margin_free
    tick = get_tick(symbol_info.name)
    if tick and free_margin > 0:
        price = tick.ask
        # Estimate required margin (conservative for 1:100 leverage)
        # XAUUSD contract size typically 100 oz
        estimated_margin = (lots * 100 * price) / 100  # 1:100 leverage
        
        # If estimated margin > 70% of free margin, reduce lot size
        max_safe_margin = free_margin * 0.7
        if estimated_margin > max_safe_margin:
            safe_lots = (max_safe_margin * 100) / (100 * price)
            safe_lots = max(lot_min, round(safe_lots / lot_step) * lot_step)
            if safe_lots < lots:
                log(f"⚠ Lot reduced {lots:.2f} → {safe_lots:.2f} (margin safety)")
                lots = safe_lots
    
    return lots

def check_margin_available(symbol, lot_size):
    """Pre-check if sufficient margin for new position"""
    account = mt5.account_info()
    if not account:
        return False, "No account info"
    
    info = mt5.symbol_info(symbol)
    tick = get_tick(symbol)
    if not info or not tick:
        return False, "No symbol/tick"
    
    # Estimate required margin
    price = tick.ask
    estimated_margin = (lot_size * 100 * price) / 100  # Conservative 1:100
    
    free_margin = account.margin_free
    
    # Require at least 20% buffer
    if estimated_margin > free_margin * 0.8:
        return False, f"Low margin: need ~${estimated_margin:.0f}, free ${free_margin:.0f}"
    
    return True, "OK"

def place_order(symbol, order_type, volume, sl, tp, deviation_points):
    """Place order with margin pre-check"""
    info = mt5.symbol_info(symbol)
    tick = get_tick(symbol)
    
    if tick is None or info is None:
        log("⚠ No tick/info")
        return None
    
    # PRE-CHECK MARGIN
    margin_ok, margin_msg = check_margin_available(symbol, volume)
    if not margin_ok:
        log(f"✗ {margin_msg}")
        return None
    
    price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
    filling = choose_filling_mode(symbol)
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": normalize_price(price, info.digits),
        "sl": normalize_price(sl, info.digits),
        "tp": normalize_price(tp, info.digits),
        "deviation": int(deviation_points),
        "magic": MAGIC,
        "comment": "Aggressive",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling,
    }
    
    result = mt5.order_send(request)
    
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        sl_pts = int((price - sl) / info.point) if order_type == mt5.ORDER_TYPE_BUY else int((sl - price) / info.point)
        account = mt5.account_info()
        log(f"✓ {'BUY' if order_type == mt5.ORDER_TYPE_BUY else 'SELL'} {volume} lots | SL {sl_pts} pts | TP {int(sl_pts * RR)} pts")
        log(f"  Margin used: ${account.margin:.0f} | Free: ${account.margin_free:.0f}")
        return result
    
    if result:
        log(f"✗ Order failed: {result.comment}")
        if result.retcode == 10019:  # Not enough money
            account = mt5.account_info()
            log(f"  Balance ${account.balance:.2f} | Free margin ${account.margin_free:.2f}")
            log(f"  SOLUTION: Reduce RISK_PERCENT or MAX_OPEN_POSITIONS")
    else:
        log("✗ Order failed: No result")
    
    return None

def modify_sl(position_ticket, new_sl, new_tp):
    pos_list = mt5.positions_get(ticket=position_ticket)
    if not pos_list:
        return False
    
    req = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": position_ticket,
        "sl": new_sl,
        "tp": new_tp,
        "magic": MAGIC,
    }
    
    result = mt5.order_send(req)
    return result and result.retcode == mt5.TRADE_RETCODE_DONE

def close_partial(position, fraction):
    symbol = position.symbol
    info = mt5.symbol_info(symbol)
    tick = get_tick(symbol)
    
    if tick is None or info is None:
        return False
    
    vol = position.volume * fraction
    step = info.volume_step
    vol = max(info.volume_min, min(info.volume_max, round(vol / step) * step))
    
    if vol <= 0:
        return False
    
    order_type = mt5.ORDER_TYPE_SELL if position.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
    price = tick.bid if order_type == mt5.ORDER_TYPE_SELL else tick.ask
    
    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": vol,
        "type": order_type,
        "position": position.ticket,
        "price": normalize_price(price, info.digits),
        "deviation": DEVIATION_POINTS,
        "magic": MAGIC,
        "comment": "Partial",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": choose_filling_mode(symbol),
    }
    
    result = mt5.order_send(req)
    return result and result.retcode == mt5.TRADE_RETCODE_DONE

# ========= SIGNAL GENERATION =========
def build_signal(symbol):
    info = mt5.symbol_info(symbol)
    m1_rates, c1 = last_closed_m1(symbol)
    
    if c1 is None:
        return None, "no_data"
    
    tick = get_tick(symbol)
    if tick is None:
        return None, "no_tick"
    
    # Skip only extreme spreads
    spr = spread_points(info, tick)
    if spr > MAX_SPREAD_POINTS:
        return None, f"spread:{int(spr)}"
    
    # Skip tiny candles
    c1p = candle_parts(c1)
    if c1p["range"] < MIN_CANDLE_RANGE_POINTS * info.point:
        return None, "tiny_candle"
    
    bias = m5_bias(symbol)
    
    # BULLISH: Sweep low + bullish candle + lower wick
    if swept_prior_low(m1_rates, c1, info) and c1p["bull"]:
        lower_wick_frac = c1p["lower_wick"] / c1p["range"]
        if lower_wick_frac >= REJECTION_MIN_WICK_FRAC:
            entry_price = tick.ask
            
            # Tight structural SL
            sl_distance = max(c1p["range"] * 1.2, SL_POINTS_MIN * info.point)
            sl_distance = min(sl_distance, SL_POINTS_MAX * info.point)
            
            sl = entry_price - sl_distance
            sl_points = sl_distance / info.point
            tp = entry_price + RR * sl_distance
            
            return {
                "type": mt5.ORDER_TYPE_BUY,
                "sl": sl,
                "tp": tp,
                "sl_points": sl_points
            }, "long"
    
    # BEARISH: Sweep high + bearish candle + upper wick
    if swept_prior_high(m1_rates, c1, info) and c1p["bear"]:
        upper_wick_frac = c1p["upper_wick"] / c1p["range"]
        if upper_wick_frac >= REJECTION_MIN_WICK_FRAC:
            entry_price = tick.bid
            
            sl_distance = max(c1p["range"] * 1.2, SL_POINTS_MIN * info.point)
            sl_distance = min(sl_distance, SL_POINTS_MAX * info.point)
            
            sl = entry_price + sl_distance
            sl_points = sl_distance / info.point
            tp = entry_price - RR * sl_distance
            
            return {
                "type": mt5.ORDER_TYPE_SELL,
                "sl": sl,
                "tp": tp,
                "sl_points": sl_points
            }, "short"
    
    return None, "no_setup"

# ========= MAIN LOOP =========
def main():
    try:
        ensure_initialized()
        login_if_needed()
        
        info = ensure_symbol(SYMBOL)
        
        log("=" * 70)
        log(f"AGGRESSIVE SCALPER: {SYMBOL} (Margin-Safe)")
        log(f"Risk: {RISK_PERCENT}% per trade | Max {MAX_OPEN_POSITIONS} positions")
        log(f"SL: {SL_POINTS_MIN}-{SL_POINTS_MAX} pts | RR: {RR}:1")
        log(f"Target: 120-150%/month (15-25 trades/day) | HIGH RISK - DEMO ONLY")
        log("=" * 70)
        
        filling = choose_filling_mode(SYMBOL)
        log(f"Filling mode: {filling}")
        log(f"Point size: {info.point} | Digits: {info.digits}")
        
        last_m1_time = None
        trades_today = 0
        start_time = datetime.now()
        
        while True:
            try:
                info = mt5.symbol_info(SYMBOL)
                if info is None:
                    time.sleep(POLL_SECONDS)
                    continue
                
                # Check position limit
                open_positions = get_open_positions(SYMBOL)
                if len(open_positions) >= MAX_OPEN_POSITIONS:
                    time.sleep(POLL_SECONDS)
                    continue
                
                m1_rates = get_rates(SYMBOL, mt5.TIMEFRAME_M1, 3)
                if len(m1_rates) < 2:
                    time.sleep(POLL_SECONDS)
                    continue
                
                prev_time = datetime.fromtimestamp(m1_rates[-2]['time'], tz=timezone.utc)
                
                if last_m1_time and prev_time <= last_m1_time:
                    time.sleep(POLL_SECONDS)
                    continue
                
                # Manage open positions
                for position in open_positions:
                    tick = get_tick(SYMBOL)
                    if tick:
                        entry = position.price_open
                        point = info.point
                        direction = 1 if position.type == mt5.POSITION_TYPE_BUY else -1
                        price = tick.bid if direction == 1 else tick.ask
                        moved_points = direction * (price - entry) / point
                        sl_dist = direction * (entry - position.sl) / point if position.sl > 0 else None
                        
                        # BE at 0.5R
                        if MOVE_TO_BREAKEVEN_AT_R and sl_dist:
                            if moved_points >= MOVE_TO_BREAKEVEN_AT_R * sl_dist:
                                if abs(position.sl - entry) > point:
                                    new_sl = normalize_price(entry, info.digits)
                                    if modify_sl(position.ticket, new_sl, position.tp):
                                        log(f"→ BE (ticket {position.ticket})")
                        
                        # Partial at 1.5R
                        if PARTIAL_CLOSE_AT_R and sl_dist:
                            if moved_points >= PARTIAL_CLOSE_AT_R * sl_dist:
                                if close_partial(position, PARTIAL_CLOSE_FRACTION):
                                    log(f"→ Partial (ticket {position.ticket})")
                
                if len(open_positions) > 0:
                    time.sleep(POLL_SECONDS)
                    continue
                
                # New signal
                signal, reason = build_signal(SYMBOL)
                last_m1_time = prev_time
                
                if signal:
                    account = mt5.account_info()
                    lots = compute_lot(info, signal["sl_points"], account)
                    
                    res = place_order(
                        SYMBOL,
                        signal["type"],
                        lots,
                        signal["sl"],
                        signal["tp"],
                        DEVIATION_POINTS
                    )
                    
                    if res:
                        trades_today += 1
                        runtime = (datetime.now() - start_time).total_seconds() / 3600
                        log(f"Trade #{trades_today} | Bal: ${account.balance:.0f} | Runtime: {runtime:.1f}h")
                        
                        # Stats every 5 trades
                        if trades_today % 5 == 0:
                            log(f"📊 Used margin: ${account.margin:.0f} | Free: ${account.margin_free:.0f} | Level: {account.margin_level:.0f}%")
                else:
                    if DIAGNOSTICS:
                        log(f"Skip: {reason}")
                
                time.sleep(POLL_SECONDS)
                
            except KeyboardInterrupt:
                log("Bot stopped by user")
                break
            except Exception as e:
                log(f"Loop error: {e}")
                time.sleep(POLL_SECONDS)
    
    except Exception as e:
        log(f"FATAL ERROR: {e}")
        log("\nTroubleshooting:")
        log("1. Make sure MT5 desktop is open and logged in")
        log("2. Check XAUUSD is in Market Watch")
        log("3. Verify server name matches MT5")
    
    finally:
        mt5.shutdown()
        log("MT5 connection closed")

if __name__ == "__main__":
    main()

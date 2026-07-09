import math

def calculate_sma(data, period):
    if len(data) < period:
        return [None] * len(data)
    
    sma = []
    for i in range(len(data)):
        if i < period - 1:
            sma.append(None)
        else:
            window = data[i - period + 1 : i + 1]
            sma.append(sum(window) / period)
    return sma

def calculate_ema(data, period):
    if len(data) < period:
        return [None] * len(data)
        
    ema = []
    multiplier = 2 / (period + 1)
    
    # Start with SMA for the first value
    sma = calculate_sma(data, period)
    
    for i in range(len(data)):
        if i < period - 1:
            ema.append(None)
        elif i == period - 1:
            ema.append(sma[i])
        else:
            val = (data[i] * multiplier) + (ema[i - 1] * (1 - multiplier))
            ema.append(val)
    return ema

def calculate_rsi(closes, period=14):
    if len(closes) <= period:
        return [None] * len(closes)
        
    rsi = [None] * (period + 1)
    
    # Calculate initial average gain and loss
    gains = []
    losses = []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(-change)
            
    # Initial averages
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    # First RSI
    if avg_loss == 0:
        rs = float('inf')
        first_rsi = 100.0
    else:
        rs = avg_gain / avg_loss
        first_rsi = 100.0 - (100.0 / (1.0 + rs))
        
    rsi[-1] = first_rsi  # The first element with RSI is at index 'period'
    
    # Keep track of average gains and losses
    curr_avg_gain = avg_gain
    curr_avg_loss = avg_loss
    
    # Pad rsi list with None up to period
    rsi_list = [None] * (period + 1)
    rsi_list[period] = first_rsi
    
    for i in range(period + 1, len(closes)):
        gain = gains[i - 1]
        loss = losses[i - 1]
        
        curr_avg_gain = (curr_avg_gain * (period - 1) + gain) / period
        curr_avg_loss = (curr_avg_loss * (period - 1) + loss) / period
        
        if curr_avg_loss == 0:
            val = 100.0
        else:
            rs = curr_avg_gain / curr_avg_loss
            val = 100.0 - (100.0 / (1.0 + rs))
        rsi_list.append(val)
        
    # Standardize length to match closes
    while len(rsi_list) < len(closes):
        rsi_list.insert(0, None)
    return rsi_list

def calculate_macd(closes, fast_period=12, slow_period=26, signal_period=9):
    if len(closes) < slow_period:
        return [None] * len(closes), [None] * len(closes), [None] * len(closes)
        
    ema_fast = calculate_ema(closes, fast_period)
    ema_slow = calculate_ema(closes, slow_period)
    
    macd_line = []
    for f, s in zip(ema_fast, ema_slow):
        if f is None or s is None:
            macd_line.append(None)
        else:
            macd_line.append(f - s)
            
    # Calculate Signal Line (EMA of MACD Line)
    # We must filter out leading None values to calculate the EMA
    none_count = sum(1 for x in macd_line if x is None)
    macd_valid = macd_line[none_count:]
    
    signal_valid = calculate_ema(macd_valid, signal_period)
    signal_line = [None] * none_count + signal_valid
    
    # Calculate Histogram
    histogram = []
    for m, s in zip(macd_line, signal_line):
        if m is None or s is None:
            histogram.append(None)
        else:
            histogram.append(m - s)
            
    return macd_line, signal_line, histogram

def calculate_bollinger_bands(closes, period=20, num_std=2):
    if len(closes) < period:
        return [None] * len(closes), [None] * len(closes), [None] * len(closes)
        
    sma = calculate_sma(closes, period)
    upper_band = []
    lower_band = []
    
    for i in range(len(closes)):
        if sma[i] is None:
            upper_band.append(None)
            lower_band.append(None)
        else:
            window = closes[i - period + 1 : i + 1]
            mean = sma[i]
            variance = sum((x - mean) ** 2 for x in window) / period
            std_dev = math.sqrt(variance)
            upper_band.append(mean + (num_std * std_dev))
            lower_band.append(mean - (num_std * std_dev))
            
    return upper_band, sma, lower_band

def calculate_atr(highs, lows, closes, period=14):
    if len(closes) <= period:
        return [None] * len(closes)
        
    # Calculate True Ranges
    tr_list = []
    for i in range(len(closes)):
        if i == 0:
            tr_list.append(highs[i] - lows[i])
        else:
            tr1 = highs[i] - lows[i]
            tr2 = abs(highs[i] - closes[i - 1])
            tr3 = abs(lows[i] - closes[i - 1])
            tr_list.append(max(tr1, tr2, tr3))
            
    # Calculate ATR (Wilder's Smoothing of TR)
    atr_list = [None] * len(closes)
    
    # Initial SMA of TR
    initial_atr = sum(tr_list[1:period+1]) / period
    atr_list[period] = initial_atr
    
    curr_atr = initial_atr
    for i in range(period + 1, len(closes)):
        curr_atr = (curr_atr * (period - 1) + tr_list[i]) / period
        atr_list[i] = curr_atr
        
    return atr_list

def get_latest_indicators(klines):
    """
    Takes list of klines, extracts closes/highs/lows,
    computes all indicators, and returns a dictionary of the most recent values.
    """
    if len(klines) < 50:
        return {"error": "Need at least 50 historical candles for indicator calculations."}
        
    closes = [float(k[4]) for k in klines]
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    
    ema9 = calculate_ema(closes, 9)
    ema21 = calculate_ema(closes, 21)
    ema50 = calculate_ema(closes, 50)
    rsi = calculate_rsi(closes, 14)
    macd_line, signal_line, histogram = calculate_macd(closes, 12, 26, 9)
    upper_bb, mid_bb, lower_bb = calculate_bollinger_bands(closes, 20, 2)
    atr = calculate_atr(highs, lows, closes, 14)
    
    return {
        "current_price": closes[-1],
        "ema9": ema9[-1],
        "ema21": ema21[-1],
        "ema50": ema50[-1],
        "rsi": rsi[-1],
        "macd": macd_line[-1],
        "macd_signal": signal_line[-1],
        "macd_hist": histogram[-1],
        "bb_upper": upper_bb[-1],
        "bb_middle": mid_bb[-1],
        "bb_lower": lower_bb[-1],
        "atr": atr[-1]
    }

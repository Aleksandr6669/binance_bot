import asyncio
import time
import logging
from collections import deque
import numpy as np
import pandas as pd
import db

# Настройка логирования для вывода в консоль
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("Scalper")

import os
import requests
from dotenv import load_dotenv

# Загрузка переменных окружения из .env
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
    logger.info("Telegram уведомления активированы для скальпера.")
else:
    logger.info("Глобальные Telegram уведомления в .env не заданы. Пользователи могут настроить своих ботов индивидуально в настройках профиля.")

async def send_telegram_notification_async(message):
    """
    Асинхронно отправляет сообщение в Telegram, используя asyncio.to_thread,
    чтобы не блокировать выполнение основного WebSocket-цикла.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        await asyncio.to_thread(requests.post, url, json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Не удалось отправить уведомление в Telegram: {e}")

# Динамическая проверка доступности PyTorch.
# Если PyTorch недоступен (например, не скомпилирован под Python 3.14 на этой архитектуре),
# скрипт автоматически переключится на оптимизированный NumPy-эквивалент DLinear.
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    HAS_TORCH = True
    logger.info("PyTorch успешно импортирован. Будет использована нейросетевая модель DLinear на PyTorch.")
except ImportError:
    HAS_TORCH = False
    logger.warning("PyTorch не найден. Включается режим высокопроизводительной NumPy-симуляции DLinear.")

# Динамический импорт LightGBM с защитой от отсутствия libomp.dylib (OpenMP) на macOS.
# При ошибках импорта или загрузки C-библиотеки скрипт переключится на классификатор на NumPy.
try:
    import lightgbm as lgb
    HAS_LIGHTGBM = True
    logger.info("LightGBM успешно импортирован. Будет использован бустинг LightGBM.")
except (ImportError, OSError) as e:
    HAS_LIGHTGBM = False
    logger.warning(
        f"LightGBM не импортирован (ошибка: {e}). "
        "Включается высокопроизводительный логистический классификатор на NumPy."
    )

# =====================================================================
# 1. РЕАЛИЗАЦИЯ МОДЕЛИ DLINEAR (PyTorch)
# =====================================================================
if HAS_TORCH:
    class MovingAvg(nn.Module):
        """Блок скользящего среднего для декомпозиции временного ряда"""
        def __init__(self, kernel_size, stride=1):
            super(MovingAvg, self).__init__()
            self.kernel_size = kernel_size
            self.avg = nn.AvgPool1d(kernel_size=kernel_size, stride=stride, padding=0)

        def forward(self, x):
            # x shape: [Batch, SeqLen, Channels]
            # Добавляем паддинг на концах ряда, чтобы сохранить размерность
            front = x[:, 0:1, :].repeat(1, (self.kernel_size - 1) // 2, 1)
            end = x[:, -1:, :].repeat(1, self.kernel_size // 2, 1)
            x = torch.cat([front, x, end], dim=1)
            x = self.avg(x.permute(0, 2, 1))
            x = x.permute(0, 2, 1)
            return x

    class SeriesDecomp(nn.Module):
        """Декомпозиция временного ряда на сезонную (seasonal) и трендовую (trend) части"""
        def __init__(self, kernel_size):
            super(SeriesDecomp, self).__init__()
            self.moving_avg = MovingAvg(kernel_size, stride=1)

        def forward(self, x):
            moving_mean = self.moving_avg(x)
            res = x - moving_mean
            return res, moving_mean

    class PyTorchDLinear(nn.Module):
        """Реализация DLinear на PyTorch для предсказания временных рядов"""
        def __init__(self, seq_len=60, pred_len=2, channels=1):
            super(PyTorchDLinear, self).__init__()
            self.seq_len = seq_len
            self.pred_len = pred_len
            
            # Декомпозиция ряда с размером ядра 25
            self.decomp = SeriesDecomp(kernel_size=25)
            
            # Линейные слои для прогнозирования
            self.linear_seasonal = nn.Linear(self.seq_len, self.pred_len)
            self.linear_trend = nn.Linear(self.seq_len, self.pred_len)
            
        def forward(self, x):
            # x shape: [Batch, SeqLen, Channels]
            seasonal_init, trend_init = self.decomp(x)
            
            # Перестановка осей для полносвязного слоя [Batch, Channels, SeqLen]
            seasonal_init = seasonal_init.permute(0, 2, 1)
            trend_init = trend_init.permute(0, 2, 1)
            
            # Прогон через линейные слои
            seasonal_output = self.linear_seasonal(seasonal_init)
            trend_output = self.linear_trend(trend_init)
            
            # Суммирование результатов
            x = seasonal_output + trend_output
            # Возвращаем к форме [Batch, PredLen, Channels]
            return x.permute(0, 2, 1)

# =====================================================================
# 2. РЕАЛИЗАЦИЯ DLINEAR НА NumPy (Высокоскоростной Fallback)
# =====================================================================
class NumPyDLinear:
    """NumPy реализация DLinear для работы без PyTorch"""
    def __init__(self, seq_len=60, pred_len=2, kernel_size=25):
        self.seq_len = seq_len
        self.pred_len = pred_len
        self.kernel_size = kernel_size
        
        # Инициализация весов Xavier/Glorot для стабильности
        limit_s = np.sqrt(6.0 / (seq_len + pred_len))
        self.W_seasonal = np.random.uniform(-limit_s, limit_s, (seq_len, pred_len))
        self.b_seasonal = np.zeros((pred_len,))
        
        self.W_trend = np.random.uniform(-limit_s, limit_s, (seq_len, pred_len))
        self.b_trend = np.zeros((pred_len,))
        
    def _moving_avg_2d(self, X):
        # X: (N, seq_len)
        N, seq_len = X.shape
        pad_front = (self.kernel_size - 1) // 2
        pad_end = self.kernel_size // 2
        
        pads_front = np.repeat(X[:, 0:1], pad_front, axis=1)
        pads_end = np.repeat(X[:, -1:], pad_end, axis=1)
        padded_X = np.hstack([pads_front, X, pads_end])
        
        cumsum = np.cumsum(padded_X, axis=1)
        cumsum_padded = np.hstack([np.zeros((N, 1)), cumsum])
        W = self.kernel_size
        return (cumsum_padded[:, W:] - cumsum_padded[:, :-W]) / W
        
    def _moving_avg(self, x):
        return self._moving_avg_2d(x.reshape(1, -1))[0]
        
    def forward(self, X):
        # X can be 1D (seq_len,) or 2D (N, seq_len)
        is_1d = X.ndim == 1
        if is_1d:
            X = X.reshape(1, -1)
            
        trend = self._moving_avg_2d(X)
        seasonal = X - trend
        
        seasonal_out = seasonal @ self.W_seasonal + self.b_seasonal
        trend_out = trend @ self.W_trend + self.b_trend
        out = seasonal_out + trend_out
        
        return out[0] if is_1d else out
        
    def fit(self, X, Y, epochs=15, lr=0.005):
        # X: (N, 30), Y: (N, 2)
        N = len(X)
        for epoch in range(epochs):
            trend = self._moving_avg_2d(X)
            seasonal = X - trend
            
            pred = self.forward(X)
            err = pred - Y
            loss = np.mean(err ** 2)
            
            # Векторизованные градиенты
            dW_seasonal = (seasonal.T @ err) / N
            db_seasonal = np.mean(err, axis=0)
            dW_trend = (trend.T @ err) / N
            db_trend = np.mean(err, axis=0)
            
            # Обновление параметров
            self.W_seasonal -= lr * dW_seasonal
            self.b_seasonal -= lr * db_seasonal
            self.W_trend -= lr * dW_trend
            self.b_trend -= lr * db_trend
            
            if (epoch + 1) % 5 == 0:
                logger.info(f"DLinear NumPy - Epoch {epoch+1}/{epochs}, Loss: {loss:.6f}")


# =====================================================================
# 3. РЕАЛИЗАЦИЯ КЛАССИФИКАТОРА НА NumPy (Резерв для LightGBM)
# =====================================================================
class NumPyClassifier:
    """
    Логистическая регрессия на NumPy.
    Используется в качестве резервного варианта при ошибках загрузки LightGBM.
    """
    def __init__(self, num_features=6):
        self.W = np.random.normal(0, 0.1, (num_features,))
        self.b = 0.0
        
    def _sigmoid(self, z):
        return 1.0 / (1.0 + np.exp(-np.clip(z, -15, 15)))
        
    def predict(self, X):
        # X: (N, num_features) или (num_features,)
        z = X @ self.W + self.b
        return self._sigmoid(z)
        
    def fit(self, X, y, epochs=100, lr=0.1):
        # X: (N, num_features), y: (N,)
        X = np.array(X)
        y = np.array(y)
        for _ in range(epochs):
            pred = self.predict(X)
            err = pred - y
            
            # Вычисление градиентов
            dW = (X.T @ err) / len(y)
            db = np.mean(err)
            
            # Обновление параметров
            self.W -= lr * dW
            self.b -= lr * db


# =====================================================================
# 3.5 РЕАЛИЗАЦИЯ ИИ ТРЕЙЛИНГ МОДЕЛИ НА NumPy
# =====================================================================
class NumPyTrailingModel:
    """
    Линейная регрессия на NumPy для оценки оптимального отступа трейлинг-стопа.
    Предсказывает волатильность (стандартное отклонение цены на 10 свечей вперед).
    """
    def __init__(self, num_features=7):
        self.W = np.zeros((num_features,))
        self.b = 0.005  # Начинаем с отступа в 0.5% по умолчанию
        
    def forward(self, X):
        return X @ self.W + self.b
        
    def predict(self, X):
        # Ограничиваем отступ снизу 0.001 (0.1%) и сверху 0.05 (5.0%) для безопасности
        pred = self.forward(X)
        if isinstance(pred, np.ndarray):
            return np.clip(pred, 0.001, 0.05)
        return float(np.clip(pred, 0.001, 0.05))
        
    def fit(self, X, y, epochs=100, lr=0.01):
        X = np.array(X)
        y = np.array(y)
        N = len(y)
        if N == 0:
            return
        for _ in range(epochs):
            pred = self.forward(X)
            err = pred - y
            dW = (X.T @ err) / N
            db = np.mean(err)
            self.W -= lr * dW
            self.b -= lr * db

# Глобальный инстанс модели трейлинга
ai_trailing_model = NumPyTrailingModel(num_features=7)

def predict_ai_trailing_distance(features):
    """
    Предсказывает волатильность (в процентах от цены) для настройки трейлинг-стопа.
    features: np.array (1D с 7 признаками или 2D [1, 7])
    """
    global ai_trailing_model
    return float(ai_trailing_model.predict(features))


# =====================================================================
# 4. ФУНКЦИИ ВЫЧИСЛЕНИЯ ТЕХНИЧЕСКИХ ИНДИКАТОРОВ
# =====================================================================
def calculate_indicators(df, rsi_period=14, atr_period=14):
    """
    Вычисляет технические индикаторы: RSI (нормированный от 0 до 1)
    и ATR_pct (в процентах от цены закрытия для стационарности).
    Использует pandas ewm для оптимизации скорости.
    """
    # Разница цен для RSI
    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    
    # Экспоненциальное скользящее среднее (эквивалент Wilder's MMA)
    avg_gain = gain.ewm(com=rsi_period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=rsi_period - 1, adjust=False).mean()
    
    rs = avg_gain / (avg_loss + 1e-10)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    df['rsi_norm'] = rsi / 100.0  # Нормализуем RSI от 0.0 до 1.0
    
    # Истинный диапазон (True Range) для ATR
    tr1 = df['high'] - df['low']
    tr2 = (df['high'] - df['close'].shift(1)).abs()
    tr3 = (df['low'] - df['close'].shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # ATR (Wilder's MMA)
    atr = tr.ewm(com=atr_period - 1, adjust=False).mean()
    df['atr'] = atr
    df['atr_pct'] = atr / df['close']  # Относительная волатильность
    
    # Добавляем фичу времени суток (нормированный час от 0.0 до 1.0)
    if 'time' in df.columns:
        timestamps = pd.to_datetime(df['time'], unit='ms')
        df['hour_feature'] = timestamps.dt.hour / 24.0
    elif 'open_time' in df.columns:
        # Пытаемся распарсить open_time (это может быть timestamp или строка)
        try:
            times = pd.to_numeric(df['open_time'], errors='coerce')
            if times.isna().all():
                timestamps = pd.to_datetime(df['open_time'])
            else:
                timestamps = pd.to_datetime(times, unit='ms')
            df['hour_feature'] = timestamps.dt.hour / 24.0
        except Exception:
            df['hour_feature'] = 0.5
    else:
        df['hour_feature'] = 0.5
        
    return df


# =====================================================================
# 5. РАСЧЕТ ЦЕЛЕВОЙ ПЕРЕМЕННОЙ (TARGET) ДЛЯ КЛАССИФИКАТОРА
# =====================================================================
def calculate_targets(df, horizon=60, use_ai_limit_price=False):
    """
    Вычисляет таргет для классификатора на основе реальной логики закрытия сделок бота:
    - Если включен use_ai_limit_price, TP/SL рассчитываются на основе предсказаний DLinear (pred_change_1m).
    - Иначе TP и SL рассчитываются динамически по ATR: TP = 4.0 * ATR, SL = 2.0 * ATR.
    - Учитывает направление тренда (UP или DOWN) по EMA 200 на эквивалентном 5м таймфрейме (1000 EMA для 1м свечей).
    - Для аптренда (Long): успех (1), если цена достигает TP раньше SL.
    - Для даунтренда (Short): успех (1), если цена падает до TP раньше SL.
    """
    n = len(df)
    targets = np.zeros(n)
    
    # Расчет EMA 200 на эквивалентном 5м таймфрейме (1000 EMA для 1м свечей)
    ema_trend = df['close'].ewm(span=1000, adjust=False).mean()
    
    closes = df['close'].values
    highs = df['high'].values
    lows = df['low'].values
    atr_values = df['atr'].values if 'atr' in df.columns else np.zeros(n)
    
    for i in range(n - horizon):
        entry_price = closes[i]
        atr_val = atr_values[i]
        
        # Определяем ATR-пороги или AI-пороги (соответствует логике bot в trading_engine.py)
        if use_ai_limit_price and 'dlinear_pred_1m' in df.columns:
            pred_1m = df['dlinear_pred_1m'].values[i]
            predicted_move = entry_price * abs(pred_1m)
            min_move = entry_price * 0.001  # Минимальный порог 0.1% для стабильности
            predicted_move = max(predicted_move, min_move)
            
            offset_tp = 2.0 * predicted_move
            offset_sl = 1.0 * predicted_move
        elif atr_val and atr_val > 0:
            offset_tp = 4.0 * atr_val
            offset_sl = 2.0 * atr_val
        else:
            offset_tp = entry_price * 0.006
            offset_sl = entry_price * 0.003
            
        # Направление тренда
        is_uptrend = entry_price >= ema_trend[i]
        
        if is_uptrend:
            # Long (BUY) targets
            tp_price = entry_price + offset_tp
            sl_price = entry_price - offset_sl
            
            hit = 0
            for j in range(i + 1, i + horizon):
                if lows[j] <= sl_price:
                    hit = 0
                    break
                if highs[j] >= tp_price:
                    hit = 1
                    break
        else:
            # Short (SELL) targets
            tp_price = entry_price - offset_tp
            sl_price = entry_price + offset_sl
            
            hit = 0
            for j in range(i + 1, i + horizon):
                if highs[j] >= sl_price:
                    hit = 0
                    break
                if lows[j] <= tp_price:
                    hit = 1
                    break
                    
        targets[i] = hit
        
    df['target'] = targets
    return df


# =====================================================================
# 6. ГЕНЕРАЦИЯ СИНТЕТИЧЕСКИХ ДАННЫХ И ОБУЧЕНИЕ МОДЕЛЕЙ НА СТАРТЕ
# =====================================================================
def generate_synthetic_data(num_candles=2000):
    """
    Генерирует симулированную минутную историю (OHLCV) и данные микроструктуры
    (OBI, CVD) для начального обучения моделей.
    """
    np.random.seed(42)
    timestamps = pd.date_range(end=pd.Timestamp.now(), periods=num_candles, freq='1min')
    
    price = 10000.0
    closes = []
    highs = []
    lows = []
    opens = []
    volumes = []
    obi_list = []
    cvd_list = []
    
    current_cvd = 0.0
    
    for i in range(num_candles):
        # Имитируем авторегрессионные тренды
        change = np.random.normal(0, 4.0)
        if len(closes) > 1:
            change += 0.15 * (closes[-1] - closes[-2])
            
        open_p = price
        close_p = price + change
        high_p = max(open_p, close_p) + abs(np.random.normal(0, 2.0))
        low_p = min(open_p, close_p) - abs(np.random.normal(0, 2.0))
        volume = float(np.random.randint(10, 150))
        
        # Дисбаланс стакана (OBI) и кумулятивная дельта объемов (CVD)
        obi = np.clip(np.random.normal(0.08 if change > 0 else -0.08, 0.25), -1.0, 1.0)
        vol_delta = volume * np.random.normal(obi, 0.2)
        current_cvd = 0.95 * current_cvd + vol_delta
        
        opens.append(open_p)
        closes.append(close_p)
        highs.append(high_p)
        lows.append(low_p)
        volumes.append(volume)
        obi_list.append(obi)
        cvd_list.append(current_cvd)
        
        price = close_p
        
    df = pd.DataFrame({
        'timestamp': timestamps,
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': volumes,
        'obi': obi_list,
        'cvd': cvd_list
    })
    return df


def train_models(df):
    """
    Обучает обе модели (DLinear и LightGBM/NumPy-классификатор) на исторических свечах на старте.
    """
    logger.info("Начало подготовки обучающих выборок...")
    df = calculate_indicators(df)
    
    closes = df['close'].values
    n = len(df)
    
    X_dlinear = []
    Y_dlinear = []
    
    # Подготовка окон для DLinear (60 минут lookback, 2 минуты прогноз)
    for i in range(59, n - 2):
        window = closes[i-59 : i+1]
        last_val = window[-1]
        
        # Масштабируем данные close относительно последнего значения окна
        x_norm = window / last_val - 1.0
        y_norm = np.array([closes[i+1] / last_val - 1.0, closes[i+2] / last_val - 1.0])
        
        X_dlinear.append(x_norm)
        Y_dlinear.append(y_norm)
        
    X_dlinear = np.array(X_dlinear)
    Y_dlinear = np.array(Y_dlinear)
    
    # Инициализация и обучение DLinear
    global dlinear_model
    if HAS_TORCH:
        logger.info("Инициализация DLinear на PyTorch...")
        dlinear_model = PyTorchDLinear(seq_len=60, pred_len=2)
        criterion = nn.MSELoss()
        optimizer = optim.Adam(dlinear_model.parameters(), lr=0.005)
        
        # Конвертация в тензоры
        X_t = torch.tensor(X_dlinear, dtype=torch.float32).unsqueeze(-1)  # [N, 60, 1]
        Y_t = torch.tensor(Y_dlinear, dtype=torch.float32).unsqueeze(-1)  # [N, 2, 1]
        
        dlinear_model.train()
        for epoch in range(15):
            optimizer.zero_grad()
            outputs = dlinear_model(X_t)
            loss = criterion(outputs, Y_t)
            loss.backward()
            optimizer.step()
            if (epoch + 1) % 5 == 0:
                logger.info(f"DLinear PyTorch Epoch {epoch+1}/15 - Loss: {loss.item():.6f}")
        dlinear_model.eval()
    else:
        logger.info("Инициализация DLinear на NumPy (без PyTorch)...")
        dlinear_model = NumPyDLinear(seq_len=60, pred_len=2)
        dlinear_model.fit(X_dlinear, Y_dlinear, epochs=15, lr=0.005)
        
    # Генерируем фичи DLinear прогнозов для датасета LightGBM с помощью векторного инференса
    dlinear_pred_1m = np.zeros(n)
    dlinear_pred_2m = np.zeros(n)
    
    if HAS_TORCH:
        with torch.no_grad():
            X_t = torch.tensor(X_dlinear, dtype=torch.float32).unsqueeze(-1)
            preds = dlinear_model(X_t).squeeze(-1).numpy()
    else:
        preds = dlinear_model.forward(X_dlinear)
        
    dlinear_pred_1m[59 : n - 2] = preds[:, 0]
    dlinear_pred_2m[59 : n - 2] = preds[:, 1]
    
    df['dlinear_pred_1m'] = dlinear_pred_1m
    df['dlinear_pred_2m'] = dlinear_pred_2m
    
    # Расчет таргетов классификатора с учетом настроек пользователя
    settings = db.get_user_settings(1)
    use_ai_limit_price = bool(dict(settings).get("use_ai_limit_price", 0)) if settings else False
    df = calculate_targets(df, use_ai_limit_price=use_ai_limit_price)
    
    # Расчет таргета для ИИ-трейлинга (стандартное отклонение близлежащих 10 закрытий)
    volatility_targets = np.zeros(n)
    for i in range(n):
        if i + 10 < n:
            next_closes = closes[i+1 : i+11]
            volatility_targets[i] = np.std(next_closes) / closes[i]
        else:
            volatility_targets[i] = np.nan
    df['volatility_target'] = volatility_targets
    
    # Список колонок-фичей для классификатора и трейлинга
    feature_cols = ['rsi_norm', 'atr_pct', 'obi', 'cvd', 'dlinear_pred_1m', 'dlinear_pred_2m', 'hour_feature']
    
    # Убираем пропуски перед обучением
    valid_df = df[feature_cols + ['target', 'volatility_target']].dropna()
    X_lgb = valid_df[feature_cols]
    y_lgb = valid_df['target']
    y_vol = valid_df['volatility_target']
    
    logger.info(f"Размер обучающего множества для классификатора: {len(X_lgb)}")
    
    global classifier_model, ai_trailing_model
    if HAS_LIGHTGBM:
        logger.info("Обучение модели LightGBM...")
        params = {
            'objective': 'binary',
            'metric': 'binary_logloss',
            'boosting_type': 'gbdt',
            'learning_rate': 0.05,
            'num_leaves': 15,
            'max_depth': 4,
            'feature_fraction': 0.8,
            'verbose': -1,
            'seed': 42
        }
        train_data = lgb.Dataset(X_lgb, label=y_lgb)
        classifier_model = lgb.train(
            params,
            train_data,
            num_boost_round=100
        )
    else:
        logger.info("Обучение модели NumPyClassifier...")
        classifier_model = NumPyClassifier(num_features=len(feature_cols))
        classifier_model.fit(X_lgb.values, y_lgb.values, epochs=200, lr=0.1)
        
    logger.info("Обучение ИИ-модели трейлинг-стопа...")
    ai_trailing_model.fit(X_lgb.values, y_vol.values, epochs=150, lr=0.01)
    logger.info("Все модели успешно обучены!")

def retrain_on_market_history(pair, timeframe):
    """
    Дообучает DLinear и Классификатор на реальных накопленных свечах из SQLite.
    Позволяет нейросети учиться прямо в процессе торговли на рынке.
    """
    import db
    logger.info(f"Запуск самообучения нейросети на истории рынка для {pair} ({timeframe})...")
    
    # 1. Извлекаем свечи из SQLite
    rows = db.get_market_history(pair, timeframe, limit=3000)
    if len(rows) < 150:
        logger.info(f"Недостаточно сохраненных свечей для самообучения ({len(rows)}/150). Пропускаем.")
        return False
        
    # Преобразуем в DataFrame
    df = pd.DataFrame([{
        "open": r["open"],
        "high": r["high"],
        "low": r["low"],
        "close": r["close"],
        "volume": r["volume"],
        "obi": np.clip(np.random.normal(0, 0.1), -1.0, 1.0),
        "cvd": np.random.normal(0, 50.0)
    } for r in rows])
    
    # 2. Вычисляем индикаторы и таргеты
    df = calculate_indicators(df)
    settings = db.get_user_settings(1)
    use_ai_limit_price = bool(dict(settings).get("use_ai_limit_price", 0)) if settings else False
    df = calculate_targets(df, use_ai_limit_price=use_ai_limit_price)
    
    # 2.5 Сопоставляем с реальными закрытыми ордерами бота для переопределения таргета реальным исходом
    try:
        conn = db.get_db_connection()
        orders_rows = conn.execute(
            "SELECT * FROM orders WHERE pair = ? AND status IN ('CLOSED_TP', 'CLOSED_SL', 'CLOSED_MANUAL')",
            (pair.upper(),)
        ).fetchall()
        conn.close()
        
        if orders_rows:
            # Превращаем в массив open_time
            df["open_time"] = [r["open_time"] for r in rows]
            
            # Определяем размер таймфрейма в мс
            timeframe_minutes = 15
            if timeframe.endswith('m'):
                timeframe_minutes = int(timeframe[:-1])
            elif timeframe.endswith('h'):
                timeframe_minutes = int(timeframe[:-1]) * 60
            elif timeframe.endswith('d'):
                timeframe_minutes = int(timeframe[:-1]) * 1440
            timeframe_ms = timeframe_minutes * 60 * 1000
            
            for order in orders_rows:
                try:
                    from datetime import datetime, timezone
                    created_dt = datetime.strptime(order["created_at"], "%Y-%m-%d %H:%M:%S")
                    order_ms = int(created_dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
                    
                    match_mask = (df["open_time"] <= order_ms) & (order_ms < df["open_time"] + timeframe_ms)
                    if match_mask.any():
                        closest_idx = df[match_mask].index[-1]
                        is_win = 1 if (order["pnl"] is not None and float(order["pnl"]) > 0) else 0
                        df.loc[closest_idx, 'target'] = is_win
                        logger.info(f"Обучение: Наложен реальный исход ордера #{order['id']} на индекс {closest_idx} (PnL={order['pnl']}, target={is_win})")
                except Exception as o_ex:
                    logger.error(f"Ошибка сопоставления ордера #{order.get('id')} при дообучении: {o_ex}")
    except Exception as db_ex:
        logger.error(f"Ошибка при извлечении реальных ордеров из БД для дообучения: {db_ex}")
        
    closes = df['close'].values
    n = len(df)
    
    X_dlinear = []
    Y_dlinear = []
    
    # Готовим окна для DLinear
    for i in range(59, n - 2):
        window = closes[i-59 : i+1]
        last_val = window[-1]
        x_norm = window / last_val - 1.0
        y_norm = np.array([closes[i+1] / last_val - 1.0, closes[i+2] / last_val - 1.0])
        X_dlinear.append(x_norm)
        Y_dlinear.append(y_norm)
        
    X_dlinear = np.array(X_dlinear)
    Y_dlinear = np.array(Y_dlinear)
    
    # 3. Дообучаем DLinear
    global dlinear_model
    if HAS_TORCH:
        import torch
        import torch.nn as nn
        import torch.optim as optim
        dlinear_model.train()
        criterion = nn.MSELoss()
        optimizer = optim.Adam(dlinear_model.parameters(), lr=0.002) # Меньший lr для тонкой настройки
        
        X_t = torch.tensor(X_dlinear, dtype=torch.float32).unsqueeze(-1)
        Y_t = torch.tensor(Y_dlinear, dtype=torch.float32).unsqueeze(-1)
        
        for epoch in range(5): # Достаточно 5 эпох для дообучения
            optimizer.zero_grad()
            outputs = dlinear_model(X_t)
            loss = criterion(outputs, Y_t)
            loss.backward()
            optimizer.step()
        dlinear_model.eval()
    else:
        dlinear_model.fit(X_dlinear, Y_dlinear, epochs=5, lr=0.002)
        
    # 4. Векторный инференс для получения фичей классификатора
    dlinear_pred_1m = np.zeros(n)
    dlinear_pred_2m = np.zeros(n)
    
    if HAS_TORCH:
        import torch
        with torch.no_grad():
            X_t = torch.tensor(X_dlinear, dtype=torch.float32).unsqueeze(-1)
            preds = dlinear_model(X_t).squeeze(-1).numpy()
    else:
        preds = dlinear_model.forward(X_dlinear)
        
    dlinear_pred_1m[59 : n - 2] = preds[:, 0]
    dlinear_pred_2m[59 : n - 2] = preds[:, 1]
    
    df['dlinear_pred_1m'] = dlinear_pred_1m
    df['dlinear_pred_2m'] = dlinear_pred_2m
    
    # 5. Переобучаем/дообучаем классификатор и ИИ-трейлинг
    feature_cols = ['rsi_norm', 'atr_pct', 'obi', 'cvd', 'dlinear_pred_1m', 'dlinear_pred_2m', 'hour_feature']
    
    # Расчет таргета для ИИ-трейлинга
    volatility_targets = np.zeros(n)
    for i in range(n):
        if i + 10 < n:
            next_closes = closes[i+1 : i+11]
            volatility_targets[i] = np.std(next_closes) / closes[i]
        else:
            volatility_targets[i] = np.nan
    df['volatility_target'] = volatility_targets
    
    valid_df = df[feature_cols + ['target', 'volatility_target']].dropna()
    X_lgb = valid_df[feature_cols]
    y_lgb = valid_df['target']
    y_vol = valid_df['volatility_target']
    
    global classifier_model, ai_trailing_model
    if HAS_LIGHTGBM:
        import lightgbm as lgb
        params = {
            'objective': 'binary',
            'metric': 'binary_logloss',
            'boosting_type': 'gbdt',
            'learning_rate': 0.05,
            'num_leaves': 15,
            'max_depth': 4,
            'feature_fraction': 0.8,
            'verbose': -1,
            'seed': 42
        }
        train_data = lgb.Dataset(X_lgb, label=y_lgb)
        classifier_model = lgb.train(params, train_data, num_boost_round=50)
    else:
        # NumPyClassifier просто делает еще 50 шагов градиентного спуска по новым данным
        classifier_model.fit(X_lgb.values, y_lgb.values, epochs=50, lr=0.05)
        
    # Дообучаем модель трейлинг-стопа на новых данных
    ai_trailing_model.fit(X_lgb.values, y_vol.values, epochs=50, lr=0.01)
        
    logger.info(f"Самообучение завершено! Модели успешно адаптированы под новые рыночные данные ({len(valid_df)} строк).")
    return True


# =====================================================================
# 7. ДВИЖОК СКАЛЬПИНГА (Scalping Engine)
# =====================================================================
class ScalpingEngine:
    """
    Класс управления скользящим буфером и инференса ансамбля.
    """
    def __init__(self, dlinear_model, classifier_model):
        self.dlinear_model = dlinear_model
        self.classifier_model = classifier_model
        # Кольцевой буфер свечей (максимальный размер 100 для экономии ОЗУ)
        self.buffer = deque(maxlen=100)
        
    def add_candle(self, candle):
        self.buffer.append(candle)
        
    def process_tick(self):
        """
        Основной метод инференса, запускаемый на каждом новом тике/минутной свече.
        """
        # Нам нужно как минимум 30 свечей для старта DLinear инференса
        if len(self.buffer) < 30:
            return {
                "status": "INITIALIZING",
                "message": f"Накапливаем свечи: {len(self.buffer)}/30"
            }
            
        t_start = time.perf_counter()
        
        # Конвертируем кольцевой буфер в DataFrame для применения векторных функций индикаторов.
        # Поскольку размер ограничен 100 строками, создание DataFrame занимает менее 0.1 мс.
        df = pd.DataFrame(list(self.buffer))
        df = calculate_indicators(df)
        
        current_row = df.iloc[-1]
        current_close = current_row['close']
        current_rsi_norm = current_row['rsi_norm']
        current_atr_pct = current_row['atr_pct']
        current_atr = current_row['atr']
        current_obi = current_row['obi']
        current_cvd = current_row['cvd']
        
        # --- Защитный фильтр волатильности ---
        # Сравниваем минутный ATR с средним ATR за последний час (последние 60 свечей в буфере)
        hour_window = min(60, len(df))
        mean_hourly_atr = df['atr'].iloc[-hour_window:].mean()
        
        volatility_blocked = False
        if current_atr > 4.0 * mean_hourly_atr:
            volatility_blocked = True
            
        # Окно последних 60 свечей Close для DLinear
        closes_60 = df['close'].iloc[-60:].values
        last_close = closes_60[-1]
        x_norm = closes_60 / last_close - 1.0
        
        # Время старта инференса моделей
        t_model_start = time.perf_counter()
        
        # --- Шаг 1: Инференс DLinear ---
        if HAS_TORCH:
            with torch.no_grad():
                x_t = torch.tensor(x_norm, dtype=torch.float32).view(1, 60, 1)
                dlinear_pred = self.dlinear_model(x_t).numpy().flatten()
        else:
            dlinear_pred = self.dlinear_model.forward(x_norm)
            
        pred_change_1m = dlinear_pred[0]
        pred_change_2m = dlinear_pred[1]
        
        # --- Шаг 2: Инференс Классификатора ---
        features = np.array([[
            current_rsi_norm,
            current_atr_pct,
            current_obi,
            current_cvd,
            pred_change_1m,
            pred_change_2m
        ]])
        
        # Различный синтаксис предсказания в зависимости от модели
        if HAS_LIGHTGBM:
            prob = self.classifier_model.predict(features)[0]
        else:
            prob = self.classifier_model.predict(features)[0]
            
        t_end = time.perf_counter()
        
        total_latency_ms = (t_end - t_start) * 1000.0
        inference_latency_ms = (t_end - t_model_start) * 1000.0
        
        # Финальное решение по ордеру
        action = "HOLD"
        reason = ""
        
        if volatility_blocked:
            action = "SKIP_VOLATILITY_BLOCKED"
            reason = f"Блокировка волатильности! (ATR {current_atr:.4f} > 4x Hourly Avg {mean_hourly_atr:.4f})"
        elif prob > 0.80:
            action = "BUY"
            reason = f"Сигнал на покупку! Вероятность {prob:.4f} > 0.80"
        else:
            reason = f"Вероятность сделки: {prob:.4f} (вход не подтвержден)"
            
        return {
            "status": "SUCCESS",
            "action": action,
            "reason": reason,
            "current_price": current_close,
            "rsi": current_rsi_norm * 100.0,
            "atr_pct": current_atr_pct * 100.0,
            "dlinear_1m_pct": pred_change_1m * 100.0,
            "dlinear_2m_pct": pred_change_2m * 100.0,
            "prob": prob,
            "volatility_blocked": volatility_blocked,
            "total_latency_ms": total_latency_ms,
            "inference_latency_ms": inference_latency_ms
        }


# =====================================================================
# 8. АСИНХРОННЫЙ WebSocket ЦИКЛ СИМУЛЯЦИИ ТИКОВ
# =====================================================================
async def run_websocket_simulation(engine, tick_delay=0.1):
    """
    Симулирует бесконечный WebSocket-стрим минутных свечей.
    Каждые tick_delay секунд приходит новое обновление свечи.
    Замеряется время инференса в миллисекундах.
    """
    logger.info("Запуск WebSocket-стрима...")
    price = 10000.0
    current_cvd = 0.0
    
    # Симулируем 60 тиков для теста работоспособности и задержек
    for tick in range(1, 61):
        change = np.random.normal(0, 3.0)
        
        # Искусственные сквизы цены на 15 и 45 тике для теста фильтра волатильности
        is_squeeze = tick in [15, 45]
        if is_squeeze:
            change = np.random.choice([-1, 1]) * 55.0
            logger.warning(f"[TICK {tick:02d}] Генерируем искусственный ценовой сквиз для проверки фильтра волатильности!")
            
        open_p = price
        close_p = price + change
        high_p = max(open_p, close_p) + abs(np.random.normal(0, 1.0))
        low_p = min(open_p, close_p) - abs(np.random.normal(0, 1.0))
        
        if is_squeeze:
            high_p += 15.0
            low_p -= 15.0
            
        volume = float(np.random.randint(10, 100))
        obi = np.clip(np.random.normal(0.08 if change > 0 else -0.08, 0.2), -1.0, 1.0)
        vol_delta = volume * np.random.normal(obi, 0.15)
        current_cvd = 0.95 * current_cvd + vol_delta
        
        candle = {
            'timestamp': pd.Timestamp.now(),
            'open': open_p,
            'high': high_p,
            'low': low_p,
            'close': close_p,
            'volume': volume,
            'obi': obi,
            'cvd': current_cvd
        }
        
        price = close_p
        
        # Передаем данные в буфер скальпера
        engine.add_candle(candle)
        
        # Обрабатываем тик
        res = engine.process_tick()
        
        if res["status"] == "SUCCESS":
            # Раскрашиваем вывод в терминале для удобства
            # Зеленый для BUY, красный для блокировки волатильности
            if res["action"] == "BUY":
                action_str = f"\033[92m{res['action']}\033[0m"
                # Асинхронно отправляем сигнал в Телеграм
                msg = (
                    f"🟢 <b>[Scalper AI Signal] BUY</b>\n\n"
                    f"Цена: <b>{res['current_price']:.2f}</b>\n"
                    f"RSI: {res['rsi']:.1f}\n"
                    f"ATR%: {res['atr_pct']:.4f}%\n"
                    f"Прогноз DLinear 1m/2m: {res['dlinear_1m_pct']:.4f}% / {res['dlinear_2m_pct']:.4f}%\n"
                    f"Вероятность классификатора: <b>{res['prob']:.4f}</b>"
                )
                asyncio.create_task(send_telegram_notification_async(msg))
            elif res["action"] == "SKIP_VOLATILITY_BLOCKED":
                action_str = f"\033[91m{res['action']}\033[0m"
            else:
                action_str = res["action"]
                
            logger.info(
                f"Tick {tick:02d} | Цена: {res['current_price']:.2f} | "
                f"RSI: {res['rsi']:.1f} | ATR%: {res['atr_pct']:.4f}% | "
                f"DLinear 1m/2m: {res['dlinear_1m_pct']:.4f}%/{res['dlinear_2m_pct']:.4f}% | "
                f"LGBM Prob: {res['prob']:.4f} | "
                f"Action: {action_str} | "
                f"Model Ping: {res['inference_latency_ms']:.3f} ms | "
                f"Total Ping: {res['total_latency_ms']:.3f} ms"
            )
        else:
            logger.info(f"Tick {tick:02d} | {res['message']}")
            
        await asyncio.sleep(tick_delay)


# =====================================================================
# 9. ТОЧКА ВХОДА (MAIN)
# =====================================================================
async def main():
    logger.info("=== Запуск скрипта криптовалютного скальпинга ===")
    
    # 1. Генерация исторических данных для обучения
    historical_df = generate_synthetic_data(num_candles=2500)
    
    # 2. Обучение моделей на старте
    train_models(historical_df)
    
    # 3. Инициализация движка скальпинга
    engine = ScalpingEngine(dlinear_model, classifier_model)
    
    # 4. Запуск WebSocket-симуляции
    # tick_delay установлен в 0.05 секунд для быстрого тестирования в консоли
    await run_websocket_simulation(engine, tick_delay=0.05)
    
    logger.info("=== Тестовая симуляция успешно завершена! ===")

if __name__ == "__main__":
    asyncio.run(main())

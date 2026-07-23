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

async def send_notification_async(message):
    """
    Выводит уведомление в логгер (логирование событий терминала).
    """
    clean_msg = message.replace("<b>", "").replace("</b>", "").replace("🟢", "").replace("🔴", "").replace("🔵", "").replace("⚠️", "").replace("🚀", "")
    logger.info(f"[NOTIFICATION] {clean_msg.strip()}")

# Совместимость со старыми вызовами
send_notification_async = send_notification_async

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
            self.last_loss = float(loss)
            
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
        self.mean = None
        self.std = None
        
    def _sigmoid(self, z):
        return 1.0 / (1.0 + np.exp(-np.clip(z, -15, 15)))
        
    def predict(self, X):
        # X: (N, num_features) или (num_features,)
        X = np.array(X)
        if self.mean is not None and self.std is not None:
            X_scaled = (X - self.mean) / self.std
        else:
            X_scaled = X
        z = X_scaled @ self.W + self.b
        return self._sigmoid(z)
        
    def fit(self, X, y, epochs=100, lr=0.1):
        # X: (N, num_features), y: (N,)
        X = np.array(X)
        y = np.array(y)
        self.mean = np.mean(X, axis=0)
        self.std = np.std(X, axis=0) + 1e-8
        X_scaled = (X - self.mean) / self.std
        
        for _ in range(epochs):
            pred = self._sigmoid(X_scaled @ self.W + self.b)
            err = pred - y
            
            # Вычисление градиентов
            dW = (X_scaled.T @ err) / len(y)
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
        self.mean = None
        self.std = None
        
    def forward(self, X):
        X = np.array(X)
        if self.mean is not None and self.std is not None:
            X_scaled = (X - self.mean) / self.std
        else:
            X_scaled = X
        return X_scaled @ self.W + self.b
        
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
        self.mean = np.mean(X, axis=0)
        self.std = np.std(X, axis=0) + 1e-8
        X_scaled = (X - self.mean) / self.std
        
        for _ in range(epochs):
            pred = X_scaled @ self.W + self.b
            err = pred - y
            dW = (X_scaled.T @ err) / N
            db = np.mean(err)
            self.W -= lr * dW
            self.b -= lr * db

# Глобальные инстанции моделей
dlinear_model = None
classifier_model = None
ai_trailing_model = NumPyTrailingModel(num_features=9)
current_model_pair = None
current_model_timeframe = None

training_status = {
    "active": False,
    "pair": "",
    "timeframe": "",
    "started_at": 0.0
}

def predict_ai_trailing_distance(features):
    """
    Предсказывает волатильность (в процентах от цены) для настройки трейлинг-стопа.
    features: np.array (1D с 9 признаками или 2D [1, 9])
    """
    global ai_trailing_model
    return float(ai_trailing_model.predict(features))

import pickle
import os

def save_models_to_disk(pair, timeframe):
    """Сохраняет обученные веса DLinear, классификатора, трейлинга и всю связанную историю из БД в pkl файл."""
    global dlinear_model, classifier_model, ai_trailing_model
    try:
        os.makedirs("models", exist_ok=True)
        filepath = f"models/{pair.upper()}_{timeframe}.pkl"
        
        # Загружаем связанные данные из SQLite для этой пары
        orders = []
        analysis_logs = []
        market_candles = []
        try:
            import sqlite3
            db_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trading_bot.db")
            if os.path.exists(db_file):
                conn = sqlite3.connect(db_file)
                conn.row_factory = sqlite3.Row
                orders = [dict(row) for row in conn.execute("SELECT * FROM orders WHERE pair = ?", (pair.upper(),)).fetchall()]
                analysis_logs = [dict(row) for row in conn.execute("SELECT * FROM analysis_logs WHERE pair = ?", (pair.upper(),)).fetchall()]
                market_candles = [dict(row) for row in conn.execute("SELECT * FROM market_candles WHERE pair = ?", (pair.upper(),)).fetchall()]
                conn.close()
        except Exception as db_ex:
            logger.warning(f"Не удалось загрузить историю из БД для экспорта: {db_ex}")

        last_loss = float(getattr(dlinear_model, "last_loss", 0.000016)) if dlinear_model is not None else 0.000016
        data = {
            "dlinear": dlinear_model,
            "classifier": classifier_model,
            "trailing": ai_trailing_model,
            "loss": last_loss,
            "db_orders": orders,
            "db_analysis_logs": analysis_logs,
            "db_market_candles": market_candles
        }
        with open(filepath, "wb") as f:
            pickle.dump(data, f)
            
        # Write fast JSON sidecar metadata file for instant UI loading
        try:
            import json
            clf_name = type(classifier_model).__name__ if classifier_model is not None else ""
            if "Booster" in clf_name or "lightgbm" in str(type(classifier_model)).lower():
                classifier_type = "LightGBM (Gradient Boosting)"
            else:
                classifier_type = "NumPy Classifier"

            stat = os.stat(filepath)
            mtime = datetime.datetime.fromtimestamp(stat.st_mtime).astimezone().strftime("%Y-%m-%d %H:%M:%S")
            size_mb = round(stat.st_size / (1024 * 1024), 2)

            meta_filepath = f"models/{pair.upper()}_{timeframe}.meta.json"
            meta = {
                "pair": pair.upper(),
                "timeframe": timeframe,
                "classifier_type": classifier_type,
                "candles_count": len(market_candles),
                "feedback_count": len(analysis_logs),
                "loss": last_loss,
                "mtime": mtime,
                "size_mb": size_mb
            }
            with open(meta_filepath, "w", encoding="utf-8") as f_meta:
                json.dump(meta, f_meta, ensure_ascii=False, indent=2)
        except Exception as meta_ex:
            logger.warning(f"Failed to write meta.json sidecar: {meta_ex}")

        logger.info(f"Модели и история для {pair} ({timeframe}) успешно сохранены на диск: {filepath}")
        return True
    except Exception as e:
        logger.error(f"Ошибка сохранения моделей на диск: {e}")
        return False

def load_models_from_disk(pair, timeframe):
    """Загружает веса из pkl файла и импортирует упакованную историю обратно в SQLite базу данных."""
    global dlinear_model, classifier_model, ai_trailing_model, current_model_pair, current_model_timeframe
    try:
        filepath = f"models/{pair.upper()}_{timeframe}.pkl"
        if not os.path.exists(filepath):
            return False
        with open(filepath, "rb") as f:
            data = pickle.load(f)
        
        # Обновляем глобальные инстанции моделей
        dlinear_model = data["dlinear"]
        classifier_model = data["classifier"]
        ai_trailing_model = data["trailing"]
        
        current_model_pair = pair.upper()
        current_model_timeframe = timeframe
        
        # Импортируем историю в базу данных SQLite
        try:
            import sqlite3
            db_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trading_bot.db")
            conn = sqlite3.connect(db_file)
            
            # Импортируем ордера
            if "db_orders" in data and data["db_orders"]:
                for o in data["db_orders"]:
                    columns = ", ".join(o.keys())
                    placeholders = ", ".join("?" for _ in o)
                    conn.execute(
                        f"INSERT OR IGNORE INTO orders ({columns}) VALUES ({placeholders})", 
                        tuple(o.values())
                    )
            
            # Импортируем логи анализа ИИ
            if "db_analysis_logs" in data and data["db_analysis_logs"]:
                for l in data["db_analysis_logs"]:
                    columns = ", ".join(l.keys())
                    placeholders = ", ".join("?" for _ in l)
                    conn.execute(
                        f"INSERT OR IGNORE INTO analysis_logs ({columns}) VALUES ({placeholders})", 
                        tuple(l.values())
                    )
            
            # Импортируем свечи
            if "db_market_candles" in data and data["db_market_candles"]:
                for c in data["db_market_candles"]:
                    columns = ", ".join(c.keys())
                    placeholders = ", ".join("?" for _ in c)
                    conn.execute(
                        f"INSERT OR IGNORE INTO market_candles ({columns}) VALUES ({placeholders})", 
                        tuple(c.values())
                    )
            
            conn.commit()
            conn.close()
            
            # Синхронизация облачного хранилища HuggingFace
            try:
                import db
                db.upload_db_to_hf_async()
            except:
                pass
                
            logger.info(f"Исторические сделки, логи ИИ и свечи успешно импортированы в базу данных.")
        except Exception as db_ex:
            logger.warning(f"Ошибка импорта сопутствующей истории из pkl в БД: {db_ex}")
            
        # Если подключен LightGBM, но из pkl загрузился старый NumPyClassifier — автоматически обновляем до LightGBM
        if HAS_LIGHTGBM and isinstance(classifier_model, NumPyClassifier):
            logger.info(f"Обнаружен устаревший NumPyClassifier для {pair} ({timeframe}) при активном LightGBM. Автоматически обновляем модель до LightGBM...")
            retrain_on_market_history(pair, timeframe)

        logger.info(f"Модели для {pair} ({timeframe}) успешно загружены с диска!")
        return True
    except Exception as e:
        logger.error(f"Ошибка загрузки моделей с диска: {e}")
        return False

def get_models_metadata_list():
    """
    Возвращает список метаданных всех сохраненных моделей в папке models/.
    Использует сверхбыстрые .meta.json файлы для мгновенной отклика интерфейса (0ms).
    """
    import os, datetime, pickle, json
    models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
    if not os.path.exists(models_dir):
        return []
    
    result = []
    files = [f for f in os.listdir(models_dir) if f.endswith(".pkl")]
    files.sort()
    
    for filename in files:
        filepath = os.path.join(models_dir, filename)
        name_no_ext = filename[:-4]
        meta_filepath = os.path.join(models_dir, f"{name_no_ext}.meta.json")
        
        parts = name_no_ext.split("_")
        pair = parts[0].upper() if len(parts) > 0 else "UNKNOWN"
        timeframe = parts[1] if len(parts) > 1 else "1m"
        
        # 1. Попытка прочитать готовый мелкий JSON файл (мгновенно)
        if os.path.exists(meta_filepath):
            try:
                with open(meta_filepath, "r", encoding="utf-8") as f_meta:
                    meta = json.load(f_meta)
                    meta["filename"] = filename
                    meta["filepath"] = filepath
                    result.append(meta)
                    continue
            except Exception:
                pass
        
        # 2. Фолбэк на замер pickle (только при первом запуске без json)
        try:
            stat = os.stat(filepath)
            mtime = datetime.datetime.fromtimestamp(stat.st_mtime).astimezone().strftime("%Y-%m-%d %H:%M:%S")
            size_mb = round(stat.st_size / (1024 * 1024), 2)
        except Exception:
            mtime = "—"
            size_mb = 0.0
        
        candles_count = 0
        feedback_count = 0
        classifier_type = "NumPy Classifier"
        loss_val = 0.000016
        
        try:
            with open(filepath, "rb") as f:
                data = pickle.load(f)
                candles_count = len(data.get("db_market_candles", []))
                feedback_count = len(data.get("db_analysis_logs", []))
                clf = data.get("classifier")
                dl = data.get("dlinear")
                
                if clf is not None:
                    clf_name = type(clf).__name__
                    if "Booster" in clf_name or "lightgbm" in str(type(clf)).lower():
                        classifier_type = "LightGBM (Gradient Boosting)"
                    else:
                        classifier_type = "NumPy Classifier"
                
                if "loss" in data and data["loss"] is not None:
                    loss_val = float(data["loss"])
                elif dl is not None and hasattr(dl, "last_loss"):
                    loss_val = float(dl.last_loss)
                    
                # Создаем meta.json для последующих мгновенных загрузок
                try:
                    meta_to_write = {
                        "pair": pair,
                        "timeframe": timeframe,
                        "classifier_type": classifier_type,
                        "candles_count": candles_count,
                        "feedback_count": feedback_count,
                        "loss": loss_val,
                        "mtime": mtime,
                        "size_mb": size_mb
                    }
                    with open(meta_filepath, "w", encoding="utf-8") as f_meta:
                        json.dump(meta_to_write, f_meta, ensure_ascii=False, indent=2)
                except Exception:
                    pass
        except Exception:
            pass
            
        result.append({
            "filename": filename,
            "pair": pair,
            "timeframe": timeframe,
            "classifier_type": classifier_type,
            "candles_count": candles_count,
            "feedback_count": feedback_count,
            "loss": loss_val,
            "mtime": mtime,
            "size_mb": size_mb,
            "filepath": filepath
        })
        
    return result

def delete_model_file(pair, timeframe):
    """Удаляет файл модели (.pkl и .meta.json) с диска."""
    try:
        filename = f"models/{pair.upper()}_{timeframe}.pkl"
        filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        meta_filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"models/{pair.upper()}_{timeframe}.meta.json")
        
        deleted = False
        if os.path.exists(filepath):
            os.remove(filepath)
            deleted = True
        if os.path.exists(meta_filepath):
            os.remove(meta_filepath)
            
        if deleted:
            logger.info(f"Файл модели {filename} успешно удален.")
            return True
        return False
    except Exception as e:
        logger.error(f"Ошибка удаления файла модели {pair} ({timeframe}): {e}")
        return False


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
        
    # 1. Расчет VWAP и нормализованного отклонения цены от него (vwap_dist)
    try:
        typical_price = (df['high'] + df['low'] + df['close']) / 3.0
        cum_vol_price = (typical_price * df['volume']).cumsum()
        cum_vol = df['volume'].cumsum()
        vwap = cum_vol_price / (cum_vol + 1e-10)
        df['vwap_dist'] = (df['close'] - vwap) / (vwap + 1e-10)
    except Exception:
        df['vwap_dist'] = 0.0

    # 2. Расчет MACD Histogram и нормализация по цене (macd_hist_norm)
    try:
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = macd_line - signal_line
        df['macd_hist_norm'] = macd_hist / (df['close'] + 1e-10)
    except Exception:
        df['macd_hist_norm'] = 0.0
        
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
    # 0. Попытка загрузить веса с диска перед обучением
    settings = db.get_settings()
    pair = (dict(settings).get("trading_pair", "BTCUSDT") if settings else "BTCUSDT").upper()
    tf = (dict(settings).get("timeframe", "3m") if settings else "3m")
    
    if load_models_from_disk(pair, tf):
        logger.info(f"Модели для {pair} ({tf}) найдены на диске. Пропускаем этап первичного обучения.")
        return
        
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
        dlinear_model.last_loss = float(loss.item())
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
    settings = db.get_settings()
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
    feature_cols = [
        'rsi_norm', 'atr_pct', 'obi', 'cvd', 'dlinear_pred_1m', 'dlinear_pred_2m', 'hour_feature',
        'vwap_dist', 'macd_hist_norm'
    ]
    
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
    # Сохраняем веса на диск
    save_models_to_disk(pair, tf)
    
    global current_model_pair, current_model_timeframe
    current_model_pair = pair.upper()
    current_model_timeframe = tf

def fetch_binance_klines_with_start(symbol, timeframe, start_time, limit=100, market_type="SPOT"):
    import requests
    import os
    import trading_engine
    symbol = symbol.upper()
    market_type = market_type.upper()
    use_us = os.environ.get("USE_BINANCE_US", "False").lower() == "true"
    url = "https://fapi.binance.com/fapi/v1/klines" if market_type == "FUTURES" else (
        "https://api.binance.us/api/v3/klines" if use_us else "https://api.binance.com/api/v3/klines"
    )
    params = {
        "symbol": symbol,
        "interval": timeframe,
        "startTime": start_time,
        "limit": limit
    }
    try:
        res = requests.get(url, params=params, timeout=10, proxies=trading_engine.get_binance_proxies())
        res.raise_for_status()
        return res.json()
    except Exception as e:
        logger.warning(f"Error fetching klines with start_time={start_time}: {e}")
        return []

def adapt_models_to_closed_orders(pair=None, timeframe=None):
    """
    Алиас для тонкого дообучения (RL) нейросети на реальных закрытых ордерах и истории логов.
    """
    import db
    settings = db.get_settings()
    if not pair:
        pair = (dict(settings).get("trading_pair", "SOLUSDC") if settings else "SOLUSDC").upper()
    if not timeframe:
        timeframe = dict(settings).get("timeframe", "1m") if settings else "1m"
    return retrain_on_market_history(pair, timeframe)

def retrain_on_market_history(pair, timeframe):
    """
    Дообучает DLinear и Классификатор на реальных накопленных свечах из SQLite.
    Позволяет нейросети учиться прямо в процессе торговли на рынке.
    """
    global training_status
    training_status = {
        "active": True,
        "pair": pair.upper(),
        "timeframe": timeframe,
        "started_at": time.time()
    }
    try:
        return _retrain_on_market_history_inner(pair, timeframe)
    finally:
        training_status["active"] = False

def _retrain_on_market_history_inner(pair, timeframe):
    import db
    import trading_engine
    logger.info(f"Запуск самообучения нейросети на истории рынка для {pair} ({timeframe})...")
    
    # Расчет длительности таймфрейма в миллисекундах для точной синхронизации свечей, ордеров и логов
    timeframe_minutes = 15
    if timeframe.endswith('m'):
        timeframe_minutes = int(timeframe[:-1])
    elif timeframe.endswith('h'):
        timeframe_minutes = int(timeframe[:-1]) * 60
    elif timeframe.endswith('d'):
        timeframe_minutes = int(timeframe[:-1]) * 1440
    timeframe_ms = timeframe_minutes * 60 * 1000
    
    # 1. Извлекаем свечи с Binance
    try:
        raw_klines = trading_engine.fetch_binance_klines(pair, timeframe, limit=1000)
    except Exception as e:
        logger.error(f"Ошибка получения истории рынка для дообучения: {e}")
        return False
        
    if not raw_klines:
        logger.info("Не удалось получить свечи с Binance. Пропускаем.")
        return False

    # Преобразуем в словарь для дедупликации
    candles_dict = {
        int(k[0]): {
            "open_time": int(k[0]),
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
            "obi": np.clip(np.random.normal(0, 0.1), -1.0, 1.0),
            "cvd": np.random.normal(0, 50.0)
        } for k in raw_klines
    }

    # Подгружаем исторические свечи из локальной БД для расширения периода
    try:
        conn = db.get_db_connection()
        db_candles = conn.execute(
            "SELECT open_time, open, high, low, close, volume FROM market_candles WHERE pair = ? AND timeframe = ? GROUP BY open_time ORDER BY open_time DESC LIMIT 10000",
            (pair.upper(), timeframe)
        ).fetchall()
        conn.close()
        for c in db_candles:
            ot = int(c["open_time"])
            if ot not in candles_dict:
                candles_dict[ot] = {
                    "open_time": ot,
                    "open": float(c["open"]),
                    "high": float(c["high"]),
                    "low": float(c["low"]),
                    "close": float(c["close"]),
                    "volume": float(c["volume"]),
                    "obi": np.clip(np.random.normal(0, 0.1), -1.0, 1.0),
                    "cvd": np.random.normal(0, 50.0)
                }
    except Exception as db_ex:
        logger.warning(f"Не удалось прочитать исторические свечи из БД: {db_ex}")

    if len(candles_dict) < 150:
        logger.info(f"Недостаточно свечей для самообучения ({len(candles_dict)}/150). Пропускаем.")
        return False

    # 2. Скачиваем недостающие свечи с Binance для исторических ордеров, если они выходят за пределы загруженного периода
    try:
        conn = db.get_db_connection()
        orders_rows = conn.execute(
            "SELECT * FROM orders WHERE pair = ? AND (timeframe = ? OR timeframe IS NULL) AND status IN ('CLOSED_TP', 'CLOSED_SL', 'CLOSED_MANUAL')",
            (pair.upper(), timeframe)
        ).fetchall()
        conn.close()
        
        if orders_rows:
            missing_starts = []
            for order in orders_rows:
                try:
                    from datetime import datetime, timezone
                    created_dt = datetime.strptime(order["created_at"], "%Y-%m-%d %H:%M:%S")
                    order_ms = int(created_dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
                    
                    has_candle = False
                    for ot in list(candles_dict.keys()):
                        if ot <= order_ms < ot + timeframe_ms:
                            has_candle = True
                            break
                    if not has_candle:
                        # Нам нужны свечи начиная с order_ms - 20 * timeframe_ms
                        missing_starts.append(order_ms - 20 * timeframe_ms)
                except:
                    pass
            
            if missing_starts:
                logger.info(f"Найдено {len(missing_starts)} ордеров вне загруженного диапазона свечей. Догружаем историю с Binance...")
                settings_data = db.get_settings()
                market_type = dict(settings_data).get("market_type", "SPOT") if settings_data else "SPOT"
                for start_t in missing_starts[:15]: # Лимитируем до 15 запросов
                    extra_klines = fetch_binance_klines_with_start(pair, timeframe, start_t, limit=100, market_type=market_type)
                    if extra_klines:
                        for k in extra_klines:
                            ot = int(k[0])
                            if ot not in candles_dict:
                                candles_dict[ot] = {
                                    "open_time": ot,
                                    "open": float(k[1]),
                                    "high": float(k[2]),
                                    "low": float(k[3]),
                                    "close": float(k[4]),
                                    "volume": float(k[5]),
                                    "obi": np.clip(np.random.normal(0, 0.1), -1.0, 1.0),
                                    "cvd": np.random.normal(0, 50.0)
                                }
                        try:
                            c_conn = db.get_db_connection()
                            for k in extra_klines:
                                c_conn.execute(
                                    "INSERT OR IGNORE INTO market_candles (pair, timeframe, open_time, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                    (pair.upper(), timeframe, int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]))
                                )
                            c_conn.commit()
                            c_conn.close()
                        except Exception as db_wr_ex:
                            logger.warning(f"Не удалось записать догруженные свечи в БД: {db_wr_ex}")
    except Exception as db_ex:
        logger.warning(f"Не удалось проверить недостающие свечи для ордеров: {db_ex}")

    # Сортируем хронологически и создаем DataFrame
    sorted_times = sorted(candles_dict.keys())
    df = pd.DataFrame([candles_dict[t] for t in sorted_times])
    df['time'] = df['open_time']
    
    df = calculate_indicators(df)
    settings = db.get_settings()
    use_ai_limit_price = bool(dict(settings).get("use_ai_limit_price", 0)) if settings else False
    df = calculate_targets(df, use_ai_limit_price=use_ai_limit_price)
    
    # 2.5 Сопоставляем с реальными закрытыми ордерами бота для переопределения таргета реальным исходом
    try:
        conn = db.get_db_connection()
        orders_rows = conn.execute(
            "SELECT * FROM orders WHERE pair = ? AND (timeframe = ? OR timeframe IS NULL) AND status IN ('CLOSED_TP', 'CLOSED_SL', 'CLOSED_MANUAL')",
            (pair.upper(), timeframe)
        ).fetchall()
        conn.close()
        
        if orders_rows:
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
    feature_cols = [
        'rsi_norm', 'atr_pct', 'obi', 'cvd', 'dlinear_pred_1m', 'dlinear_pred_2m', 'hour_feature',
        'vwap_dist', 'macd_hist_norm'
    ]
    
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

    # --- REINFORCEMENT LEARNING FEEDBACK LOOP ---
    # Обучаем классификатор на собственных логах и сделках
    try:
        import sqlite3
        db_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trading_bot.db")
        if os.path.exists(db_file):
            conn = sqlite3.connect(db_file)
            conn.row_factory = sqlite3.Row
            
            # 1. Загружаем историю закрытых сделок (ордеров)
            db_orders = conn.execute(
                "SELECT * FROM orders WHERE status LIKE 'CLOSED_%' AND pair = ? AND (timeframe = ? OR timeframe IS NULL) ORDER BY created_at DESC LIMIT 1000", 
                (pair.upper(), timeframe)
            ).fetchall()
            
            # 2. Загружаем историю логируемых HOLD-сигналов
            db_logs = conn.execute(
                "SELECT * FROM analysis_logs WHERE pair = ? AND stage3_output LIKE '%\"action\": \"HOLD\"%' ORDER BY created_at DESC LIMIT 5000", 
                (pair.upper(),)
            ).fetchall()
            conn.close()
            
            extra_X = []
            extra_y = []
            
            # Обработка сделок: учимся на ошибках (убытках) и закрепляем прибыльные паттерны
            for order in db_orders:
                order_time = order["created_at"]
                pnl = float(order["pnl"] or 0.0)
                
                try:
                    o_dt = pd.to_datetime(order_time)
                    o_ts_ms = int(o_dt.timestamp() * 1000)
                    
                    # Находим ближайшую свечу в нашем df
                    idx = (df['time'] - o_ts_ms).abs().idxmin()
                    if idx < len(df) and abs(df.loc[idx, 'time'] - o_ts_ms) <= timeframe_ms:
                        feat = df.iloc[idx][feature_cols].values
                        if not np.isnan(feat).any():
                            close_reason = order.get("status", "CLOSED_MANUAL")
                            if pnl < 0:
                                # Ошибка: сделка закрылась в минус. Учим модель выставлять target = 0 (не торговать здесь)
                                target_val = 0.0
                                # Если выбило по обычному стоп-лоссу (CLOSED_SL), штрафуем паттерн входа сильнее (вес 6), чем при ручном закрытии (вес 4)
                                weight = 6 if close_reason == "CLOSED_SL" else 4
                            else:
                                # Успех: сделка в плюс. Закрепляем паттерн (target = 1)
                                target_val = 1.0
                                # Если закрылось по CLOSED_SL, но PnL > 0 — это сработка трейлинга в плюс! Закрепляем сильнее (вес 5)
                                if close_reason == "CLOSED_SL":
                                    weight = 5
                                elif close_reason == "CLOSED_TP":
                                    weight = 4
                                else:
                                    weight = 2
                                
                            for _ in range(weight):
                                extra_X.append(feat)
                                extra_y.append(target_val)
                except:
                    pass
            
            # Обработка HOLD-логов: выявляем упущенные возможности входа
            for log in db_logs:
                log_time = log["created_at"]
                try:
                    l_dt = pd.to_datetime(log_time)
                    l_ts_ms = int(l_dt.timestamp() * 1000)
                    
                    # Синхронизированный поиск: находим точную свечу, во время которой был сделан этот лог
                    match_mask = (df['time'] <= l_ts_ms) & (l_ts_ms < df['time'] + timeframe_ms)
                    if match_mask.any():
                        idx = df[match_mask].index[-1]
                    else:
                        continue
                    
                    # Проверяем последующие 10 свечей для оценки упущенной сделки
                    if idx < len(df) - 10:
                        entry_price = df.iloc[idx]["close"]
                        future_highs = df['high'].iloc[idx+1 : idx+11].values
                        future_lows = df['low'].iloc[idx+1 : idx+11].values
                        
                        # ATR-пороги для расчета TP/SL
                        atr_val = df.iloc[idx]["atr"]
                        if atr_val and atr_val > 0:
                            offset_tp = 4.0 * atr_val
                            offset_sl = 2.0 * atr_val
                        else:
                            offset_tp = entry_price * 0.006
                            offset_sl = entry_price * 0.003
                            
                        # Проверяем упущенную LONG (BUY) сделку
                        tp_price_buy = entry_price + offset_tp
                        sl_price_buy = entry_price - offset_sl
                        hit_buy = False
                        for j in range(10):
                            if future_lows[j] <= sl_price_buy:
                                break
                            if future_highs[j] >= tp_price_buy:
                                hit_buy = True
                                break
                                
                        # Проверяем упущенную SHORT (SELL) сделку
                        tp_price_sell = entry_price - offset_tp
                        sl_price_sell = entry_price + offset_sl
                        hit_sell = False
                        for j in range(10):
                            if future_highs[j] >= sl_price_sell:
                                break
                            if future_lows[j] <= tp_price_sell:
                                hit_sell = True
                                break
                                
                        if hit_buy or hit_sell:
                            feat = df.iloc[idx][feature_cols].values
                            if not np.isnan(feat).any():
                                for _ in range(3):  # Дублируем сэмпл для закрепления
                                    extra_X.append(feat)
                                    extra_y.append(1.0)
                except:
                    pass
            
            if len(extra_X) > 0:
                extra_X_df = pd.DataFrame(extra_X, columns=feature_cols)
                extra_y_series = pd.Series(extra_y)
                X_lgb = pd.concat([X_lgb, extra_X_df], ignore_index=True)
                y_lgb = pd.concat([y_lgb, extra_y_series], ignore_index=True)
                logger.info(f"[RL FEEDBACK] Добавлено {len(extra_X)} адаптивных сэмплов из закрытых ордеров и HOLD-логов для автокоррекции бота.")
    except Exception as db_ex:
        logger.warning(f"[RL FEEDBACK] Не удалось загрузить обратную связь из БД (некритично): {db_ex}")
    
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
        
    # Дообучаем модель трейлинг-стопа на новых данных (используем исходный valid_df)
    ai_trailing_model.fit(valid_df[feature_cols].values, valid_df['volatility_target'].values, epochs=50, lr=0.01)
        
    logger.info(f"Самообучение завершено! Модели успешно адаптированы под новые рыночные данные ({len(valid_df)} строк).")
    # Сохраняем адаптированные веса на диск
    save_models_to_disk(pair, timeframe)
    global current_model_pair, current_model_timeframe
    current_model_pair = pair.upper()
    current_model_timeframe = timeframe
    return True

def bootstrap_virtual_training(pair, timeframe):
    """
    Выполняет виртуальное ускоренное обучение (бэктест-симуляцию) на реальных свечах с Binance,
    если у нас нет сохраненной нейросети. Симулирует ордера, стопы и тейки,
    и использует результаты для RL-дообучения.
    """
    global training_status
    training_status = {
        "active": True,
        "pair": pair.upper(),
        "timeframe": timeframe,
        "started_at": time.time()
    }
    try:
        return _bootstrap_virtual_training_inner(pair, timeframe)
    finally:
        training_status["active"] = False

def _bootstrap_virtual_training_inner(pair, timeframe):
    logger.info(f"🚀 Запуск виртуального обучения (бутстрап) для {pair} ({timeframe})...")
    
    import trading_engine
    try:
        raw_klines = trading_engine.fetch_binance_klines(pair, timeframe, limit=1500)
    except Exception as e:
        logger.error(f"Ошибка получения свечей для виртуального обучения: {e}")
        return False
        
    if not raw_klines or len(raw_klines) < 150:
        logger.warning("Недостаточно свечей с Binance для запуска симуляции.")
        return False
        
    df_list = []
    for k in raw_klines:
        df_list.append({
            "open_time": int(k[0]),
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
            "obi": np.clip(np.random.normal(0, 0.1), -1.0, 1.0),
            "cvd": np.random.normal(0, 50.0)
        })
    df = pd.DataFrame(df_list)
    df['time'] = df['open_time']
    
    df = calculate_indicators(df)
    n = len(df)
    
    closes = df['close'].values
    X_dlinear = []
    Y_dlinear = []
    for i in range(59, n - 2):
        window = closes[i-59 : i+1]
        last_val = window[-1]
        x_norm = window / last_val - 1.0
        y_norm = np.array([closes[i+1] / last_val - 1.0, closes[i+2] / last_val - 1.0])
        X_dlinear.append(x_norm)
        Y_dlinear.append(y_norm)
        
    X_dlinear = np.array(X_dlinear)
    Y_dlinear = np.array(Y_dlinear)
    
    global dlinear_model, classifier_model, ai_trailing_model
    if HAS_TORCH:
        logger.info("Бутстрап: Первичное обучение DLinear (PyTorch)...")
        import torch.nn as nn
        import torch.optim as optim
        import torch
        dlinear_model = PyTorchDLinear(seq_len=60, pred_len=2)
        criterion = nn.MSELoss()
        optimizer = optim.Adam(dlinear_model.parameters(), lr=0.005)
        X_t = torch.tensor(X_dlinear, dtype=torch.float32).unsqueeze(-1)
        Y_t = torch.tensor(Y_dlinear, dtype=torch.float32).unsqueeze(-1)
        dlinear_model.train()
        for epoch in range(15):
            optimizer.zero_grad()
            outputs = dlinear_model(X_t)
            loss = criterion(outputs, Y_t)
            loss.backward()
            optimizer.step()
        dlinear_model.eval()
    else:
        logger.info("Бутстрап: Первичное обучение DLinear (NumPy)...")
        dlinear_model = NumPyDLinear(seq_len=60, pred_len=2)
        dlinear_model.fit(X_dlinear, Y_dlinear, epochs=15, lr=0.005)
        
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
    
    feature_cols = [
        'rsi_norm', 'atr_pct', 'obi', 'cvd', 'dlinear_pred_1m', 'dlinear_pred_2m', 'hour_feature',
        'vwap_dist', 'macd_hist_norm'
    ]
    
    virtual_orders = []
    for i in range(60, n - 20):
        rsi_norm_val = df.iloc[i]['rsi_norm']
        d_pred = df.iloc[i]['dlinear_pred_1m']
        
        signal = None
        if rsi_norm_val < 0.32 or d_pred > 0.0015:
            signal = "BUY"
        elif rsi_norm_val > 0.68 or d_pred < -0.0015:
            signal = "SELL"
            
        if signal:
            entry_price = df.iloc[i]['close']
            atr_val = df.iloc[i]['atr']
            if atr_val and atr_val > 0:
                offset_tp = 4.0 * atr_val
                offset_sl = 2.0 * atr_val
            else:
                offset_tp = entry_price * 0.006
                offset_sl = entry_price * 0.003
                
            tp_price = entry_price + offset_tp if signal == "BUY" else entry_price - offset_tp
            sl_price = entry_price - offset_sl if signal == "BUY" else entry_price + offset_sl
            
            pnl = None
            is_win = 0
            for j in range(i + 1, min(i + 21, n)):
                high_j = df.iloc[j]['high']
                low_j = df.iloc[j]['low']
                if signal == "BUY":
                    if low_j <= sl_price:
                        pnl = (sl_price - entry_price) / entry_price * 100
                        break
                    if high_j >= tp_price:
                        pnl = (tp_price - entry_price) / entry_price * 100
                        is_win = 1
                        break
                else:
                    if high_j >= sl_price:
                        pnl = (entry_price - sl_price) / entry_price * 100
                        break
                    if low_j <= tp_price:
                        pnl = (entry_price - tp_price) / entry_price * 100
                        is_win = 1
                        break
                        
            if pnl is None:
                exit_price = df.iloc[min(i + 20, n - 1)]['close']
                pnl = (exit_price - entry_price) / entry_price * 100 if signal == "BUY" else (entry_price - exit_price) / entry_price * 100
                is_win = 1 if pnl > 0 else 0
                
            virtual_orders.append({
                "idx": i,
                "pnl": pnl,
                "is_win": is_win
            })
            
    settings = db.get_settings()
    use_ai_limit_price = bool(dict(settings).get("use_ai_limit_price", 0)) if settings else False
    df = calculate_targets(df, use_ai_limit_price=use_ai_limit_price)
    
    for vo in virtual_orders:
        df.loc[vo["idx"], 'target'] = vo["is_win"]
        
    volatility_targets = np.zeros(n)
    for i in range(n):
        if i + 10 < n:
            volatility_targets[i] = np.std(closes[i+1 : i+11]) / closes[i]
        else:
            volatility_targets[i] = np.nan
    df['volatility_target'] = volatility_targets
    
    valid_df = df[feature_cols + ['target', 'volatility_target']].dropna()
    X_lgb = valid_df[feature_cols]
    y_lgb = valid_df['target']
    y_vol = valid_df['volatility_target']
    
    extra_X = []
    extra_y = []
    for vo in virtual_orders:
        feat = df.iloc[vo["idx"]][feature_cols].values
        if not np.isnan(feat).any():
            target_val = 1.0 if vo["is_win"] == 1 else 0.0
            weight = 5 if vo["is_win"] == 1 else 2
            for _ in range(weight):
                extra_X.append(feat)
                extra_y.append(target_val)
                
    if len(extra_X) > 0:
        extra_X_df = pd.DataFrame(extra_X, columns=feature_cols)
        extra_y_series = pd.Series(extra_y)
        X_lgb = pd.concat([X_lgb, extra_X_df], ignore_index=True)
        y_lgb = pd.concat([y_lgb, extra_y_series], ignore_index=True)
        
    logger.info(f"Бутстрап: Найдено и симулировано {len(virtual_orders)} виртуальных сделок для обучения классификатора.")
    
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
        classifier_model = lgb.train(params, train_data, num_boost_round=100)
    else:
        classifier_model = NumPyClassifier(num_features=len(feature_cols))
        classifier_model.fit(X_lgb.values, y_lgb.values, epochs=200, lr=0.1)
        
    ai_trailing_model.fit(valid_df[feature_cols].values, valid_df['volatility_target'].values, epochs=150, lr=0.01)
    
    logger.info("✅ Виртуальное обучение успешно завершено! Сохраняем веса...")
    save_models_to_disk(pair, timeframe)
    
    global current_model_pair, current_model_timeframe
    current_model_pair = pair.upper()
    current_model_timeframe = timeframe
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
        
        # Вычисляем нормированный час суток для фичи времени
        current_time_ms = float(current_row["time"]) if "time" in current_row else (float(current_row["open_time"]) if "open_time" in current_row else time.time() * 1000)
        import pandas as pd
        current_hour = pd.to_datetime(current_time_ms, unit='ms').hour / 24.0
        
        # --- Шаг 2: Инференс Классификатора ---
        features = np.array([[
            current_rsi_norm,
            current_atr_pct,
            current_obi,
            current_cvd,
            pred_change_1m,
            pred_change_2m,
            current_hour,
            current_row.get("vwap_dist", 0.0),
            current_row.get("macd_hist_norm", 0.0)
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
                asyncio.create_task(send_notification_async(msg))
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

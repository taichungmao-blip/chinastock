import json
import logging
import math
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock

import akshare as ak
import pandas as pd
import requests
import yfinance as yf

try:
    from deep_translator import GoogleTranslator
except ImportError:
    GoogleTranslator = None
try:
    from opencc import OpenCC
    _converter = OpenCC('s2t')
except ImportError:
    _converter = None

WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL', '').strip()
MIN_YIELD = float(os.getenv('MIN_YIELD', '7.0'))
MAX_PE = float(os.getenv('MAX_PE', '20'))
MAX_WORKERS = max(1, min(8, int(os.getenv('MAX_WORKERS', '3'))))
DIVIDEND_LOOKBACK_DAYS = max(1, int(os.getenv('DIVIDEND_LOOKBACK_DAYS', '365')))
CACHE_DIR = Path(os.getenv('MONITOR_CACHE_DIR', str(Path(__file__).resolve().parent)))
CONSTITUENTS_CACHE = CACHE_DIR / 'china_hk_constituents_cache.json'
TRANSLATION_CACHE = CACHE_DIR / 'china_hk_translation_cache.json'
LOG = logging.getLogger('china_hk_monitor')
_cache_lock = Lock()

HK_STOCKS = {
    '0939.HK': '建設銀行', '1398.HK': '工商銀行', '3988.HK': '中國銀行',
    '1288.HK': '農業銀行', '0941.HK': '中國移動', '0883.HK': '中海油',
    '1088.HK': '中國神華', '0005.HK': '匯豐控股', '1658.HK': '郵儲銀行',
    '0386.HK': '中國石化', '0857.HK': '中國石油', '2318.HK': '中國平安',
}
INDEX_CODES = {'000300': '滬深300', '000010': '上證180', '000009': '上證380', '399001': '深證成指'}


def read_cache(path):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(path, data):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + '.tmp')
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(path)
    except OSError as exc:
        LOG.warning('快取儲存失敗 %s: %s', path, exc)


def retry(fn, label, attempts=3):
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:
            LOG.warning('%s 第 %s/%s 次失敗: %s', label, attempt + 1, attempts, exc)
            if attempt + 1 < attempts:
                time.sleep(min(12, 2 ** attempt + random.uniform(0.5, 1.5)))
    return None


def traditional(text):
    value = str(text or '').strip()
    return _converter.convert(value) if _converter else value


def translate_name(text, cache):
    """英文名稱才嘗試翻譯；中文名稱只做簡轉繁。"""
    value = str(text or '').strip()
    if not value:
        return '未知'
    if re.search(r'[\u3400-\u9fff]', value):
        return traditional(value)
    if value in cache:
        return cache[value]
    if GoogleTranslator is None:
        return value
    result = retry(lambda: GoogleTranslator(source='auto', target='zh-TW').translate(value),
                   f'翻譯 {value}', attempts=3)
    if result and result.strip():
        with _cache_lock:
            cache[value] = traditional(result)
        return traditional(result)
    return value


def normalize_code(value):
    """辨識滬市、深市與北交所代碼；不接受非六碼或重複後綴。"""
    raw = str(value).strip().split('.')[0]
    if not re.fullmatch(r'\d{1,6}', raw):
        return None
    code = raw.zfill(6)
    if code.startswith(('6', '9')):
        return f'{code}.SS'
    if code.startswith(('0', '2', '3')):
        return f'{code}.SZ'
    if code.startswith(('4', '8')):
        return f'{code}.BJ'
    return None


def pick_column(df, options):
    for col in df.columns:
        normalized = str(col).strip().lower()
        if normalized in options:
            return col
    return None


def get_a_share_stocks():
    cached = read_cache(CONSTITUENTS_CACHE)
    previous = cached.get('stocks', {}) if isinstance(cached.get('stocks'), dict) else {}
    merged = {}
    success = 0
    for idx, label in INDEX_CODES.items():
        LOG.info('讀取 %s (%s)', label, idx)
        # 滬深300屬於中證指數系列，使用中證指數專用接口；
        # 其他指數沿用原本的 AKShare 接口。
        if idx == '000300':
            df = retry(
                lambda: ak.index_stock_cons_csindex(symbol='000300'),
                f'指數 {label}'
            )
        else:
            df = retry(
                lambda code=idx: ak.index_stock_cons(symbol=code),
                f'指數 {label}'
            )
        if df is None or df.empty:
            LOG.warning('%s 未取得成分股資料', label)
            continue
        code_col = pick_column(df, {
            '品种代码', '品種代碼', '证券代码', '證券代碼',
            'stock_code', 'code', '成分券代码', '成分券代碼'
        })
        name_col = pick_column(df, {
            '品种名称', '品種名稱', '证券简称', '證券簡稱',
            'stock_name', 'name', '成分券名称', '成分券名稱'
        })
        if code_col is None or name_col is None:
            LOG.warning('%s 欄位無法辨識：%s', label, list(df.columns))
            continue
        found = 0
        for code, name in zip(df[code_col], df[name_col]):
            symbol = normalize_code(code)
            if symbol:
                merged.setdefault(symbol, traditional(name))
                found += 1
        if found:
            success += 1
            LOG.info('%s 成功讀取 %s 筆', label, found)
    
    if success:
        save_cache(CONSTITUENTS_CACHE, {'updated_at': datetime.now(timezone.utc).isoformat(), 'stocks': merged})
    elif previous:
        LOG.warning('全部指數抓取失敗，改用舊成分股快取（可能過期）')
        merged = {k: traditional(v) for k, v in previous.items()
                  if re.fullmatch(r'\d{6}\.(SS|SZ|BJ)', k)}
    else:
        LOG.warning('無 A 股名單及快取，僅掃描預設港股')
    return merged


def as_positive_number(value):
    try:
        num = float(value)
        return num if math.isfinite(num) and num > 0 else None
    except (TypeError, ValueError):
        return None


def fetch_single_stock(symbol, name_map, translation_cache):
    """使用最近 N 天現金股息 / 最新價格估算歷史殖利率；非預測殖利率。"""
    try:
        time.sleep(random.uniform(0.2, 0.8))
        ticker = yf.Ticker(symbol)
        info = None
        try:
            price = as_positive_number(ticker.fast_info.last_price)
        except Exception:
            price = None
        if price is None:
            info = retry(lambda: ticker.info, f'{symbol} 基本資料', attempts=2)
            info = info if isinstance(info, dict) else {}
            price = as_positive_number(info.get('regularMarketPrice') or info.get('currentPrice'))
        if price is None:
            LOG.info('%s 缺少有效股價', symbol)
            return None

        dividends = retry(lambda: ticker.dividends, f'{symbol} 股息紀錄', attempts=2)
        dividend_sum = None
        if dividends is not None and not dividends.empty:
            try:
                dates = pd.to_datetime(dividends.index, utc=True)
                cutoff = pd.Timestamp.now(tz='UTC') - pd.Timedelta(days=DIVIDEND_LOOKBACK_DAYS)
                dividend_sum = float(pd.to_numeric(dividends[dates >= cutoff], errors='coerce').fillna(0).sum())
            except Exception as exc:
                LOG.warning('%s 股息日期處理失敗: %s', symbol, exc)
        if info is None:
            info = retry(lambda: ticker.info, f'{symbol} 基本資料', attempts=2)
            info = info if isinstance(info, dict) else {}
        # 僅在股息歷史不可用時使用股息率備援，避免 0 配息誤判。
        if dividend_sum is None:
            dividend_sum = as_positive_number(info.get('dividendRate') or info.get('trailingAnnualDividendRate'))
        if dividend_sum is None:
            return None
        yield_pct = dividend_sum / price * 100
        if not math.isfinite(yield_pct) or yield_pct < MIN_YIELD:
            return None

        pe = as_positive_number(info.get('trailingPE'))
        if pe is None:
            eps = as_positive_number(info.get('trailingEps'))
            pe = price / eps if eps else None
        if pe is None or pe > MAX_PE:
            return None

        low = as_positive_number(info.get('fiftyTwoWeekLow'))
        distance = (price / low - 1) * 100 if low else None
        raw_name = name_map.get(symbol) or info.get('shortName') or symbol
        return {
            '名稱': translate_name(raw_name, translation_cache), '代碼': symbol,
            '市場': '港股' if symbol.endswith('.HK') else 'A股',
            '殖利率(%)': yield_pct, '距低點%': distance, 'PE': pe,
        }
    except Exception as exc:
        LOG.warning('%s 處理失敗: %s', symbol, exc)
        return None


def send_to_discord(df):
    if not WEBHOOK_URL:
        LOG.error('未設定 DISCORD_WEBHOOK_URL，無法推播')
        return False
    top = df.head(25)
    lines = [f'### 🛡️ 滬深港高股息監控｜符合條件 {len(df)} 檔（顯示前 {len(top)} 檔）',
             f'篩選：近 {DIVIDEND_LOOKBACK_DAYS} 天歷史現金股息殖利率 ≥ {MIN_YIELD:g}%｜0 < PE ≤ {MAX_PE:g}',
             '```', '名稱 | 代碼 | 殖利率 | 距52週低點 | PE', '-' * 55]
    for _, row in top.iterrows():
        distance = 'N/A' if pd.isna(row['距低點%']) else f"{row['距低點%']:.1f}%"
        lines.append(f"{str(row['名稱'])[:10]} | {row['代碼']} | {row['殖利率(%)']:.2f}% | {distance} | {row['PE']:.1f}")
    lines += ['```', '註：殖利率依歷史配息估算，非未來保證配息；A/H 股以各自交易貨幣計價。']
    message = '\n'.join(lines)
    # Discord content 上限 2000 字元，避免因訊息太長失敗。
    if len(message) > 1950:
        message = message[:1900].rsplit('\n', 1)[0] + '\n```'
    for attempt in range(3):
        try:
            response = requests.post(WEBHOOK_URL, json={'content': message}, timeout=20)
            if response.status_code == 429:
                wait = min(30, float(response.json().get('retry_after', 3)))
                LOG.warning('Discord 限流，等待 %.1f 秒', wait)
                time.sleep(wait)
                continue
            response.raise_for_status()
            LOG.info('Discord 推播成功')
            return True
        except (requests.RequestException, ValueError) as exc:
            LOG.warning('Discord 推播第 %s 次失敗: %s', attempt + 1, exc)
            if attempt < 2:
                time.sleep(2 ** attempt)
    return False


def run_monitor():
    if not WEBHOOK_URL:
        LOG.error('請先設定 DISCORD_WEBHOOK_URL 環境變數')
        return
    LOG.info('讀取港股清單與 A 股指數成分股')
    name_map = dict(HK_STOCKS)
    name_map.update({k: v for k, v in get_a_share_stocks().items() if k not in name_map})
    LOG.info('掃描 %s 檔（港股 %s 檔）', len(name_map), len(HK_STOCKS))
    translation_cache = read_cache(TRANSLATION_CACHE)
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        tasks = {pool.submit(fetch_single_stock, code, name_map, translation_cache): code for code in name_map}
        for count, future in enumerate(as_completed(tasks), 1):
            try:
                item = future.result()
                if item:
                    results.append(item)
            except Exception as exc:
                LOG.warning('%s 執行緒錯誤: %s', tasks[future], exc)
            if count % 50 == 0 or count == len(tasks):
                LOG.info('進度 %s/%s；符合 %s 檔', count, len(tasks), len(results))
    save_cache(TRANSLATION_CACHE, translation_cache)
    if not results:
        LOG.info('掃描完成，沒有符合條件的標的')
        return
    df = pd.DataFrame(results).sort_values('殖利率(%)', ascending=False)
    send_to_discord(df)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    run_monitor()

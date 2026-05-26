import akshare as ak
import yfinance as yf
import pandas as pd
import os
import requests
import time
import random
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 1. 配置區 ---
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
MIN_YIELD = 6.5
MAX_PE = 20.0
MAX_WORKERS = 4 # 大幅降低線程數以規避 Rate Limit

def fetch_single_stock(symbol, name_map):
    """具備退讓機制的抓取邏輯"""
    try:
        # 加入隨機微小延遲 (0.1s ~ 0.5s)
        time.sleep(random.uniform(0.1, 0.5))
        
        ticker = yf.Ticker(symbol)
        
        # 獲取價格
        price = None
        if hasattr(ticker, 'fast_info'):
            price = ticker.fast_info.last_price
        if not price:
            info = ticker.info
            price = info.get('regularMarketPrice') or info.get('currentPrice')

        # 獲取股息 (450天窗口)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=450)
        div_history = ticker.dividends
        div_sum = div_history[div_history.index >= start_date.strftime('%Y-%m-%d')].sum()
        
        # 備援：如果歷史記錄為 0，嘗試 dividendRate
        if div_sum == 0:
            div_sum = ticker.info.get('dividendRate') or 0
            
        dy_pct = (div_sum / price * 100) if price and price > 0 else 0

        # 過濾第一關：殖利率
        if dy_pct < MIN_YIELD:
            return None

        # 獲取 PE 與 52週低點
        info = ticker.info
        pe = info.get('trailingPE')
        if not pe:
            eps = info.get('trailingEps')
            if eps and eps > 0 and price:
                pe = price / eps
        
        low_52w = info.get('fiftyTwoWeekLow')
        dist_from_low = ((price - low_52w) / low_52w * 100) if price and low_52w else 0

        if pe and 0 < pe <= MAX_PE:
            return {
                "名稱": name_map.get(symbol, "未知"),
                "代碼": symbol,
                "殖利率(%)": dy_pct,
                "距低點%": dist_from_low,
                "PE": pe
            }
    except Exception as e:
        err_msg = str(e)
        if "Too Many Requests" in err_msg:
            print(f"⚠️ Rate limited on {symbol}, pausing...")
            time.sleep(2) # 遇到 429 暫停 2 秒
        return None

def run_monitor():
    name_map = {}
    
    # 步驟 1: 先加載港股 (優先處理)
    print("--- 步驟 1: 加載港股清單 (優先權最高) ---")
    hk_list = {
        "0939.HK": "建設銀行", "1398.HK": "工商銀行", "3988.HK": "中國銀行",
        "1288.HK": "農業銀行", "0941.HK": "中國移動", "0883.HK": "中海油",
        "1088.HK": "中國神華", "0005.HK": "匯豐控股", "1658.HK": "郵儲銀行",
        "0386.HK": "中國石化", "0857.HK": "中國石油", "2318.HK": "中國平安"
    }
    # 港股放在最前面
    name_map.update(hk_list)

    # 步驟 2: 加載 A 股名單
    print("--- 步驟 2: 獲取 A 股名單 ---")
    indices_a = {"000010": "上證180", "000009": "上證380", "399001": "深證成指"}
    for idx_code in indices_a:
        try:
            df = ak.index_stock_cons(symbol=idx_code)
            c_code = next(c for c in ['品种代码', 'stock_code', 'code'] if c in df.columns)
            c_name = next(c for c in ['品种名称', 'stock_name', 'name'] if c in df.columns)
            for _, row in df.iterrows():
                raw_code = str(row[c_code]).zfill(6)
                suffix = ".SS" if raw_code.startswith('6') else ".SZ"
                sym = f"{raw_code}{suffix}"
                if sym not in name_map:
                    name_map[sym] = row[c_name]
        except: continue

    codes = list(name_map.keys())
    print(f"✅ 掃描範圍：{len(codes)} 隻標的。")

    results = []
    # 使用小規模線程池
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_stock = {executor.submit(fetch_single_stock, s, name_map): s for s in codes}
        for i, future in enumerate(as_completed(future_to_stock)):
            res = future.result()
            if res: results.append(res)
            if (i+1) % 50 == 0:
                print(f"已完成: {i+1}/{len(codes)}...")

    if results:
        final_df = pd.DataFrame(results).sort_values(by="殖利率(%)", ascending=False)
        send_to_discord(final_df)
    else:
        print("💡 掃描完成，無符合標的。")

def send_to_discord(df):
    top_stocks = df.head(25)
    msg = "### 🛡️ 滬深港三棲監控 (抗屏蔽穩健版)\n"
    msg += "```\n"
    msg += f"{'名稱':<8} {'代碼':<10} {'殖利率':<8} {'距低點%':<8} {'PE':<6}\n"
    msg += "-" * 48 + "\n"
    for _, row in top_stocks.iterrows():
        name = str(row['名稱'])[:4]
        msg += f"{name:<8} {row['代碼']:<10} {row['殖利率(%)']:>7.2f}% {row['距低點%']:>7.1f}% {row['PE']:>6.1f}\n"
    msg += "```\n"
    msg += f"> *策略: 港股優先 + 頻率限制規避*"
    requests.post(DISCORD_WEBHOOK_URL, json={"content": msg}, timeout=15)

if __name__ == "__main__":
    run_monitor()

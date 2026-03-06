import akshare as ak
import yfinance as yf
import pandas as pd
import os
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 1. 配置區 ---
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
MIN_YIELD = 4.0
MAX_YIELD = 25.0
MAX_PE = 25.0
MAX_WORKERS = 15

def fetch_single_stock(symbol, name_map):
    """抓取數據並計算 52 週低點距離"""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        # 1. 取得股價與 52 週低點
        price = info.get('regularMarketPrice') or info.get('currentPrice') or info.get('previousClose')
        low_52w = info.get('fiftyTwoWeekLow')
        
        # 2. 計算 52 週低點距離 %
        dist_from_low = 0
        if price and low_52w:
            dist_from_low = ((price - low_52w) / low_52w) * 100

        # 3. 取得殖利率 (手動複算模式)
        dy_raw = info.get('trailingAnnualDividendYield') or info.get('dividendYield') or 0
        div_rate = info.get('dividendRate') or 0
        if price and price > 0:
            calc_dy = (div_rate / price)
            dy = max(float(dy_raw), calc_dy)
        else:
            dy = float(dy_raw)

        # 4. 取得 PE/PB
        pe = info.get('trailingPE') or info.get('forwardPE')
        pb = info.get('priceToBook')

        if dy > 0 and pe:
            dy_pct = dy if dy > 1.0 else dy * 100
            pe_val = float(pe)
            
            if MIN_YIELD <= dy_pct <= MAX_YIELD and 0 < pe_val <= MAX_PE:
                return {
                    "名稱": name_map.get(symbol, "未知"),
                    "代碼": symbol,
                    "殖利率(%)": dy_pct,
                    "PE": pe_val,
                    "PB": pb if pb else 0,
                    "距低點%": dist_from_low
                }
    except:
        pass
    return None

def run_monitor():
    name_map = {}
    
    # 步驟 1: 獲取名單
    indices_a = {"000010": "上證180", "000009": "上證380", "399001": "深證成指"}
    for idx_code, idx_name in indices_a.items():
        try:
            df = ak.index_stock_cons(symbol=idx_code)
            c_code = next(c for c in ['品种代码', 'stock_code', 'code'] if c in df.columns)
            c_name = next(c for c in ['品种名称', 'stock_name', 'name'] if c in df.columns)
            for _, row in df.iterrows():
                raw_code = str(row[c_code]).zfill(6)
                suffix = ".SS" if raw_code.startswith('6') else ".SZ"
                name_map[f"{raw_code}{suffix}"] = row[c_name]
        except: continue

    # 步驟 2: 港股名單
    hk_raw = {
        "0005": "匯豐控股", "0939": "建設銀行", "1398": "工商銀行", "3988": "中國銀行",
        "1288": "農業銀行", "0941": "中國移動", "0883": "中海油", "0386": "中石化",
        "0857": "中石油", "1088": "中國神華", "2628": "中國人壽", "2318": "中國平安"
    }
    for k, v in hk_raw.items():
        symbol = f"{k.zfill(4)}.HK" if len(k) <= 4 else f"{k.zfill(5)}.HK"
        name_map[symbol] = v

    codes = list(name_map.keys())
    print(f"✅ 掃描範圍：{len(codes)} 隻標的。")

    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_stock = {executor.submit(fetch_single_stock, s, name_map): s for s in codes}
        for future in as_completed(future_to_stock):
            res = future.result()
            if res: results.append(res)

    if results:
        final_df = pd.DataFrame(results).sort_values(by="殖利率(%)", ascending=False)
        send_to_discord(final_df)
    else:
        print("💡 掃描完成，無符合條件標的。")

def send_to_discord(df):
    top_stocks = df.head(25)
    msg = "### 🏹 價值股底部監控 (高息 + 貼地)\n"
    msg += "```\n"
    msg += f"{'名稱':<8} {'代碼':<10} {'殖利率':<8} {'距低點%':<8} {'PE':<6}\n"
    msg += "-" * 48 + "\n"
    for _, row in top_stocks.iterrows():
        name = str(row['名稱'])[:4]
        # 顯示名稱、代碼、殖利率、距離 52 週低點 %、PE
        msg += f"{name:<8} {row['代碼']:<10} {row['殖利率(%)']:>7.2f}% {row['距低點%']:>7.1f}% {row['PE']:>6.1f}\n"
    msg += "```\n"
    msg += f"> *指標說明: 距低點% 越小代表股價越接近一年最低點*"
    requests.post(DISCORD_WEBHOOK_URL, json={"content": msg}, timeout=15)

if __name__ == "__main__":
    run_monitor()

import akshare as ak
import yfinance as yf
import pandas as pd
import os
import requests
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 1. 配置區 ---
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
MIN_YIELD = 4.0
MAX_PE = 25.0
MAX_WORKERS = 10 # 降低線程數，因為抓取歷史紀錄較耗時

def fetch_single_stock(symbol, name_map):
    """透過歷史配息記錄計算真實殖利率"""
    try:
        ticker = yf.Ticker(symbol)
        
        # 1. 取得最新股價
        price = ticker.fast_info.last_price if hasattr(ticker, 'fast_info') else None
        if not price:
            info = ticker.info
            price = info.get('regularMarketPrice') or info.get('currentPrice')

        # 2. 硬核計算：抓取過去 365 天的所有配息加總
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)
        dividends = ticker.dividends
        
        # 篩選過去一年的配息
        last_year_divs = dividends[dividends.index >= start_date.strftime('%Y-%m-%d')]
        total_div = last_year_divs.sum()

        # 3. 計算殖利率
        dy_pct = (total_div / price) * 100 if price and price > 0 else 0

        # 4. 取得 PE (仍使用 info)
        info = ticker.info
        pe = info.get('trailingPE') or info.get('forwardPE')
        low_52w = info.get('fiftyTwoWeekLow')
        
        dist_from_low = ((price - low_52w) / low_52w * 100) if price and low_52w else 0

        if dy_pct >= MIN_YIELD and pe and 0 < pe <= MAX_PE:
            return {
                "名稱": name_map.get(symbol, "未知"),
                "代碼": symbol,
                "殖利率(%)": dy_pct,
                "距低點%": dist_from_low,
                "PE": pe
            }
    except:
        pass
    return None

def run_monitor():
    name_map = {}
    print("--- 步驟 1: 獲取 A 股名單 ---")
    # 為了測試，我們先專注於 180 指數與港股，確保港股能出現在前幾名
    indices_a = {"000010": "上證180", "399001": "深證成指"}
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

    print("--- 步驟 2: 加載港股核心標的 ---")
    hk_list = {
        "0939.HK": "建設銀行", "1398.HK": "工商銀行", "3988.HK": "中國銀行",
        "1288.HK": "農業銀行", "0941.HK": "中國移動", "0883.HK": "中海油",
        "1088.HK": "中國神華", "0005.HK": "匯豐控股", "1658.HK": "郵儲銀行"
    }
    name_map.update(hk_list)

    codes = list(name_map.keys())
    print(f"✅ 掃描範圍：{len(codes)} 隻標的。")

    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_stock = {executor.submit(fetch_single_stock, s, name_map): s for s in codes}
        for i, future in enumerate(as_completed(future_to_stock)):
            res = future.result()
            if res: results.append(res)

    if results:
        final_df = pd.DataFrame(results).sort_values(by="殖利率(%)", ascending=False)
        send_to_discord(final_df)
    else:
        print("💡 掃描完成，無符合標的。")

def send_to_discord(df):
    top_stocks = df.head(25)
    msg = "### 🏮 滬深港三棲監控 (歷史配息複算版)\n"
    msg += "```\n"
    msg += f"{'名稱':<8} {'代碼':<10} {'殖利率':<8} {'距低點%':<8} {'PE':<6}\n"
    msg += "-" * 48 + "\n"
    for _, row in top_stocks.iterrows():
        name = str(row['名稱'])[:4]
        msg += f"{name:<8} {row['代碼']:<10} {row['殖利率(%)']:>7.2f}% {row['距低點%']:>7.1f}% {row['PE']:>6.1f}\n"
    msg += "```\n"
    msg += f"> *模式: 歷史配息加總 (過去365天)*"
    requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})

if __name__ == "__main__":
    run_monitor()

import akshare as ak
import yfinance as yf
import pandas as pd
import os
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 1. 配置區 ---
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
MIN_YIELD = 5.0
MAX_PE = 20.0
MAX_WORKERS = 10 # 並行線程數

def fetch_single_stock(symbol, name_map):
    """單一股票抓取邏輯"""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        dy = info.get('trailingAnnualDividendYield')
        pe = info.get('trailingPE')
        pb = info.get('priceToBook') # 額外抓取 PB

        if dy is not None and pe is not None:
            dy_pct = dy * 100
            if dy_pct >= MIN_YIELD and 0 < pe <= MAX_PE:
                return {
                    "名稱": name_map.get(symbol, "未知"),
                    "代碼": symbol,
                    "殖利率(%)": dy_pct,
                    "PE": pe,
                    "PB": pb if pb else 0
                }
    except:
        pass
    return None

def run_monitor():
    print("--- 步驟 1: 獲取成分股與名稱映射 ---")
    df_180 = ak.index_stock_cons(symbol="000010")
    df_380 = ak.index_stock_cons(symbol="000009")
    
    # 建立 { "600000.SS": "浦發銀行" } 的映射表
    name_map = {}
    for df in [df_180, df_380]:
        c_code = next(c for c in ['品种代码', 'stock_code', 'code'] if c in df.columns)
        c_name = next(c for c in ['品种名称', 'stock_name', 'name'] if c in df.columns)
        for _, row in df.iterrows():
            name_map[f"{row[c_code]}.SS"] = row[c_name]

    codes = list(name_map.keys())
    print(f"✅ 成功鎖定 {len(codes)} 隻標的。")

    print(f"--- 步驟 2: 並行抓取數據 (Workers: {MAX_WORKERS}) ---")
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_stock = {executor.submit(fetch_single_stock, s, name_map): s for s in codes}
        for future in as_completed(future_to_stock):
            res = future.result()
            if res:
                results.append(res)

    # 3. 整理與排序
    final_df = pd.DataFrame(results).sort_values(by="殖利率(%)", ascending=False)
    
    # 4. 發送 Discord (邏輯與之前相同)
    if not final_df.empty:
        send_to_discord(final_df)
    print(f"🎯 任務完成，符合標的: {len(final_df)} 隻。")

def send_to_discord(df):
    top_stocks = df.head(20)
    msg = "### 💎 上證 180/380 價值股監控 (並行優化版)\n"
    msg += "```\n"
    msg += f"{'名稱':<8} {'代碼':<10} {'殖利率':<8} {'PE':<6} {'PB':<5}\n"
    msg += "-" * 45 + "\n"
    for _, row in top_stocks.iterrows():
        name = row['名稱'][:4]
        msg += f"{name:<8} {row['代碼']:<10} {row['殖利率(%)']:>7.2f}% {row['PE']:>6.1f} {row['PB']:>5.2f}\n"
    msg += "```\n"
    requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})

if __name__ == "__main__":
    run_monitor()

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
MAX_PE = 25.0
MAX_WORKERS = 20 # 增加線程數以處理滬深港共 1200+ 隻股票

def fetch_single_stock(symbol, name_map):
    """抓取單一股票數據 (支援 .SS, .SZ, .HK)"""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        dy = info.get('trailingAnnualDividendYield')
        pe = info.get('trailingPE')
        pb = info.get('priceToBook')

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
    # 2. 定義要監控的指數 (滬、深、港)
    indices_a = {"000010": "上證180", "000009": "上證380", "399001": "深證成指"}
    indices_hk = {"恒生指数": "恒生指數"} # 包含香港市值最大的 80+ 隻龍頭
    
    name_map = {}
    print("--- 步驟 1: 獲取滬深港成分股清單 ---")
    
    # 處理 A 股
    for idx_code, idx_name in indices_a.items():
        try:
            df = ak.index_stock_cons(symbol=idx_code)
            code_col = next(c for c in ['品种代码', 'stock_code', 'code'] if c in df.columns)
            name_col = next(c for c in ['品种名称', 'stock_name', 'name'] if c in df.columns)
            for _, row in df.iterrows():
                raw_code = str(row[code_col]).zfill(6) # A 股補足 6 位
                suffix = ".SS" if raw_code.startswith('6') else ".SZ"
                name_map[f"{raw_code}{suffix}"] = row[name_col]
        except: continue

    # 處理港股
    for idx_symbol, idx_name in indices_hk.items():
        try:
            print(f"正在獲取 {idx_name} 名單...")
            df_hk = ak.stock_hk_selection(symbol=idx_symbol)
            for _, row in df_hk.iterrows():
                # 港股代碼補足 4 位，例如 5 -> 0005.HK
                raw_code = str(row['代码']).zfill(4)
                name_map[f"{raw_code}.HK"] = row['名称']
        except Exception as e:
            print(f"獲取港股失敗: {e}")

    codes = list(name_map.keys())
    print(f"✅ 已鎖定滬深港標的共 {len(codes)} 隻。")

    print(f"--- 步驟 2: 並行抓取數據 (線程數: {MAX_WORKERS}) ---")
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_stock = {executor.submit(fetch_single_stock, s, name_map): s for s in codes}
        for i, future in enumerate(as_completed(future_to_stock)):
            res = future.result()
            if res: results.append(res)
            if (i + 1) % 200 == 0: print(f"進度：{i+1}/{len(codes)}...")

    # 3. 整理與發送
    if results:
        final_df = pd.DataFrame(results).sort_values(by="殖利率(%)", ascending=False)
        send_to_discord(final_df)
    else:
        print("💡 掃描完成，無符合條件標的。")

def send_to_discord(df):
    top_stocks = df.head(25) # 增加顯示數量至 25 隻
    msg = "### 🏮 滬深港三棲價值股監控\n"
    msg += f"篩選：殖利率 > {MIN_YIELD}% | PE < {MAX_PE}\n"
    msg += "```\n"
    msg += f"{'名稱':<8} {'代碼':<10} {'殖利率':<8} {'PE':<6} {'PB':<5}\n"
    msg += "-" * 45 + "\n"
    for _, row in top_stocks.iterrows():
        name = str(row['名稱'])[:4]
        msg += f"{name:<8} {row['代碼']:<10} {row['殖利率(%)']:>7.2f}% {row['PE']:>6.1f} {row['PB']:>5.2f}\n"
    msg += "```\n"
    msg += f"> *GitHub Runner 更新於: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}*"
    requests.post(DISCORD_WEBHOOK_URL, json={"content": msg}, timeout=15)

if __name__ == "__main__":
    run_monitor()

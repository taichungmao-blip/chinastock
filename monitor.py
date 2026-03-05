import akshare as ak
import yfinance as yf
import pandas as pd
import os
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 1. 配置區 ---
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
MIN_YIELD = 6.0
MAX_PE = 20.0
MAX_WORKERS = 15 # 增加線程數以處理更多標的

def fetch_single_stock(symbol, name_map):
    """抓取單一股票數據"""
    try:
        ticker = yf.Ticker(symbol)
        # 僅獲取必要資訊以節省資源
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
    # 2. 定義要監控的指數
    target_indices = {
        "000010": "上證180",
        "000009": "上證380",
        "399001": "深證成指"
    }
    
    name_map = {}
    print("--- 步驟 1: 獲取滬深成分股清單 ---")
    
    for idx_code, idx_name in target_indices.items():
        try:
            print(f"正在獲取 {idx_name} 名單...")
            df = ak.index_stock_cons(symbol=idx_code)
            
            # 動態識別欄位
            code_col = next(c for c in ['品种代码', 'stock_code', 'code'] if c in df.columns)
            name_col = next(c for c in ['品种名称', 'stock_name', 'name'] if c in df.columns)
            
            for _, row in df.iterrows():
                raw_code = str(row[code_col])
                # 判斷交易所後綴: 6 開頭為上交所 (.SS)，其餘(0, 3等)為深交所 (.SZ)
                suffix = ".SS" if raw_code.startswith('6') else ".SZ"
                full_symbol = f"{raw_code}{suffix}"
                name_map[full_symbol] = row[name_col]
        except Exception as e:
            print(f"獲取 {idx_name} 失敗: {e}")

    codes = list(name_map.keys())
    print(f"✅ 成功鎖定滬深標的共 {len(codes)} 隻。")

    print(f"--- 步驟 2: 並行抓取數據 (線程數: {MAX_WORKERS}) ---")
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_stock = {executor.submit(fetch_single_stock, s, name_map): s for s in codes}
        for i, future in enumerate(as_completed(future_to_stock)):
            res = future.result()
            if res:
                results.append(res)
            # 顯示進度
            if (i + 1) % 100 == 0:
                print(f"已處理 {i+1}/{len(codes)} 隻...")

    # 3. 整理並發送通知
    if results:
        final_df = pd.DataFrame(results).sort_values(by="殖利率(%)", ascending=False)
        send_to_discord(final_df)
        print(f"🎯 任務完成，符合條件標的: {len(final_df)} 隻。")
    else:
        print("💡 掃描完成，無符合條件標的。")

def send_to_discord(df):
    top_stocks = df.head(20)
    msg = "### 🏮 滬深 180/380/深成 價值股監控\n"
    msg += f"條件：殖利率 > {MIN_YIELD}% | PE < {MAX_PE}\n"
    msg += "```\n"
    msg += f"{'名稱':<8} {'代碼':<10} {'殖利率':<8} {'PE':<6} {'PB':<5}\n"
    msg += "-" * 45 + "\n"
    for _, row in top_stocks.iterrows():
        name = str(row['名稱'])[:4]
        msg += f"{name:<8} {row['代碼']:<10} {row['殖利率(%)']:>7.2f}% {row['PE']:>6.1f} {row['PB']:>5.2f}\n"
    msg += "```\n"
    msg += f"> *數據源: Yahoo Finance | 更新時間: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}*"
    requests.post(DISCORD_WEBHOOK_URL, json={"content": msg}, timeout=15)

if __name__ == "__main__":
    run_monitor()

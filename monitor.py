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
MAX_WORKERS = 10 # 診斷時降低線程數確保穩定

def fetch_single_stock(symbol, name_map):
    """強化數據抓取邏輯"""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        # 強化：多欄位抓取殖利率 (Yahoo 港股有時會換名稱)
        dy = info.get('trailingAnnualDividendYield') or info.get('dividendYield') or info.get('yield')
        pe = info.get('trailingPE') or info.get('forwardPE')
        pb = info.get('priceToBook')

        # 診斷：如果是匯豐或建行，強制印出數值
        if symbol in ["0005.HK", "0939.HK", "1398.HK"]:
            print(f"🔍 [港股診斷] {symbol}: dy={dy}, pe={pe}, pb={pb}")

        if dy is not None and pe is not None:
            dy_pct = float(dy) * 100
            pe_val = float(pe)
            if dy_pct >= MIN_YIELD and 0 < pe_val <= MAX_PE:
                return {
                    "名稱": name_map.get(symbol, "未知"),
                    "代碼": symbol,
                    "殖利率(%)": dy_pct,
                    "PE": pe_val,
                    "PB": pb if pb else 0
                }
    except Exception as e:
        if symbol in ["0005.HK", "0939.HK"]:
            print(f"❌ [港股報錯] {symbol}: {e}")
    return None

def run_monitor():
    name_map = {}
    
    # A 股邏輯不變
    print("--- 步驟 1: 獲取 A 股清單 ---")
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

    print("--- 步驟 2: 加載港股核心標的 (調整代碼格式) ---")
    # 將港股代碼改為 4 位 (這是 Yahoo Finance 最常用的格式)
    hk_raw = {
        "0005": "匯豐控股", "0939": "建設銀行", "1398": "工商銀行",
        "03988": "中國銀行", "1288": "農業銀行", "0941": "中國移動",
        "0883": "中國海洋石油", "0386": "中石化", "0857": "中石油",
        "2628": "中國人壽", "2318": "中國平安", "0011": "恆生銀行",
        "0002": "中電控股", "1088": "中國神華", "0700": "騰訊控股"
    }
    for k, v in hk_raw.items():
        # Yahoo Finance 港股代碼需視情況補 4 位或 5 位，我們用 .HK 結尾
        symbol = f"{k.zfill(4)}.HK" if len(k) <= 4 else f"{k.zfill(5)}.HK"
        name_map[symbol] = v

    codes = list(name_map.keys())
    print(f"✅ 最終掃描範圍：{len(codes)} 隻標的。")

    print(f"--- 步驟 3: 開始抓取 ---")
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
        print("💡 掃描完成，無符合條件標的。")

def send_to_discord(df):
    top_stocks = df.head(25)
    msg = "### 🏮 滬深港價值股監控 (診斷版)\n"
    msg += "```\n"
    msg += f"{'名稱':<8} {'代碼':<10} {'殖利率':<8} {'PE':<6} {'PB':<5}\n"
    msg += "-" * 45 + "\n"
    for _, row in top_stocks.iterrows():
        name = str(row['名稱'])[:4]
        msg += f"{name:<8} {row['代碼']:<10} {row['殖利率(%)']:>7.2f}% {row['PE']:>6.1f} {row['PB']:>5.2f}\n"
    msg += "```\n"
    requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})

if __name__ == "__main__":
    run_monitor()

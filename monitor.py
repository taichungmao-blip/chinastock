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
MAX_YIELD = 25.0
MAX_PE = 20.0
MAX_WORKERS = 20 # 恢復全量掃描，線程數調高

def fetch_single_stock(symbol, name_map):
    """具備智能單位識別與異常過濾"""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        # 兼容多個欄位
        dy = info.get('trailingAnnualDividendYield') or info.get('dividendYield') or info.get('yield')
        pe = info.get('trailingPE') or info.get('forwardPE')
        pb = info.get('priceToBook')

        if dy is not None and pe is not None:
            raw_dy = float(dy)
            # 智能單位縮放：0.05 -> 5.0% | 5.0 -> 5.0%
            dy_pct = raw_dy if raw_dy > 1.0 else raw_dy * 100
            pe_val = float(pe)
            
            if MIN_YIELD <= dy_pct <= MAX_YIELD and 0 < pe_val <= MAX_PE:
                return {
                    "名稱": name_map.get(symbol, "未知"),
                    "代碼": symbol,
                    "殖利率(%)": dy_pct,
                    "PE": pe_val,
                    "PB": pb if pb else 0
                }
    except:
        pass
    return None

def run_monitor():
    name_map = {}
    
    # 步驟 1: 恢復完整的 A 股名單 (包含 380 指數)
    print("--- 步驟 1: 獲取滬深名單 (180+380+深成) ---")
    indices_a = {
        "000010": "上證180", 
        "000009": "上證380",  # <--- 加回這裡，中谷物流就會回來了
        "399001": "深證成指"
    }
    
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
    print("--- 步驟 2: 獲取港股核心標的 ---")
    hk_raw = {
        "0005": "匯豐控股", "0939": "建設銀行", "1398": "工商銀行",
        "3988": "中國銀行", "1288": "農業銀行", "0941": "中國移動",
        "0883": "中海油", "0386": "中石化", "0857": "中石油",
        "2628": "中國人壽", "2318": "中國平安", "1088": "中國神華", 
        "0011": "恆生銀行", "0700": "騰訊控股", "0002": "中電控股"
    }
    for k, v in hk_raw.items():
        symbol = f"{k.zfill(4)}.HK" if len(k) <= 4 else f"{k.zfill(5)}.HK"
        name_map[symbol] = v

    codes = list(name_map.keys())
    print(f"✅ 掃描範圍：{len(codes)} 隻標的。")

    # 步驟 3: 並行抓取
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_stock = {executor.submit(fetch_single_stock, s, name_map): s for s in codes}
        for i, future in enumerate(as_completed(future_to_stock)):
            res = future.result()
            if res: results.append(res)
            if (i+1) % 300 == 0: print(f"進度: {i+1}...")

    # 4. 排序與發送
    if results:
        final_df = pd.DataFrame(results).sort_values(by="殖利率(%)", ascending=False)
        send_to_discord(final_df)
    else:
        print("💡 掃描完成，無標的。")

def send_to_discord(df):
    top_stocks = df.head(25)
    msg = "### 💎 滬深港三棲價值股監控 (完整版)\n"
    msg += f"條件：殖利率 {MIN_YIELD}%~{MAX_YIELD}% | PE < {MAX_PE}\n"
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

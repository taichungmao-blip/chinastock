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
MAX_WORKERS = 15 # 適度降低線程數以求穩定

def fetch_single_stock(symbol, name_map):
    """抓取數據"""
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
    name_map = {}
    
    # 2. 獲取 A 股清單 (目前穩定)
    print("--- 步驟 1: 獲取滬深成分股 ---")
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

    # 3. 獲取港股清單 (改用硬核穩定清單，避開 API 封鎖)
    print("--- 步驟 2: 加載港股核心標的 (HSI/HSCEI) ---")
    # 這裡內建了港股最核心的高息藍籌股代碼
    hk_stable_list = {
        "00005.HK": "匯豐控股", "00939.HK": "建設銀行", "01398.HK": "工商銀行",
        "03988.HK": "中國銀行", "01288.HK": "農業銀行", "00941.HK": "中國移動",
        "00883.HK": "中國海洋石油", "00386.HK": "中國石油化工", "00857.HK": "中國石油股份",
        "02628.HK": "中國人壽", "02318.HK": "中國平安", "00011.HK": "恆生銀行",
        "00002.HK": "中電控股", "00003.HK": "香港中華煤氣", "00006.HK": "電能實業",
        "00012.HK": "恆基兆業地產", "00016.HK": "新鴻基地產", "00017.HK": "新世界發展",
        "00027.HK": "銀河娛樂", "00066.HK": "港鐵公司", "00101.HK": "恆隆地產",
        "00388.HK": "香港交易所", "00688.HK": "中國海外發展", "00700.HK": "騰訊控股",
        "00762.HK": "中國聯通", "00823.HK": "領展房產基金", "00960.HK": "龍湖集團",
        "00992.HK": "聯想集團", "01038.HK": "長江基建集團", "01044.HK": "恆安國際",
        "01088.HK": "中國神華", "01093.HK": "石藥集團", "01109.HK": "華潤置地",
        "01113.HK": "長江實業集團", "01177.HK": "中國生物製藥", "01211.HK": "比亞迪股份",
        "01810.HK": "小米集團", "01928.HK": "金沙中國有限公司", "02020.HK": "安踏體育",
        "02313.HK": "申洲國際", "02319.HK": "蒙牛乳業", "02331.HK": "李寧",
        "02382.HK": "舜宇光學科技", "02688.HK": "新奧能源", "03690.HK": "美團-W",
        "09618.HK": "京東集團-SW", "09988.HK": "阿里巴巴-SW", "09999.HK": "網易-S"
    }
    name_map.update(hk_stable_list)

    codes = list(name_map.keys())
    print(f"✅ 最終掃描範圍：滬深港共 {len(codes)} 隻標的。")

    print(f"--- 步驟 3: Yahoo Finance 並行抓取 ---")
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_stock = {executor.submit(fetch_single_stock, s, name_map): s for s in codes}
        for i, future in enumerate(as_completed(future_to_stock)):
            res = future.result()
            if res: results.append(res)
            if (i+1) % 200 == 0: print(f"進度: {i+1}/{len(codes)}...")

    if results:
        final_df = pd.DataFrame(results).sort_values(by="殖利率(%)", ascending=False)
        send_to_discord(final_df)
    else:
        print("💡 掃描完成，無符合條件標的。")

def send_to_discord(df):
    top_stocks = df.head(25)
    msg = "### 🏮 滬深港三棲價值股監控 (穩定版)\n"
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

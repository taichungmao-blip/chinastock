import akshare as ak
import yfinance as yf
import pandas as pd
import os
import requests

# --- 1. 配置區 ---
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
MIN_YIELD = 4.0  # 4%
MAX_PE = 25.0

def send_discord_notification(stocks_df):
    if not DISCORD_WEBHOOK_URL or stocks_df.empty:
        print("💡 掃描完成，無符合條件標的。")
        return
    
    top_stocks = stocks_df.head(20)
    message_content = "### 🌍 上證 180/380 監控 (Yahoo Finance 國際版)\n"
    message_content += f"篩選標準：殖利率 > {MIN_YIELD}% 且 PE < {MAX_PE}\n"
    message_content += "```\n"
    message_content += f"{'代碼':<10} {'殖利率':<10} {'PE':<6}\n"
    message_content += "-" * 30 + "\n"
    
    for _, row in top_stocks.iterrows():
        # Yahoo Finance 不容易拿中文名稱，我們改顯示代碼
        message_content += f"{row['Symbol']:<10} {row['Yield']:>7.2f}% {row['PE']:>6.1f}\n"
    
    message_content += "```\n"
    message_content += f"> *透過 Yahoo Finance 於 {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')} 更新*"
    
    requests.post(DISCORD_WEBHOOK_URL, json={"content": message_content}, timeout=15)

def run_monitor():
    print("--- 步驟 1: 獲取成分股名單 ---")
    try:
        df_180 = ak.index_stock_cons(symbol="000010")
        df_380 = ak.index_stock_cons(symbol="000009")
        c1 = next(c for c in ['品种代码', 'stock_code', 'code'] if c in df_180.columns)
        c2 = next(c for c in ['品种代码', 'stock_code', 'code'] if c in df_380.columns)
        
        # 轉換為 Yahoo Finance 格式: 600000 -> 600000.SS
        codes = [f"{c}.SS" for c in set(df_180[c1].astype(str).tolist()) | set(df_380[c2].astype(str).tolist())]
        print(f"✅ 成功鎖定 {len(codes)} 隻標的。")
    except Exception as e:
        print(f"❌ 獲取清單失敗: {e}")
        return

    print("--- 步驟 2: 透過 Yahoo Finance 批量下載數據 ---")
    # 為了避免 GitHub 被 Yahoo 封鎖，我們分批次下載 (每批 50 隻)
    results = []
    batch_size = 50
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        print(f"正在抓取第 {i+1} ~ {min(i+batch_size, len(codes))} 隻...")
        
        tickers = yf.Tickers(" ".join(batch))
        for symbol in batch:
            try:
                info = tickers.tickers[symbol].info
                dy = info.get('trailingAnnualDividendYield')
                pe = info.get('trailingPE')
                
                if dy is not None and pe is not None:
                    dy_pct = dy * 100
                    if dy_pct >= MIN_YIELD and 0 < pe <= MAX_PE:
                        results.append({
                            "Symbol": symbol,
                            "Yield": dy_pct,
                            "PE": pe
                        })
            except:
                continue
    
    final_df = pd.DataFrame(results).sort_values(by="Yield", ascending=False)
    print(f"🎯 篩選完成，符合標的: {len(final_df)} 隻。")
    send_discord_notification(final_df)

if __name__ == "__main__":
    run_monitor()

import akshare as ak
import pandas as pd
import requests
import os
import time

# --- 1. 配置區 ---
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
MIN_YIELD = 4.0  
MAX_PE = 25.0
CHECK_PB = True  # 加贈功能：篩選股價低於淨值 (PB < 1)

def send_discord_notification(stocks_df):
    if not DISCORD_WEBHOOK_URL or stocks_df.empty:
        print("💡 掃描完成，無符合條件標的。")
        return
    
    top_stocks = stocks_df.head(20)
    message_content = "### 🛡️ 上證 180/380 監控 (後端優化版)\n"
    message_content += f"篩選：殖利率 > {MIN_YIELD}% | PE < {MAX_PE}"
    message_content += " | PB < 1\n" if CHECK_PB else "\n"
    message_content += "```\n"
    message_content += f"{'名稱':<8} {'代碼':<8} {'殖利率':<8} {'PE':<6} {'PB':<6}\n"
    message_content += "-" * 48 + "\n"
    
    for _, row in top_stocks.iterrows():
        name = str(row['f14'])[:4] # f14 是名稱
        message_content += f"{name:<8} {row['f12']:<8} {row['f108']:>7.2f}% {row['f9']:>6.1f} {row['f23']:>6.2f}\n"
    
    message_content += "```\n"
    message_content += f"> *GitHub Runner 更新於：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}*"
    
    requests.post(DISCORD_WEBHOOK_URL, json={"content": message_content}, timeout=15)

def fetch_eastmoney_direct():
    """模擬瀏覽器直接請求東方財富 API"""
    url = "http://82.push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1", "pz": "5000", "po": "1", "np": "1",
        "ut": "bd1d9ddb040897f1cf462785f39f3d70",
        "fltt": "2", "invt": "2", "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f12,f14,f2,f3,f9,f23,f108", # f12:代碼, f14:名稱, f9:PE, f23:PB, f108:股息率
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "http://quote.eastmoney.com/center/gridlist.html"
    }
    
    print("🚀 正在發送偽裝請求至東方財富數據中心...")
    response = requests.get(url, params=params, headers=headers, timeout=20)
    if response.status_code == 200:
        data = response.json()
        return pd.DataFrame(data['data']['diff'])
    else:
        raise Exception(f"API 請求失敗，狀態碼: {response.status_code}")

def run_monitor():
    try:
        # 1. 獲取成分股名單
        df_180 = ak.index_stock_cons(symbol="000010")
        df_380 = ak.index_stock_cons(symbol="000009")
        c1 = next(c for c in ['品种代码', 'stock_code', 'code'] if c in df_180.columns)
        c2 = next(c for c in ['品种代码', 'stock_code', 'code'] if c in df_380.columns)
        target_codes = set(df_180[c1].astype(str).tolist()) | set(df_380[c2].astype(str).tolist())
        print(f"✅ 已鎖定 180/380 名單，共 {len(target_codes)} 隻。")

        # 2. 直接請求 API
        all_market = fetch_eastmoney_direct()
        
        # 3. 數據過濾
        all_market['f12'] = all_market['f12'].astype(str)
        # 轉數值類型 (f9:PE, f23:PB, f108:股息率)
        for col in ['f9', 'f23', 'f108']:
            all_market[col] = pd.to_numeric(all_market[col], errors='coerce').fillna(0)

        # 篩選邏輯
        mask = (all_market['f12'].isin(target_codes)) & \
               (all_market['f108'] >= MIN_YIELD) & \
               (all_market['f9'] > 0) & (all_market['f9'] <= MAX_PE)
        
        if CHECK_PB:
            mask = mask & (all_market['f23'] < 1.0) & (all_market['f23'] > 0)

        final_list = all_market[mask].sort_values(by="f108", ascending=False)

        print(f"🎯 篩選完成，符合條件標的: {len(final_list)} 隻。")
        send_discord_notification(final_list)

    except Exception as e:
        print(f"❌ 診斷失敗: {e}")

if __name__ == "__main__":
    run_monitor()

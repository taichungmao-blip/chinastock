import akshare as ak
import pandas as pd
import requests
import os
import time
import random

# --- 1. 配置區 ---
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
MIN_YIELD = 4.0
MAX_PE = 25.0

def send_discord_notification(stocks_df):
    if not DISCORD_WEBHOOK_URL or stocks_df.empty:
        print("💡 掃描完成，無符合條件標的。")
        return
    
    top_stocks = stocks_df.head(20)
    message_content = "### 🛡️ 上證 180/380 監控 (穩定版)\n"
    message_content += f"篩選標準：殖利率 > {MIN_YIELD}% 且 PE < {MAX_PE}\n"
    message_content += "```\n"
    message_content += f"{'名稱':<8} {'代碼':<8} {'殖利率':<8} {'PE':<6}\n"
    message_content += "-" * 42 + "\n"
    for _, row in top_stocks.iterrows():
        name = str(row['名稱'])[:4]
        message_content += f"{name:<8} {row['代码']:<8} {row['股息率']:>7.2f}% {row['市盈率']:>6.1f}\n"
    message_content += "```\n"
    message_content += f"> *更新時間：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}*"
    
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": message_content}, timeout=15)
        print("✅ Discord 通知發送成功！")
    except:
        print("❌ Discord 發送失敗")

def get_market_data_with_retry(max_retries=3):
    """具備重試與多源備援的行情抓取函式"""
    for i in range(max_retries):
        try:
            print(f"嘗試抓取行情數據 (第 {i+1} 次)...")
            # 優先嘗試東方財富接口 (數據最齊全)
            df = ak.stock_zh_a_spot_em()
            if not df.empty:
                # 統一欄位名稱
                df = df.rename(columns={'代码': '代码', '名称': '名稱', '股息率': '股息率', '市盈率-动态': '市盈率'})
                return df
        except Exception as e:
            print(f"東方財富接口異常: {e}")
            time.sleep(random.uniform(2, 5)) # 隨機延遲避免被封
            
        try:
            # 備援：嘗試新浪接口
            print("切換至備援接口 (Sina)...")
            df = ak.stock_zh_a_spot()
            if not df.empty:
                # 新浪接口欄位不同，需換算 (假設新浪無直接股息率，可由其他方式估算，或僅作代碼過濾)
                # 這裡僅作示例，如果備援也沒股息率，通常建議直接結束
                return pd.DataFrame() 
        except:
            pass
            
    return pd.DataFrame()

def run_monitor():
    print("--- 步驟 1: 獲取上證 180 & 380 成分股清單 ---")
    try:
        # 獲取名單 (這部分通常較穩定)
        df_180 = ak.index_stock_cons(symbol="000010")
        df_380 = ak.index_stock_cons(symbol="000009")
        
        c1 = next(c for c in ['品种代码', 'stock_code', 'code'] if c in df_180.columns)
        c2 = next(c for c in ['品种代码', 'stock_code', 'code'] if c in df_380.columns)
        
        target_codes = set(df_180[c1].astype(str).tolist()) | set(df_380[c2].astype(str).tolist())
        print(f"成功獲取成分股共 {len(target_codes)} 隻。")
    except Exception as e:
        print(f"❌ 獲取清單失敗: {e}")
        return

    print("--- 步驟 2: 抓取行情並篩選 ---")
    market_df = get_market_data_with_retry()
    
    if market_df.empty:
        print("❌ 無法獲取行情數據，請檢查網路或 API 狀態。")
        return

    # 數據過濾
    market_df['代码'] = market_df['代码'].astype(str)
    my_stocks = market_df[market_df['代码'].isin(target_codes)].copy()
    
    # 數值轉換 (處理百分比與字串問題)
    my_stocks['股息率'] = pd.to_numeric(my_stocks['股息率'], errors='coerce').fillna(0)
    my_stocks['市盈率'] = pd.to_numeric(my_stocks['市盈率'], errors='coerce').fillna(999)

    final_list = my_stocks[
        (my_stocks['股息率'] >= MIN_YIELD) & 
        (my_stocks['市盈率'] > 0) & 
        (my_stocks['市盈率'] <= MAX_PE)
    ].sort_values(by="股息率", ascending=False)

    print(f"篩選完成，共 {len(final_list)} 隻符合條件。")
    send_discord_notification(final_list)

if __name__ == "__main__":
    run_monitor()

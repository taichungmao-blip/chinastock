import akshare as ak
import pandas as pd
import requests
import os
import time

# --- 1. 配置區 ---
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
MIN_YIELD = 4.0  # 篩選門檻 4%
MAX_PE = 25.0    # 篩選門檻 PE 25

def send_discord_notification(stocks_df):
    if not DISCORD_WEBHOOK_URL or stocks_df.empty:
        print("無符合條件標的，不發送通知。")
        return
    
    top_stocks = stocks_df.head(20)
    message_content = "### 🚀 上證 180/380 高殖利率監控 (優化版)\n"
    message_content += f"篩選標準：殖利率 > {MIN_YIELD}% 且 PE < {MAX_PE}\n"
    message_content += "```\n"
    message_content += f"{'名稱':<8} {'代碼':<8} {'殖利率':<8} {'PE':<6}\n"
    message_content += "-" * 42 + "\n"
    for _, row in top_stocks.iterrows():
        name = row['名稱'][:4]
        message_content += f"{name:<8} {row['代碼']:<8} {row['股息率']:>7.2f}% {row['市盈率-动态']:>6.1f}\n"
    message_content += "```\n"
    message_content += f"> *數據更新時間：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}*"
    
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": message_content}, timeout=15)
        print("✅ Discord 通知發送成功！")
    except Exception as e:
        print(f"❌ Discord 發送失敗: {e}")

def run_monitor():
    print("--- 步驟 1: 獲取上證 180 & 380 成分股名單 ---")
    try:
        # 獲取 180 名單
        df_180 = ak.index_stock_cons(symbol="000010")
        code_col_180 = next(c for c in ['品种代码', 'stock_code', 'code'] if c in df_180.columns)
        codes_180 = set(df_180[code_col_180].astype(str).tolist())

        # 獲取 380 名單
        df_380 = ak.index_stock_cons(symbol="000009")
        code_col_380 = next(c for c in ['品种代码', 'stock_code', 'code'] if c in df_380.columns)
        codes_380 = set(df_380[code_col_380].astype(str).tolist())
        
        target_codes = codes_180.union(codes_380)
        print(f"成功獲取成分股共 {len(target_codes)} 隻。")
    except Exception as e:
        print(f"❌ 獲取名單失敗: {e}")
        return

    print("--- 步驟 2: 一次性獲取全市場實時估值數據 ---")
    try:
        # 使用東方財富網的實時數據 (包含股息率和動態 PE)
        # 這個 API 穩定性極高，且一次抓完所有 A 股
        full_market_df = ak.stock_zh_a_spot_em()
        
        # 數據清理與格式化
        full_market_df['代码'] = full_market_df['代码'].astype(str)
        
        # 篩選出屬於 180/380 的股票
        my_stocks = full_market_df[full_market_df['代码'].isin(target_codes)].copy()
        
        # 強制轉換數值，並處理缺失值
        my_stocks['股息率'] = pd.to_numeric(my_stocks['股息率'], errors='coerce').fillna(0)
        my_stocks['市盈率-动态'] = pd.to_numeric(my_stocks['市盈率-动态'], errors='coerce').fillna(999)

        # 執行篩選邏輯
        # 注意：此處 '股息率' 通常已是百分比格式 (例如 5.4 代表 5.4%)
        final_list = my_stocks[
            (my_stocks['股息率'] >= MIN_YIELD) & 
            (my_stocks['市盈率-动态'] > 0) & 
            (my_stocks['市盈率-动态'] <= MAX_PE)
        ].copy()

        # 排序
        final_list = final_list.sort_values(by="股息率", ascending=False)
        
        print(f"分析完成！符合條件標的: {len(final_list)} 隻。")
        
        # 診斷：印出前兩隻看看數據格式
        if not my_stocks.empty:
            test_row = my_stocks.iloc[0]
            print(f"🔍 [診斷] 第一隻標的({test_row['名称']}): 股息率={test_row['股息率']}, PE={test_row['市盈率-动态']}")

        send_discord_notification(final_list)

    except Exception as e:
        print(f"❌ 處理行情數據發生錯誤: {e}")

if __name__ == "__main__":
    run_monitor()

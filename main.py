import akshare as ak
import pandas as pd
import time
import requests
import json
import os
# 修改配置區，從系統環境變數讀取
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
# --- 配置區 ---
DISCORD_WEBHOOK_URL = "你的_DISCORD_WEBHOOK_網址"
MIN_YIELD = 6.0  # 殖利率門檻 (%)
MAX_PE = 20.0    # 市盈率上限 (排除估值過高的股票)

def send_discord_notification(stocks_df):
    if stocks_df.empty:
        print("沒有符合篩選條件的股票，不發送通知。")
        return

    # 構建 Discord 訊息內容 (Markdown 格式)
    message_content = "### 🚀 上證 180/380 高殖利率監控清單\n"
    message_content += f"篩選條件：殖利率 > {MIN_YIELD}% 且 PE < {MAX_PE}\n"
    message_content += "```\n"
    message_content += f"{'名稱':<8} {'代碼':<8} {'殖利率':<8} {'PE':<6} {'來源':<8}\n"
    message_content += "-" * 45 + "\n"
    
    # 只取前 10 名發送，避免訊息過長
    for _, row in stocks_df.head(10).iterrows():
        message_content += f"{row['股票名稱']:<8} {row['股票代碼']:<8} {row['殖利率(%)']:>7.2f}% {row['市盈率(PE)']:>6.1f} {row['所屬指數']:<8}\n"
    
    message_content += "```\n"
    message_content += f"> *更新時間：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}*"

    payload = {"content": message_content}
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload)
        if response.status_code == 204:
            print("Discord 通知發送成功！")
        else:
            print(f"發送失敗，狀態碼：{response.status_code}")
    except Exception as e:
        print(f"發送通知時發生錯誤: {e}")

def run_monitor():
    # 1. 獲取成分股 (簡化邏輯以便示範)
    target_indices = {"000010": "上證180", "000009": "上證380"}
    all_results = []

    for idx_code, idx_name in target_indices.items():
        print(f"抓取 {idx_name} 中...")
        cons_df = ak.index_stock_cons(symbol=idx_code)
        
        for _, row in cons_df.iterrows():
            code = row['code']
            try:
                # 抓取估值
                indicator_df = ak.stock_a_lg_indicator(symbol=code)
                if not indicator_df.empty:
                    latest = indicator_df.iloc[-1]
                    # 2. 執行過濾邏輯
                    dy = latest["dv_ratio"]
                    pe = latest["pe"]
                    
                    if dy >= MIN_YIELD and pe <= MAX_PE:
                        all_results.append({
                            "股票代碼": code,
                            "股票名稱": row['name'],
                            "所屬指數": idx_name,
                            "殖利率(%)": dy,
                            "市盈率(PE)": pe
                        })
            except:
                continue
            time.sleep(0.1) # 避免 API 限制

    # 3. 排序並發送通知
    final_df = pd.DataFrame(all_results).sort_values(by="殖利率(%)", ascending=False)
    send_discord_notification(final_df)

if __name__ == "__main__":
    run_monitor()

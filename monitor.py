import akshare as ak
import pandas as pd
import time
import requests
import os

# --- 1. 配置區 ---
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

def send_discord_notification(stocks_df):
    if not DISCORD_WEBHOOK_URL:
        print("錯誤：找不到 Webhook。")
        return
    
    # 這裡我們不篩選，直接取前 10 隻作為測試
    top_stocks = stocks_df.head(10)
    
    message_content = "### 🚀 Discord 連線測試成功！\n"
    message_content += "這是目前的上證 180/380 部分清單（無篩選測試）：\n"
    message_content += "```\n"
    message_content += f"{'名稱':<8} {'代碼':<8} {'殖利率':<8} {'PE':<6}\n"
    message_content += "-" * 40 + "\n"
    
    for _, row in top_stocks.iterrows():
        name = row['股票名稱'][:4]
        message_content += f"{name:<8} {row['股票代碼']:<8} {row['殖利率(%)']:>7.2f}% {row['市盈率(PE)']:>6.1f}\n"
    
    message_content += "```\n"
    message_content += f"> *測試運行時間：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}*"

    try:
        res = requests.post(DISCORD_WEBHOOK_URL, json={"content": message_content}, timeout=15)
        print(f"Discord 發送狀態: {res.status_code}")
    except Exception as e:
        print(f"發送失敗: {e}")

def run_monitor():
    target_indices = {"000010": "上證180"} # 先抓一個指數測試速度
    all_results = []

    for idx_code, idx_name in target_indices.items():
        print(f"--- 測試抓取 {idx_name} ---")
        try:
            cons_df = ak.index_stock_cons(symbol=idx_code)
            code_col = next((c for c in ['品种代码', 'stock_code', 'code'] if c in cons_df.columns), None)
            name_col = next((c for c in ['品种名称', 'stock_name', 'name'] if c in cons_df.columns), None)

            # 測試前 20 隻就好，節省測試時間
            test_subset = cons_df.head(20)

            for i, (_, row) in enumerate(test_subset.iterrows()):
                code = str(row[code_col])
                name = str(row[name_col]) if name_col else "N/A"
                
                try:
                    indicator_df = ak.stock_a_lg_indicator(symbol=code)
                    if not indicator_df.empty:
                        latest = indicator_df.iloc[-1]
                        dy = latest["dv_ratio"]
                        pe = latest["pe"]
                        
                        # 核心偵錯：打印數據值
                        if i < 3:
                            print(f"🔍 診斷數據 [{name} {code}]: 殖利率={dy}, PE={pe}")

                        all_results.append({
                            "股票代碼": code,
                            "股票名稱": name,
                            "所屬指數": idx_name,
                            "殖利率(%)": dy,
                            "市盈率(PE)": pe
                        })
                except:
                    continue
                time.sleep(0.1)

        except Exception as e:
            print(f"錯誤: {e}")

    if all_results:
        final_df = pd.DataFrame(all_results)
        send_discord_notification(final_df)

if __name__ == "__main__":
    run_monitor()

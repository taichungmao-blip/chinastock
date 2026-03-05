import akshare as ak
import pandas as pd
import time
import requests
import os

# --- 1. 配置區 (測試用放寬條件) ---
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
MIN_YIELD = 4.0  # 從 5.0 降至 4.0
MAX_PE = 20.0    # 從 15.0 放寬至 20.0

def send_discord_notification(stocks_df):
    if not DISCORD_WEBHOOK_URL:
        print("錯誤：找不到 DISCORD_WEBHOOK_URL。")
        return
    if stocks_df.empty:
        print("💡 掃描完成，但無符合條件的股票。")
        return

    # 顯示前 15 名
    top_stocks = stocks_df.head(15)
    
    message_content = "### 🧪 測試報表：上證 180/380 監控\n"
    message_content += f"篩選標準：殖利率 > {MIN_YIELD}% 且 PE < {MAX_PE}\n"
    message_content += "```\n"
    message_content += f"{'名稱':<8} {'代碼':<8} {'殖利率':<8} {'PE':<6} {'來源':<8}\n"
    message_content += "-" * 45 + "\n"
    
    for _, row in top_stocks.iterrows():
        # 截斷過長的名稱以保持排版
        name = row['股票名稱'][:4] 
        message_content += f"{name:<8} {row['股票代碼']:<8} {row['殖利率(%)']:>7.2f}% {row['市盈率(PE)']:>6.1f} {row['所屬指數']:<8}\n"
    
    message_content += "```\n"
    message_content += f"> *測試運行時間：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}*"

    try:
        res = requests.post(DISCORD_WEBHOOK_URL, json={"content": message_content}, timeout=15)
        if res.status_code == 204:
            print("✅ Discord 通知發送成功！")
        else:
            print(f"❌ Discord 發送失敗，狀態碼：{res.status_code}")
    except Exception as e:
        print(f"❌ 發送 Discord 時發生異常: {e}")

def run_monitor():
    target_indices = {"000010": "上證180", "000009": "上證380"}
    all_results = []

    for idx_code, idx_name in target_indices.items():
        print(f"--- 正在處理 {idx_name} ({idx_code}) ---")
        try:
            cons_df = ak.index_stock_cons(symbol=idx_code)
            
            # 動態識別欄位 (包含之前噴錯的 '品种代码')
            code_col = next((c for c in ['品种代码', 'stock_code', 'code', '代码', '证券代码'] if c in cons_df.columns), None)
            name_col = next((c for c in ['品种名称', 'stock_name', 'name', '名称', '证券简称'] if c in cons_df.columns), None)

            if not code_col:
                print(f"❌ 找不到代碼欄位。現有欄位：{cons_df.columns.tolist()}")
                continue

            print(f"✅ 成功辨識欄位，開始分析 {len(cons_df)} 隻標的...")

            for i, (_, row) in enumerate(cons_df.iterrows()):
                code = str(row[code_col])
                name = str(row[name_col]) if name_col else "N/A"
                
                try:
                    indicator_df = ak.stock_a_lg_indicator(symbol=code)
                    if not indicator_df.empty:
                        latest = indicator_df.iloc[-1]
                        dy = latest["dv_ratio"]
                        pe = latest["pe"]
                        
                        # 測試用過濾邏輯
                        if dy >= MIN_YIELD and 0 < pe <= MAX_PE:
                            all_results.append({
                                "股票代碼": code,
                                "股票名稱": name,
                                "所屬指數": idx_name,
                                "殖利率(%)": dy,
                                "市盈率(PE)": pe
                            })
                except:
                    continue
                
                if (i + 1) % 50 == 0:
                    print(f"進度：已處理 {i+1}/{len(cons_df)}...")
                time.sleep(0.15) 

        except Exception as e:
            print(f"❌ 錯誤: {e}")

    if all_results:
        final_df = pd.DataFrame(all_results).sort_values(by="殖利率(%)", ascending=False)
        send_discord_notification(final_df)
    else:
        print("💡 掃描完成，符合條件的股票數量為 0。")

if __name__ == "__main__":
    run_monitor()

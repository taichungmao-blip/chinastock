import akshare as ak
import pandas as pd
import time
import requests
import os

# --- 1. 配置區 ---
# 從 GitHub Secrets / 環境變數讀取 Webhook
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
MIN_YIELD = 5.0  # 殖利率門檻 (%)
MAX_PE = 15.0    # 市盈率上限

def send_discord_notification(stocks_df):
    """將結果格式化並發送到 Discord"""
    if not DISCORD_WEBHOOK_URL:
        print("錯誤：找不到 DISCORD_WEBHOOK_URL 環境變數。")
        return

    if stocks_df.empty:
        print("今日無符合篩選條件的股票。")
        return

    # 構建 Discord 訊息
    message_content = "### 📊 上證 180/380 高殖利率監控報表\n"
    message_content += f"篩選標準：殖利率 > {MIN_YIELD}% 且 PE < {MAX_PE}\n"
    message_content += "```\n"
    message_content += f"{'名稱':<8} {'代碼':<8} {'殖利率':<8} {'PE':<6} {'來源':<8}\n"
    message_content += "-" * 45 + "\n"
    
    # 取前 15 名發送
    for _, row in stocks_df.head(15).iterrows():
        message_content += f"{row['股票名稱']:<8} {row['股票代碼']:<8} {row['殖利率(%)']:>7.2f}% {row['市盈率(PE)']:>6.1f} {row['所屬指數']:<8}\n"
    
    message_content += "```\n"
    message_content += f"> *數據抓取時間：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}*"

    payload = {"content": message_content}
    try:
        res = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        if res.status_code == 204:
            print("Discord 通知發送成功！")
        else:
            print(f"Discord 發送失敗，狀態碼：{res.status_code}")
    except Exception as e:
        print(f"發送 Discord 時發生異常: {e}")

def run_monitor():
    target_indices = {"000010": "上證180", "000009": "上證380"}
    all_results = []

    for idx_code, idx_name in target_indices.items():
        print(f"--- 正在處理 {idx_name} ({idx_code}) ---")
        try:
            # 1. 獲取成分股
            cons_df = ak.index_stock_cons(symbol=idx_code)
            
            # 2. 動態識別欄位名稱 (解決 KeyError: 'code' 的關鍵)
            code_col = next((c for c in ['stock_code', 'code', '代码', '证券代码'] if c in cons_df.columns), None)
            name_col = next((c for c in ['stock_name', 'name', '名称', '证券简称'] if c in cons_df.columns), None)

            if not code_col:
                print(f"警告：無法在 {idx_name} 中找到代碼欄位，欄位清單：{cons_df.columns.tolist()}")
                continue

            print(f"找到 {len(cons_df)} 隻股票，開始分析...")

            for i, (_, row) in enumerate(cons_df.iterrows()):
                code = str(row[code_col])
                name = str(row[name_col]) if name_col else "N/A"
                
                try:
                    # 3. 獲取估值數據
                    indicator_df = ak.stock_a_lg_indicator(symbol=code)
                    if not indicator_df.empty:
                        latest = indicator_df.iloc[-1]
                        dy = latest["dv_ratio"]
                        pe = latest["pe"]
                        
                        # 4. 執行過濾邏輯 (過濾掉 PE <= 0 的異常值)
                        if dy >= MIN_YIELD and 0 < pe <= MAX_PE:
                            all_results.append({
                                "股票代碼": code,
                                "股票名稱": name,
                                "所屬指數": idx_name,
                                "殖利率(%)": dy,
                                "市盈率(PE)": pe
                            })
                except Exception:
                    continue # 忽略單一股票錯誤
                
                # 進度顯示與頻率限制
                if (i + 1) % 50 == 0:
                    print(f"已處理 {i+1} 隻股票...")
                time.sleep(0.15) 

        except Exception as e:
            print(f"抓取指數 {idx_name} 時發生嚴重錯誤: {e}")

    # 5. 整理並發送
    if all_results:
        final_df = pd.DataFrame(all_results).sort_values(by="殖利率(%)", ascending=False)
        send_discord_notification(final_df)
    else:
        print("最終無任何符合條件的結果。")

if __name__ == "__main__":
    run_monitor()

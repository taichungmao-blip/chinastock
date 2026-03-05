import akshare as ak
import pandas as pd
import time
import requests
import os

# --- 1. 配置區 ---
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
MIN_YIELD = 4.0  # 門檻設為 4%
MAX_PE = 20.0    # PE 門檻設為 20

def send_discord_notification(stocks_df):
    if not DISCORD_WEBHOOK_URL:
        return
    
    if stocks_df.empty:
        print("💡 今日無符合條件的股票。")
        return

    # 取前 15 名發送
    top_stocks = stocks_df.head(15)
    
    message_content = "### 📈 上證 180/380 監控報表 (正式版)\n"
    message_content += f"篩選標準：殖利率 > {MIN_YIELD}% 且 PE < {MAX_PE}\n"
    message_content += "```\n"
    message_content += f"{'名稱':<8} {'代碼':<8} {'殖利率':<8} {'PE':<6}\n"
    message_content += "-" * 42 + "\n"
    
    for _, row in top_stocks.iterrows():
        name = row['股票名稱'][:4]
        message_content += f"{name:<8} {row['股票代碼']:<8} {row['殖利率(%)']:>7.2f}% {row['市盈率(PE)']:>6.1f}\n"
    
    message_content += "```\n"
    message_content += f"> *數據抓取時間：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}*"

    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": message_content}, timeout=15)
    except:
        pass

def run_monitor():
    target_indices = {"000010": "上證180", "000009": "上證380"}
    all_results = []

    for idx_code, idx_name in target_indices.items():
        print(f"--- 正在處理 {idx_name} ---")
        try:
            cons_df = ak.index_stock_cons(symbol=idx_code)
            code_col = next((c for c in ['品种代码', 'stock_code', 'code'] if c in cons_df.columns), None)
            name_col = next((c for c in ['品种名称', 'stock_name', 'name'] if c in cons_df.columns), None)

            if not code_col: continue

            for i, (_, row) in enumerate(cons_df.iterrows()):
                code = str(row[code_col])
                name = str(row[name_col]) if name_col else "N/A"
                
                try:
                    # 修正後的函式名稱: stock_a_indicator_lg
                    indicator_df = ak.stock_a_indicator_lg(symbol=code)
                    
                    if not indicator_df.empty:
                        latest = indicator_df.iloc[-1]
                        dy = latest["dv_ratio"]
                        pe = latest["pe"]
                        
                        # 篩選邏輯
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
                
                # 節流，每 50 筆輸出一次進度
                if (i + 1) % 50 == 0:
                    print(f"已處理 {idx_name}: {i+1} 隻...")
                time.sleep(0.12)

        except Exception as e:
            print(f"處理 {idx_name} 出錯: {e}")

    if all_results:
        final_df = pd.DataFrame(all_results).sort_values(by="殖利率(%)", ascending=False)
        send_discord_notification(final_df)
    else:
        print("💡 掃描完成，今日無標的。")

if __name__ == "__main__":
    run_monitor()

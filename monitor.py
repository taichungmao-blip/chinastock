import akshare as ak
import pandas as pd
import time
import requests
import os

# --- 1. 配置區 ---
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
MIN_YIELD = 4.0  # 目標 4%
MAX_PE = 25.0    # 稍微放寬 PE 限制

def send_discord_notification(stocks_df):
    if not DISCORD_WEBHOOK_URL or stocks_df.empty:
        return
    
    top_stocks = stocks_df.head(15)
    message_content = "### 📊 上證 180/380 監控報表\n"
    message_content += f"篩選標準：殖利率 > {MIN_YIELD}% 且 PE < {MAX_PE}\n"
    message_content += "```\n"
    message_content += f"{'名稱':<8} {'代碼':<8} {'殖利率':<8} {'PE':<6}\n"
    message_content += "-" * 42 + "\n"
    for _, row in top_stocks.iterrows():
        name = row['股票名稱'][:4]
        message_content += f"{name:<8} {row['股票代碼']:<8} {row['殖利率(%)']:>7.2f}% {row['市盈率(PE)']:>6.1f}\n"
    message_content += "```\n"
    message_content += f"> *更新時間：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}*"
    requests.post(DISCORD_WEBHOOK_URL, json={"content": message_content}, timeout=15)

def run_monitor():
    target_indices = {"000010": "上證180", "000009": "上證380"}
    all_results = []

    for idx_code, idx_name in target_indices.items():
        print(f"--- 正在處理 {idx_name} ---")
        try:
            cons_df = ak.index_stock_cons(symbol=idx_code)
            code_col = next((c for c in ['品种代码', 'stock_code', 'code'] if c in cons_df.columns), None)
            name_col = next((c for c in ['品种名称', 'stock_name', 'name'] if c in cons_df.columns), None)

            for i, (_, row) in enumerate(cons_df.iterrows()):
                code = str(row[code_col])
                name = str(row[name_col]) if name_col else "N/A"
                
                try:
                    # 使用正確的最新函式名
                    indicator_df = ak.stock_a_indicator_lg(symbol=code)
                    if not indicator_df.empty:
                        latest = indicator_df.iloc[-1]
                        dy = float(latest["dv_ratio"])
                        pe = float(latest["pe"])
                        
                        # --- 核心診斷：打印前兩隻股票的原始數據 ---
                        if i < 2:
                            print(f"🔍 [診斷] {name}({code}): 原始殖利率={dy}, PE={pe}")
                        
                        # --- 自動適應單位 ---
                        # 如果 API 回傳 0.05 代表 5%，我們自動乘以 100
                        actual_dy = dy if dy > 0.5 else dy * 100
                        
                        if actual_dy >= MIN_YIELD and 0 < pe <= MAX_PE:
                            all_results.append({
                                "股票代碼": code,
                                "股票名稱": name,
                                "所屬指數": idx_name,
                                "殖利率(%)": actual_dy,
                                "市盈率(PE)": pe
                            })
                except:
                    continue
                time.sleep(0.1)
            print(f"完成 {idx_name}，符合條件數: {len(all_results)}")
        except Exception as e:
            print(f"發生錯誤: {e}")

    if all_results:
        final_df = pd.DataFrame(all_results).sort_values(by="殖利率(%)", ascending=False)
        send_discord_notification(final_df)
        print(f"✅ 成功！已發送 {len(final_df)} 隻股票到 Discord。")
    else:
        print("💡 掃描完成，但最終沒有符合條件的股票。")

if __name__ == "__main__":
    run_monitor()

import os
import requests
import akshare as ak
import pandas as pd

# 1. 立即檢查 Webhook
WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL")

def log_to_discord(msg):
    print(f"DEBUG: {msg}")
    if WEBHOOK:
        requests.post(WEBHOOK, json={"content": f"📢 {msg}"})

log_to_discord("腳本啟動，開始診斷連線...")

try:
    # 2. 測試獲取 180 指數
    print("正在呼叫 ak.index_stock_cons...")
    df = ak.index_stock_cons(symbol="000010")
    log_to_discord(f"成功獲取清單！共有 {len(df)} 隻股票。")
    
    # 3. 測試第一隻股票的數據
    first_code = str(df.iloc[0, 0])
    print(f"正在測試抓取代碼: {first_code}")
    indicator_df = ak.stock_a_lg_indicator(symbol=first_code)
    
    if not indicator_df.empty:
        val = indicator_df.iloc[-1]
        log_to_discord(f"數據抓取測試成功！{first_code}: 殖利率={val['dv_ratio']}, PE={val['pe']}")
    else:
        log_to_discord("錯誤：抓到的估值表是空的。")

except Exception as e:
    log_to_discord(f"❌ 診斷過程發生崩潰: {str(e)}")

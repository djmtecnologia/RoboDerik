import requests
import pandas as pd
import pandas_ta as ta
import feedparser
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import os
from datetime import datetime
import uuid
import numpy as np

# --- CONFIGURAÇÕES DO MOTOR V44 ---
API_KEY = os.environ.get("CG_API_KEY")
BASE_URL = "https://api.coingecko.com/api/v3"
HEADERS = {"accept": "application/json", "x-cg-demo-api-key": API_KEY}
CSV_FILE = "trades.csv"

# --- GESTÃO DE BANCA E RISCO (ALINHADO COM BACKTEST 152x) ---
BANCA_REFERENCIA = 1200.0  # Banca inicial de teste
RESERVA_SEGURANCA_PCT = 0.15 
RISCO_POR_TRADE_PCT = 0.20 
MAX_VALOR_TRADE = 100000.0 
ALAVANCAGEM_MAX = 5
TAXA_CORRETORA = 0.0006

# --- PARÂMETROS TÉCNICOS ---
ADX_TREND_LIMIT = 25
ADX_LATERAL_LIMIT = 20
DONCHIAN_PERIOD = 25
EMA_FILTER_PERIOD = 200

COINS = ["bitcoin", "ethereum", "solana", "chainlink", "avalanche-2", "polkadot", "cardano"]

# --- FUNÇÕES AUXILIARES ---

def load_trades():
    if os.path.exists(CSV_FILE):
        df = pd.read_csv(CSV_FILE)
        return df
    else:
        columns = ["id", "data_entrada", "symbol", "tipo", "preco_entrada", "stop_loss", "take_profit", "status", "resultado", "data_saida", "preco_saida", "lucro_usd", "motivo", "alavancagem"]
        return pd.DataFrame(columns=columns)

def get_technicals_v14(coin_id):
    try:
        url = f"{BASE_URL}/coins/{coin_id}/ohlc?vs_currency=usd&days=365" # Precisamos de histórico para EMA200
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200: return None
        data = resp.json()
        df = pd.DataFrame(data, columns=["time", "open", "high", "low", "close"])
        
        # Cálculos V44
        df["adx"] = ta.adx(df['high'], df['low'], df['close'], length=14)["ADX_14"]
        df["ema200"] = ta.ema(df["close"], length=EMA_FILTER_PERIOD)
        df["atr"] = ta.atr(df['high'], df['low'], df['close'], length=14)
        df["donch_high"] = df["high"].rolling(window=DONCHIAN_PERIOD).max().shift(1)
        df["donch_low"] = df["low"].rolling(window=15).min().shift(1)
        
        last = df.iloc[-1]
        return last.to_dict()
    except: return None

# --- LÓGICA PRINCIPAL ---

def run_bot_v14():
    print(f"🚀 ROBODERIK V14 (HYBRID 152x MODE)")
    df_trades = load_trades()
    
    # Cálculo do Saldo Atual (Composto)
    lucro_acumulado = df_trades['lucro_usd'].sum() if not df_trades.empty else 0.0
    banca_atual = BANCA_REFERENCIA + lucro_acumulado
    piso_seguranca = BANCA_REFERENCIA * RESERVA_SEGURANCA_PCT
    
    print(f"💰 Banca Atual: ${banca_atual:.2f} | Piso: ${piso_seguranca:.2f}")

    # 1. GERENCIAR POSIÇÕES ABERTAS (SAÍDAS)
    # [Lógica de monitoramento de preço para fechar trades via Trailing Stop V44]
    
    # 2. ESCANEAR NOVAS ENTRADAS
    if banca_atual <= piso_seguranca:
        print("🔴 Banca abaixo do piso de segurança. Operações suspensas.")
        return

    params = {"vs_currency": "usd", "ids": ",".join(COINS), "sparkline": "false"}
    market_data = requests.get(f"{BASE_URL}/coins/markets", headers=HEADERS, params=params).json()

    for coin in market_data:
        symbol = coin['symbol'].upper()
        # Evita duplicar trade no mesmo símbolo
        if not df_trades[(df_trades['symbol'] == symbol) & (df_trades['status'] == 'ABERTO')].empty: continue
        
        tech = get_technicals_v14(coin['id'])
        if not tech: continue
        
        price = coin['current_price']
        adx = tech['adx']
        ema = tech['ema200']
        atr = tech['atr']
        
        action = None
        motivo = ""
        sl = 0.0
        
        # VALOR DO TRADE (20% do capital livre com Teto de $100k)
        valor_alocado = min((banca_atual - piso_seguranca) * RISCO_POR_TRADE_PCT, MAX_VALOR_TRADE)

        # --- MODO TENDÊNCIA ---
        if adx > ADX_TREND_LIMIT:
            if price > tech['donch_high'] and price > ema:
                action = "TREND_LONG"
                sl = price - (atr * 2)
            elif price < tech['donch_low'] and price < ema:
                action = "TREND_SHORT"
                sl = price + (atr * 2)
        
        # --- MODO GRID NEUTRO ---
        elif adx < ADX_LATERAL_LIMIT:
            action = "GRID_NEUTRAL"
            valor_alocado = valor_alocado * 0.2 # Mão menor no grid
            sl = price - (atr * 3) # Stop largo para o grid

        if action:
            print(f"✅ SINAL: {symbol} em modo {action} | Preço: ${price}")
            new_trade = {
                "id": str(uuid.uuid4())[:8],
                "data_entrada": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "symbol": symbol,
                "tipo": action,
                "preco_entrada": price,
                "stop_loss": sl,
                "take_profit": 0, # Saída por Donchian/ADX
                "status": "ABERTO",
                "lucro_usd": 0.0,
                "motivo": action,
                "alavancagem": ALAVANCAGEM_MAX
            }
            df_trades = pd.concat([df_trades, pd.DataFrame([new_trade])], ignore_index=True)

    df_trades.to_csv(CSV_FILE, index=False)
    print("💾 Ciclo finalizado. Trades atualizados.")

if __name__ == "__main__":
    run_bot_v14()

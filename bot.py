import sys
import subprocess
import os

# --- AUTO-INSTALAÇÃO DE DEPENDÊNCIAS ---
def install(package):
    try: __import__(package)
    except ImportError:
        map_lib = {"vaderSentiment": "vaderSentiment", "feedparser": "feedparser", "pandas_ta": "pandas_ta", "pytz": "pytz", "requests": "requests", "pandas": "pandas"}
        subprocess.check_call([sys.executable, "-m", "pip", "install", map_lib.get(package, package)])

libs = ["pytz", "pandas_ta", "vaderSentiment", "feedparser", "requests", "pandas"]
for lib in libs: install(lib)

import requests
import pandas as pd
import pandas_ta as ta
import feedparser
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from datetime import datetime
import uuid
import pytz
import numpy as np

# --- CONFIGURAÇÕES ---
API_KEY = os.environ.get("CG_API_KEY")
BASE_URL = "https://api.coingecko.com/api/v3"
HEADERS = {"accept": "application/json", "x-cg-demo-api-key": API_KEY}
CSV_FILE = "trades.csv"

try: FUSO = pytz.timezone('America/Sao_Paulo')
except: FUSO = pytz.utc 

# --- GESTÃO DE BANCA ---
BANCA_INICIAL_REAL = 1200.0  
RESERVA_SEGURANCA_PCT = 0.15 
RISCO_POR_TRADE_PCT = 0.20   
MAX_VALOR_TRADE = 100000.0   
ALAVANCAGEM_PADRAO = 5 

# --- PARÂMETROS TÉCNICOS ---
ADX_TREND_LIMIT = 25
ADX_LATERAL_LIMIT = 20
EMA_FILTER = 200
DONCHIAN_PERIOD = 25

RSS_FEEDS = ["https://cointelegraph.com/rss", "https://www.coindesk.com/arc/outboundfeeds/rss/"]
COINS_IDS = ["bitcoin", "ethereum", "solana", "chainlink", "avalanche-2", "polkadot", "cardano"]

# --- FUNÇÕES ---

def get_now_str(): return datetime.now(FUSO).strftime("%d/%m/%Y %H:%M:%S")
def get_current_month(): return datetime.now(FUSO).strftime('%Y-%m')

def load_trades():
    if os.path.exists(CSV_FILE):
        df = pd.read_csv(CSV_FILE)
        if 'mes_referencia' not in df.columns:
            df['mes_referencia'] = get_current_month()
        return df
    columns = ["id", "data_entrada", "symbol", "tipo", "preco_entrada", "stop_loss", "status", "resultado", "data_saida", "preco_saida", "lucro_usd", "motivo", "alavancagem", "mes_referencia"]
    return pd.DataFrame(columns=columns)

def analyze_news():
    analyzer = SentimentIntensityAnalyzer()
    max_impact_abs = 0; top_score = 0; top_headline = ""
    print("\n📰 ANALISANDO NOTÍCIAS (GRAVIDADE)...")
    try:
        for url in RSS_FEEDS:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                score = analyzer.polarity_scores(entry.title)['compound']
                if abs(score) > max_impact_abs:
                    max_impact_abs = abs(score); top_score = score; top_headline = entry.title
        return top_score, top_headline
    except: return 0, ""

# NOVA LÓGICA DE ZONAS (V17)
def get_sentiment_zone(score):
    """Retorna: (Nome da Zona, Permissao, Alavancagem Multiplier, Stop Multiplier)"""
    if score <= -0.6:
        return "🌪️ PÂNICO EXTREMO", "SHORT_ONLY", 1.0, 3.0 # Alavancagem Max, Stop Largo
    elif -0.6 < score <= -0.2:
        return "🐻 VIÉS DE BAIXA", "BIAS_SHORT", 0.8, 2.0  # Alavancagem Reduzida, Stop Normal
    elif -0.2 < score < 0.2:
        return "⚪ NEUTRO/RUÍDO", "ALL", 1.0, 2.0         # Normal
    elif 0.2 <= score < 0.6:
        return "🐮 VIÉS DE ALTA", "BIAS_LONG", 0.8, 2.0    # Alavancagem Reduzida
    elif score >= 0.6:
        return "🚀 EUFORIA EXTREMA", "LONG_ONLY", 1.0, 3.0 # Alavancagem Max
    return "⚪ NEUTRO", "ALL", 1.0, 2.0

def get_technicals(coin_id):
    try:
        url = f"{BASE_URL}/coins/{coin_id}/ohlc?vs_currency=usd&days=365"
        resp = requests.get(url, headers=HEADERS, timeout=10).json()
        df = pd.DataFrame(resp, columns=["time", "open", "high", "low", "close"])
        df["adx"] = ta.adx(df['high'], df['low'], df['close'], length=14)["ADX_14"]
        df["ema200"] = ta.ema(df["close"], length=EMA_FILTER)
        df["atr"] = ta.atr(df['high'], df['low'], df['close'], length=14)
        df["d_high"] = df['high'].rolling(window=DONCHIAN_PERIOD).max().shift(1)
        df["d_low"] = df['low'].rolling(window=15).min().shift(1)
        return df.iloc[-1].to_dict()
    except: return None

# --- CORE V17 ---

def run_bot_v17():
    data_hora = get_now_str()
    print(f"🚀 ROBODERIK V17 (GRAVITY ZONES) | {data_hora}")
    df = load_trades()
    
    lucro_total = df['lucro_usd'].sum() if not df.empty else 0.0
    banca_atual = BANCA_INICIAL_REAL + lucro_total
    piso_seguranca = BANCA_INICIAL_REAL * RESERVA_SEGURANCA_PCT
    
    print(f"\n🏆 --- DASHBOARD DE PERFORMANCE ---")
    print(f"   💰 Banca Atual:   ${banca_atual:.2f} (Piso: ${piso_seguranca:.2f})")
    print("-" * 40)

    # 1. Classificação de Gravidade
    score, manchete = analyze_news()
    zone_name, permission, lev_mult, stop_mult = get_sentiment_zone(score)
    
    print(f"📊 NOTÍCIA MAIS FORTE: {score:.2f}")
    print(f"   ⚠️ Manchete: {manchete[:70]}...")
    print(f"   🌡️ ZONA: {zone_name}")
    print(f"   🔒 PERMISSÃO: {permission}")

    print("\n📡 ESCANEANDO MERCADO...")
    params = {"vs_currency": "usd", "ids": ",".join(COINS_IDS), "sparkline": "false"}
    try: market = requests.get(f"{BASE_URL}/coins/markets", headers=HEADERS, params=params).json()
    except: return

    for coin in market:
        sym = coin['symbol'].upper()
        if not df[(df['symbol'] == sym) & (df['status'] == 'ABERTO')].empty:
            print(f"   🟡 {sym:<5}: Posição Aberta.")
            continue
        
        tech = get_technicals(coin['id'])
        if not tech: continue
        
        price = coin['current_price']
        adx, ema, d_high, d_low, atr = tech['adx'], tech['ema200'], tech['d_high'], tech['d_low'], tech['atr']
        
        action, motivo, sl = None, "", 0.0
        
        # --- FILTRO HÍBRIDO BASEADO NA ZONA ---
        
        # A. MERCADO LATERAL (GRID)
        # Só opera Grid se estiver na Zona Neutra (Ruído). Nas outras, é perigoso.
        if adx < ADX_LATERAL_LIMIT and permission == "ALL":
            action = "GRID_NEUTRAL"
            motivo = "Grid Lateral (Zona Neutra)"
            sl = price - (atr * 3)

        # B. TENDÊNCIA DE ALTA (LONG)
        elif price > d_high and price > ema and adx > ADX_TREND_LIMIT:
            if permission in ["ALL", "BIAS_LONG", "LONG_ONLY"]:
                action = "TREND_LONG"
                motivo = f"Rompimento Alta ({zone_name})"
                sl = price - (atr * stop_mult)
            else:
                motivo = f"Setup Long ignorado (Zona {permission})"

        # C. TENDÊNCIA DE BAIXA (SHORT)
        elif price < d_low and price < ema and adx > ADX_TREND_LIMIT:
            if permission in ["ALL", "BIAS_SHORT", "SHORT_ONLY"]:
                action = "TREND_SHORT"
                motivo = f"Rompimento Baixa ({zone_name})"
                sl = price + (atr * stop_mult)
            else:
                motivo = f"Setup Short ignorado (Zona {permission})"
        
        # D. SNIPER DE NOTÍCIA (SEMPRE ENTRA SE O PREÇO CONFIRMAR O SENTIMENTO)
        elif permission == "LONG_ONLY" and price > ema: # Euforia + Preço acima da média
             action = "SNIPER_LONG"
             motivo = "Notícia Extrema + Preço Confirmando"
             sl = price - (atr * stop_mult)
        elif permission == "SHORT_ONLY" and price < ema: # Pânico + Preço abaixo da média
             action = "SNIPER_SHORT"
             motivo = "Notícia Extrema + Preço Confirmando"
             sl = price + (atr * stop_mult)
        
        else:
            if not motivo: motivo = "Sem setup ou Preço no canal."

        if action:
            alavancagem_final = int(ALAVANCAGEM_PADRAO * lev_mult)
            print(f"   ✅ {sym:<5}: ABRINDO {action} | Lev: {alavancagem_final}x | Preço: ${price:.2f}")
            new_trade = {
                "id": str(uuid.uuid4())[:8], "data_entrada": data_hora,
                "symbol": sym, "tipo": action, "preco_entrada": price, "stop_loss": sl,
                "status": "ABERTO", "resultado": "ANDAMENTO", "lucro_usd": 0.0, 
                "motivo": motivo, "alavancagem": alavancagem_final, "mes_referencia": get_current_month()
            }
            df = pd.concat([df, pd.DataFrame([new_trade])], ignore_index=True)
        else:
            print(f"   ⚪ {sym:<5}: {motivo}")

    df.to_csv(CSV_FILE, index=False)
    print("\n💾 Ciclo V17 Finalizado.")

if __name__ == "__main__":
    run_bot_v17()

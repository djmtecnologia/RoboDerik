import sys
import subprocess
import os

# --- AUTO-INSTALAÇÃO ---
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
BASE_URL_CG = "https://api.coingecko.com/api/v3"
BASE_URL_BINANCE = "https://api.binance.com/api/v3" # Fonte Reserva
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
ADX_TREND_LIMIT = 20         
ADX_LATERAL_LIMIT = 15       
EMA_FILTER = 200
DONCHIAN_LONG = 25           
DONCHIAN_SHORT = 10          

RSS_FEEDS = ["https://cointelegraph.com/rss", "https://www.coindesk.com/arc/outboundfeeds/rss/"]
# Mapeamento ID CoinGecko -> Símbolo Binance
COINS_MAP = {
    "bitcoin": "BTCUSDT",
    "ethereum": "ETHUSDT",
    "solana": "SOLUSDT",
    "chainlink": "LINKUSDT",
    "avalanche-2": "AVAXUSDT",
    "polkadot": "DOTUSDT",
    "cardano": "ADAUSDT"
}

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
    try:
        for url in RSS_FEEDS:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                score = analyzer.polarity_scores(entry.title)['compound']
                if abs(score) > max_impact_abs:
                    max_impact_abs = abs(score); top_score = score; top_headline = entry.title
        return top_score, top_headline
    except: return 0, ""

def get_sentiment_zone(score):
    if score <= -0.6: return "🌪️ PÂNICO EXTREMO", "SHORT_ONLY", 1.0, 3.0
    elif -0.6 < score <= -0.2: return "🐻 VIÉS DE BAIXA", "BIAS_SHORT", 0.8, 2.0
    elif -0.2 < score < 0.2: return "⚪ NEUTRO/RUÍDO", "ALL", 1.0, 2.0
    elif 0.2 <= score < 0.6: return "🐮 VIÉS DE ALTA", "BIAS_LONG", 0.8, 2.0
    elif score >= 0.6: return "🚀 EUFORIA EXTREMA", "LONG_ONLY", 1.0, 3.0
    return "⚪ NEUTRO", "ALL", 1.0, 2.0

# --- NOVA FUNÇÃO HÍBRIDA DE DADOS (CG + BINANCE) ---
def get_market_data_robust(coin_id, binance_symbol):
    # 1. Tenta pegar do CoinGecko (Preferencial)
    try:
        url = f"{BASE_URL_CG}/coins/{coin_id}/ohlc?vs_currency=usd&days=365"
        resp = requests.get(url, headers=HEADERS, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            df = pd.DataFrame(data, columns=["time", "open", "high", "low", "close"])
            return df, "CoinGecko"
    except: pass # Falhou CG, vai para Binance

    # 2. Tenta pegar da Binance (Fallback Robusto)
    try:
        url = f"{BASE_URL_BINANCE}/klines?symbol={binance_symbol}&interval=1d&limit=365"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            # Binance retorna lista de strings, converter para float
            df = pd.DataFrame(data, columns=["time", "open", "high", "low", "close", "vol", "ct", "qa", "n", "tb", "tq", "ig"])
            df = df[["time", "open", "high", "low", "close"]].astype(float)
            return df, "Binance"
    except: pass
    
    return None, None

def calculate_indicators(df):
    if df is None or len(df) < 200: return None
    
    df["adx"] = ta.adx(df['high'], df['low'], df['close'], length=14)["ADX_14"]
    df["rsi"] = ta.rsi(df["close"], length=14)
    df["ema200"] = ta.ema(df["close"], length=EMA_FILTER)
    df["atr"] = ta.atr(df['high'], df['low'], df['close'], length=14)
    
    df["d_high_25"] = df['high'].rolling(window=DONCHIAN_LONG).max().shift(1)
    df["d_low_25"] = df['low'].rolling(window=DONCHIAN_LONG).min().shift(1)
    df["d_high_10"] = df['high'].rolling(window=DONCHIAN_SHORT).max().shift(1)
    df["d_low_10"] = df['low'].rolling(window=DONCHIAN_SHORT).min().shift(1)
    
    return df.iloc[-1].to_dict()

# --- CORE V18.2 (MULTI-SOURCE) ---

def run_bot_v18_2():
    data_hora = get_now_str()
    print(f"🚀 ROBODERIK V18.2 (MULTI-SOURCE) | {data_hora}")
    df_trades = load_trades()
    
    lucro_total = df_trades['lucro_usd'].sum() if not df_trades.empty else 0.0
    banca_atual = BANCA_INICIAL_REAL + lucro_total
    piso_seguranca = BANCA_INICIAL_REAL * RESERVA_SEGURANCA_PCT
    
    print(f"\n🏆 --- DASHBOARD DE PERFORMANCE ---")
    print(f"   💰 Banca Atual:   ${banca_atual:.2f} (Piso: ${piso_seguranca:.2f})")
    print("-" * 40)

    score, manchete = analyze_news()
    zone_name, permission, lev_mult, stop_mult = get_sentiment_zone(score)
    print(f"📊 NOTÍCIA: {score:.2f} | {zone_name}")
    print(f"   🔒 PERMISSÃO: {permission}")

    print("\n📡 ESCANEANDO MERCADO (CG + BINANCE)...")

    for coin_id, binance_symbol in COINS_MAP.items():
        sym = binance_symbol.replace("USDT", "") # Nome limpo (BTC)
        
        if not df_trades[(df_trades['symbol'] == sym) & (df_trades['status'] == 'ABERTO')].empty:
            print(f"   🟡 {sym:<5}: Posição Aberta.")
            continue
        
        # Busca dados brutos (Tenta CG, se falhar vai de Binance)
        df_raw, source = get_market_data_robust(coin_id, binance_symbol)
        
        # Calcula indicadores
        t = calculate_indicators(df_raw)
        
        if not t: 
            print(f"   🔴 {sym:<5}: Falha de dados em ambas as fontes.")
            continue
        
        price = t['close']
        adx, rsi, ema, atr = t['adx'], t['rsi'], t['ema200'], t['atr']
        
        # Verifica integridade dos dados antes de operar
        if pd.isna(ema) or pd.isna(rsi):
            print(f"   ⚠️ {sym:<5}: Dados insuficientes via {source}.")
            continue

        action, motivo, sl = None, "", 0.0
        
        # --- ESTRATÉGIAS ---
        # 1. PULLBACK
        if price > ema and rsi < 45 and adx > 20:
            if permission in ["ALL", "BIAS_LONG", "LONG_ONLY"]:
                action, motivo, sl = "LONG_PULLBACK", f"Compra na Baixa (RSI {rsi:.0f})", price - (atr * 2)
        
        # 2. ROMPIMENTO 10 DIAS
        elif price > t['d_high_10'] and price > ema and adx > 20:
            if permission in ["ALL", "BIAS_LONG", "LONG_ONLY"]:
                action, motivo, sl = "LONG_BREAKOUT_10", f"Rompimento Tático (${t['d_high_10']:.2f})", price - (atr * 2)

        # 3. ROMPIMENTO 25 DIAS
        elif price > t['d_high_25'] and price > ema:
            if permission in ["ALL", "BIAS_LONG", "LONG_ONLY"]:
                action, motivo, sl = "LONG_MACRO", f"Rompimento Histórico (${t['d_high_25']:.2f})", price - (atr * 3)

        # 4. SHORT
        elif price < t['d_low_10'] and price < ema and adx > 20:
            if permission in ["ALL", "BIAS_SHORT", "SHORT_ONLY"]:
                action, motivo, sl = "SHORT_BREAKOUT_10", f"Perda de Fundo Tático (${t['d_low_10']:.2f})", price + (atr * 2)

        # 5. GRID
        elif adx < ADX_LATERAL_LIMIT and permission == "ALL":
             action, motivo, sl = "GRID_NEUTRAL", "Mercado Lateral (Grid)", price - (atr * 3)

        if not action:
            dist_10d = ((t['d_high_10'] - price) / price) * 100
            motivo = f"Aguardando: Rompimento 10d (+{dist_10d:.1f}%) ou Pullback (RSI {rsi:.0f} > 45) via {source}"

        if action:
            alavancagem_final = int(ALAVANCAGEM_PADRAO * lev_mult)
            print(f"   ✅ {sym:<5}: ABRINDO {action} | Preço: ${price:.2f} ({source})")
            new_trade = {
                "id": str(uuid.uuid4())[:8], "data_entrada": data_hora,
                "symbol": sym, "tipo": action, "preco_entrada": price, "stop_loss": sl,
                "status": "ABERTO", "resultado": "ANDAMENTO", "lucro_usd": 0.0, 
                "motivo": motivo, "alavancagem": alavancagem_final, "mes_referencia": get_current_month()
            }
            df_trades = pd.concat([df_trades, pd.DataFrame([new_trade])], ignore_index=True)
        else:
            print(f"   ⚪ {sym:<5}: {motivo} [P:${price:.2f}]")

    df_trades.to_csv(CSV_FILE, index=False)
    print("\n💾 Ciclo V18.2 Finalizado.")

if __name__ == "__main__":
    run_bot_v18_2()

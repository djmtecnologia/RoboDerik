import sys
import subprocess
import os

# --- AUTO-INSTALAÇÃO ---
def install(package):
    try: __import__(package)
    except ImportError:
        pip_map = {"vaderSentiment": "vaderSentiment", "feedparser": "feedparser", "pandas_ta": "pandas_ta", "pytz": "pytz", "yfinance": "yfinance", "requests": "requests", "pandas": "pandas"}
        subprocess.check_call([sys.executable, "-m", "pip", "install", pip_map.get(package, package)])

libs = ["yfinance", "pytz", "pandas_ta", "vaderSentiment", "feedparser", "requests", "pandas"]
for lib in libs: install(lib)

import yfinance as yf
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
CSV_FILE = "trades.csv"
try: FUSO = pytz.timezone('America/Sao_Paulo')
except: FUSO = pytz.utc 

# --- GESTÃO DE BANCA ---
BANCA_INICIAL_REAL = 1200.0  
RESERVA_SEGURANCA_PCT = 0.15 
ALAVANCAGEM_PADRAO = 5 

# --- PARÂMETROS TÉCNICOS ---
EMA_FILTER = 200
# RSI GATILHOS (Conforme sua estratégia)
RSI_OVERSOLD = 35      # Abaixo disso, não vende (fundo)
RSI_BOUNCE_ENTRY = 45  # Acima disso, começa a procurar Short no repique
RSI_OVERBOUGHT = 70    # Acima disso, Short agressivo

RSS_FEEDS = ["https://cointelegraph.com/rss", "https://www.coindesk.com/arc/outboundfeeds/rss/"]
COINS_MAP = {
    "BTC": {"yf": "BTC-USD"}, "ETH": {"yf": "ETH-USD"}, "SOL": {"yf": "SOL-USD"},
    "LINK": {"yf": "LINK-USD"}, "AVAX": {"yf": "AVAX-USD"}, "DOT": {"yf": "DOT-USD"}, "ADA": {"yf": "ADA-USD"}
}

# --- FUNÇÕES ---

def get_now_str(): return datetime.now(FUSO).strftime("%d/%m/%Y %H:%M:%S")
def get_current_month(): return datetime.now(FUSO).strftime('%Y-%m')

def load_trades():
    if os.path.exists(CSV_FILE): 
        df = pd.read_csv(CSV_FILE)
        if 'mes_referencia' not in df.columns: df['mes_referencia'] = get_current_month()
        return df
    return pd.DataFrame(columns=["id", "data_entrada", "symbol", "tipo", "preco_entrada", "stop_loss", "status", "resultado", "data_saida", "preco_saida", "lucro_usd", "motivo", "alavancagem", "mes_referencia"])

def analyze_news():
    analyzer = SentimentIntensityAnalyzer()
    max_impact = 0; top_score = 0
    try:
        for url in RSS_FEEDS:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                score = analyzer.polarity_scores(entry.title)['compound']
                if abs(score) > max_impact: max_impact = abs(score); top_score = score
        return top_score
    except: return 0

def get_sentiment_zone(score):
    if score <= -0.2: return "🐻 BAIXA", "BIAS_SHORT"
    elif score >= 0.2: return "🐮 ALTA", "BIAS_LONG"
    return "⚪ NEUTRO", "ALL"

def get_data_indicators(symbol_yf):
    try:
        ticker = yf.Ticker(symbol_yf)
        hist = ticker.history(period="2y", interval="1d")
        if len(hist) < 200: return None
        
        df = hist.reset_index()
        df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close"})
        
        df["adx"] = ta.adx(df['high'], df['low'], df['close'])["ADX_14"]
        df["rsi"] = ta.rsi(df["close"], length=14)
        df["ema200"] = ta.ema(df["close"], length=EMA_FILTER)
        df["atr"] = ta.atr(df['high'], df['low'], df['close'])
        df["low_10"] = df['low'].rolling(window=10).min().shift(1)
        
        return df.iloc[-1]
    except: return None

# --- CORE V20 (DEAD CAT SNIPER) ---

def run_bot_v20():
    data_hora = get_now_str()
    print(f"🚀 ROBODERIK V20 (SHORT THE BOUNCE) | {data_hora}")
    df_trades = load_trades()
    
    score = analyze_news()
    zone, permission = get_sentiment_zone(score)
    print(f"📊 NOTÍCIA: {score:.2f} ({zone})")
    
    # 1. ANÁLISE PRIMÁRIA: O QUE O BITCOIN ESTÁ FAZENDO?
    print("🔎 Verificando a 'Mãe' (BTC)...")
    btc_data = get_data_indicators(COINS_MAP["BTC"]["yf"])
    btc_trend = "NEUTRO"
    
    if btc_data is not None:
        if btc_data['close'] < btc_data['ema200']:
            btc_trend = "URSO (Baixa)"
            print(f"   📉 BTC em Tendência de Baixa (Abaixo da EMA200). Alts liberadas para Short.")
        else:
            btc_trend = "TOURO (Alta)"
            print(f"   📈 BTC em Tendência de Alta. Shorts em Alts são perigosos.")
    print("-" * 60)

    # 2. SCANNER DAS MOEDAS
    for sym, keys in COINS_MAP.items():
        if not df_trades[(df_trades['symbol'] == sym) & (df_trades['status'] == 'ABERTO')].empty:
            print(f"   🟡 {sym:<5}: Posição já aberta.")
            continue
        
        t = get_data_indicators(keys['yf'])
        if t is None:
            print(f"   🔴 {sym}: Erro de dados.")
            continue

        price, rsi, adx, ema, atr, l10 = t['close'], t['rsi'], t['adx'], t['ema200'], t['atr'], t['low_10']
        
        print(f"🔍 {sym:<5} | P: ${price:,.2f} | EMA: ${ema:,.2f}")
        print(f"      [IND] RSI: {rsi:.1f} (Gatilho Short: >{RSI_BOUNCE_ENTRY}) | ADX: {adx:.1f}")

        action, motivo, sl = None, "", 0.0
        
        # --- LÓGICA ESTRATÉGICA V20 ---

        # CENÁRIO 1: TENDÊNCIA DE BAIXA (Price < EMA) - FOCO DA V20
        if price < ema:
            
            # A. PROTEÇÃO: "NÃO VENDA O FUNDO"
            if rsi < RSI_OVERSOLD:
                motivo = f"🚫 Venda Bloqueada: RSI Sobrevendido ({rsi:.1f}). Aguardando repique."
                # Aqui poderíamos ativar o Grid Long da V19.1 para pegar o repique
                if permission != "BIAS_SHORT": # Se a notícia não for Pânico Total
                    action = "GRID_EXHAUSTION"
                    motivo = f"Scalp de Repique (RSI {rsi:.1f} < 35)"
                    sl = price - (atr * 3)

            # B. GATILHO: "SHORT THE BOUNCE" (Venda no Repique)
            elif rsi > RSI_BOUNCE_ENTRY:
                # Confirmação do BTC (Só shorta se BTC também estiver fraco/neutro ou caindo)
                if "URSO" in btc_trend or "NEUTRO" in btc_trend:
                    action = "SHORT_BOUNCE"
                    motivo = f"Repique Identificado (RSI {rsi:.1f} recuperou). Venda na resistência."
                    sl = price + (atr * 2.5) # Stop acima do 'pulo do gato'
                else:
                    motivo = "Setup Short válido, mas BTC está forte (Risco de arrasto)."
            
            # C. GATILHO: PERDA DE FUNDO (Breakout)
            elif price < l10:
                # Só vende rompimento de fundo se o RSI não estiver extremo
                if rsi > RSI_OVERSOLD:
                    action = "SHORT_BREAKOUT"
                    motivo = "Perda de Suporte 10d (Confirmação de Queda)"
                    sl = price + (atr * 2)
                else:
                    motivo = "Rompeu fundo, mas RSI esticado. Perigoso vender."
            
            else:
                motivo = f"Em tendência de baixa, mas no meio do caminho (RSI {rsi:.1f})."

        # CENÁRIO 2: TENDÊNCIA DE ALTA (Price > EMA)
        elif price > ema:
            if permission == "BIAS_SHORT":
                motivo = "Long bloqueado: Notícias indicam queda macro (BTC 50k)."
            elif rsi < 45 and adx > 20:
                action = "LONG_PULLBACK"
                motivo = "Correção em tendência de alta"
                sl = price - (atr * 2)
            else:
                motivo = "Tendência de Alta sem gatilho de entrada."

        # EXECUÇÃO
        if action:
            print(f"      ✅ AÇÃO: {action} disparada! ({motivo})")
            new_trade = {
                "id": str(uuid.uuid4())[:8], "data_entrada": data_hora,
                "symbol": sym, "tipo": action, "preco_entrada": price, "stop_loss": sl,
                "status": "ABERTO", "resultado": "ANDAMENTO", "lucro_usd": 0.0, 
                "motivo": motivo, "alavancagem": ALAVANCAGEM_PADRAO, "mes_referencia": get_current_month()
            }
            df_trades = pd.concat([df_trades, pd.DataFrame([new_trade])], ignore_index=True)
        else:
            print(f"      ⚪ PLANO: {motivo}")
        print("-" * 60)

    df_trades.to_csv(CSV_FILE, index=False)
    print("\n💾 Ciclo Finalizado.")

if __name__ == "__main__":
    run_bot_v20()

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
DONCHIAN_LONG = 25           
DONCHIAN_SHORT = 10          

RSS_FEEDS = ["https://cointelegraph.com/rss", "https://www.coindesk.com/arc/outboundfeeds/rss/"]
COINS_MAP = {
    "BTC": {"yf": "BTC-USD"}, "ETH": {"yf": "ETH-USD"}, "SOL": {"yf": "SOL-USD"},
    "LINK": {"yf": "LINK-USD"}, "AVAX": {"yf": "AVAX-USD"}, "DOT": {"yf": "DOT-USD"}, "ADA": {"yf": "ADA-USD"}
}

# --- FUNÇÕES ---

def get_now_str(): return datetime.now(FUSO).strftime("%d/%m/%Y %H:%M:%S")

def load_trades():
    if os.path.exists(CSV_FILE): return pd.read_csv(CSV_FILE)
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

def run_bot_v18_4():
    data_hora = get_now_str()
    print(f"🚀 ROBODERIK V18.4 (DETALHADO) | {data_hora}")
    df_trades = load_trades()
    
    score = analyze_news()
    zone, permission = get_sentiment_zone(score)
    print(f"📊 SENTIMENTO: {score:.2f} ({zone}) | PERMISSÃO: {permission}")
    print("-" * 60)

    for sym, keys in COINS_MAP.items():
        if not df_trades[(df_trades['symbol'] == sym) & (df_trades['status'] == 'ABERTO')].empty:
            print(f"   🟡 {sym:<5}: Posição já aberta.")
            continue
        
        try:
            # Coleta de Dados
            ticker = yf.Ticker(keys['yf'])
            df = ticker.history(period="2y", interval="1d").reset_index()
            df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close"})
            
            # Indicadores
            df["adx"] = ta.adx(df['high'], df['low'], df['close'])["ADX_14"]
            df["rsi"] = ta.rsi(df["close"], length=14)
            df["ema200"] = ta.ema(df["close"], length=EMA_FILTER)
            df["atr"] = ta.atr(df['high'], df['low'], df['close'])
            df["high_10"] = df['high'].rolling(window=10).max().shift(1)
            
            t = df.iloc[-1]
            price = t['close']
            rsi, adx, ema, atr, h10 = t['rsi'], t['adx'], t['ema200'], t['atr'], t['high_10']
            
            # Exibição de Dados Atuais (O que você pediu)
            print(f"🔍 {sym:<5} | PREÇO: ${price:,.2f}")
            print(f"      [INDICADORES] RSI: {rsi:.1f} | ADX: {adx:.1f} | EMA200: ${ema:,.2f} | ATR: {atr:.2f}")
            print(f"      [GATILHOS]    Topo 10d: ${h10:,.2f} (Dist: {((h10/price)-1)*100:.1f}%) | Alvo RSI Pullback: > 45")

            action, motivo = None, ""
            
            # Lógica de Decisão
            if price > ema:
                if rsi < 45 and adx > 20:
                    action, motivo = "LONG_PULLBACK", f"Compra na correção (RSI {rsi:.1f})"
                elif price > h10 and adx > 20:
                    action, motivo = "LONG_BREAKOUT_10", f"Rompimento de topo 10d"
            
            if action and permission in ["ALL", "BIAS_LONG"]:
                print(f"      ✅ AÇÃO: {action} disparada!")
                # Lógica de salvar trade omitida para brevidade, mas segue o padrão anterior
            else:
                status = "MERCADO EM QUEDA (Abaixo da EMA200)" if price < ema else "AGUARDANDO GATILHO"
                print(f"      ⚪ STATUS: {status}")
            print("-" * 60)

        except Exception as e:
            print(f"   🔴 {sym}: Erro no processamento: {e}")

if __name__ == "__main__":
    run_bot_v18_4()

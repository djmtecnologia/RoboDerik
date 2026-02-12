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
ADX_LATERAL_LIMIT = 20 
ADX_TREND_LIMIT = 20   
# Mudei para pegar fundo de 10 dias também
DONCHIAN_SHORT = 10          

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

def run_bot_v18_6():
    data_hora = get_now_str()
    print(f"🚀 ROBODERIK V18.6 (FULL STRATEGY) | {data_hora}")
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
            ticker = yf.Ticker(keys['yf'])
            hist = ticker.history(period="2y", interval="1d")
            
            if len(hist) < 200:
                print(f"   🔴 {sym}: Histórico insuficiente.")
                continue

            df = hist.reset_index()
            df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close"})
            
            # --- CÁLCULO DE INDICADORES ---
            df["adx"] = ta.adx(df['high'], df['low'], df['close'])["ADX_14"]
            df["rsi"] = ta.rsi(df["close"], length=14)
            df["ema200"] = ta.ema(df["close"], length=EMA_FILTER)
            df["atr"] = ta.atr(df['high'], df['low'], df['close'])
            
            # Canais de 10 dias (Topo e Fundo)
            df["high_10"] = df['high'].rolling(window=10).max().shift(1)
            df["low_10"]  = df['low'].rolling(window=10).min().shift(1)
            
            t = df.iloc[-1]
            price = t['close']
            rsi, adx, ema, atr = t['rsi'], t['adx'], t['ema200'], t['atr']
            h10, l10 = t['high_10'], t['low_10']
            
            print(f"🔍 {sym:<5} | P: ${price:,.2f} | EMA: ${ema:,.2f}")
            print(f"      [IND] RSI: {rsi:.1f} | ADX: {adx:.1f} | Topo10d: ${h10:,.2f} | Fundo10d: ${l10:,.2f}")

            action, motivo, sl = None, "", 0.0
            
            # --- LÓGICA DE DECISÃO COMPLETA ---
            
            # 1. MODO GRID (Lateral)
            if adx < ADX_LATERAL_LIMIT:
                if permission == "ALL":
                    action = "GRID_NEUTRAL"
                    motivo = f"Lateral (ADX {adx:.1f})"
                    sl = price - (atr * 3)
                else:
                    motivo = f"Grid bloqueado por notícia ({permission})"

            # 2. MODO TENDÊNCIA (Alta ou Baixa)
            elif adx >= ADX_TREND_LIMIT:
                
                # A. TENDÊNCIA DE ALTA (Price > EMA)
                if price > ema:
                    if rsi < 45: # Pullback
                        action, motivo = "LONG_PULLBACK", f"Compra correção (RSI {rsi:.1f})"
                        sl = price - (atr * 2)
                    elif price > h10: # Breakout
                        action, motivo = "LONG_BREAKOUT_10", "Rompimento Topo 10d"
                        sl = price - (atr * 2)
                    else:
                        motivo = f"Tendência Alta s/ gatilho (Topo: ${h10:.2f})"

                # B. TENDÊNCIA DE BAIXA (Price < EMA) -> AGORA IMPLEMENTADO!
                else:
                    if rsi > 55: # Pullback de Baixa (Repique)
                        action, motivo = "SHORT_PULLBACK", f"Venda no repique (RSI {rsi:.1f})"
                        sl = price + (atr * 2)
                    elif price < l10: # Breakout de Baixa (Perder fundo)
                        action, motivo = "SHORT_BREAKOUT_10", "Perda de Fundo 10d"
                        sl = price + (atr * 2)
                    else:
                        motivo = f"Tendência Baixa s/ gatilho (Fundo: ${l10:.2f})"
            
            # --- FILTRO FINAL DE NOTÍCIAS ---
            if action:
                if "LONG" in action and permission == "BIAS_SHORT":
                    action = None; motivo = f"LONG bloqueado (Viés Baixista)"
                if "SHORT" in action and permission == "BIAS_LONG":
                    action = None; motivo = f"SHORT bloqueado (Viés Altista)"
                if "GRID" in action and permission != "ALL":
                    action = None; motivo = f"GRID bloqueado (Viés Definido)"

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
                print(f"      ⚪ ESPERA: {motivo}")
            print("-" * 60)

        except Exception as e:
            print(f"   🔴 {sym}: Erro: {e}")

    df_trades.to_csv(CSV_FILE, index=False)
    print("\n💾 Ciclo Finalizado e Planilha Salva.")

if __name__ == "__main__":
    run_bot_v18_6()

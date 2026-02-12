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
RISCO_POR_TRADE_PCT = 0.20   
MAX_VALOR_TRADE = 100000.0   
ALAVANCAGEM_PADRAO = 5 

# --- PARÂMETROS TÉCNICOS ---
EMA_FILTER = 200
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
    # Adicionada coluna 'valor_investido' na estrutura
    cols = ["id", "data_entrada", "symbol", "tipo", "valor_investido", "preco_entrada", "stop_loss", "status", "resultado", "data_saida", "preco_saida", "lucro_usd", "motivo", "alavancagem", "mes_referencia"]
    
    if os.path.exists(CSV_FILE):
        df = pd.read_csv(CSV_FILE)
        # Se a coluna nova não existir, cria ela preenchida com 0
        if 'valor_investido' not in df.columns:
            df['valor_investido'] = 0.0
        if 'mes_referencia' not in df.columns:
            df['mes_referencia'] = get_current_month()
        return df
    return pd.DataFrame(columns=cols)

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

def run_bot_v19():
    data_hora = get_now_str()
    print(f"🚀 ROBODERIK V19 (COM GESTÃO FINANCEIRA) | {data_hora}")
    df_trades = load_trades()
    
    # CÁLCULO FINANCEIRO
    lucro_total = df_trades['lucro_usd'].sum() if not df_trades.empty else 0.0
    banca_atual = BANCA_INICIAL_REAL + lucro_total
    piso_seguranca = BANCA_INICIAL_REAL * RESERVA_SEGURANCA_PCT
    capital_livre = max(0, banca_atual - piso_seguranca)
    
    # Valor Base para Trades (20% do livre)
    valor_base_trade = min(capital_livre * RISCO_POR_TRADE_PCT, MAX_VALOR_TRADE)

    print(f"\n🏆 --- DASHBOARD FINANCEIRO ---")
    print(f"   💰 Banca Total:   ${banca_atual:.2f}")
    print(f"   🔒 Piso Seguro:   ${piso_seguranca:.2f}")
    print(f"   💸 Mão Base:      ${valor_base_trade:.2f} (por operação)")
    print("-" * 60)

    score = analyze_news()
    zone, permission = get_sentiment_zone(score)
    print(f"📊 SENTIMENTO: {score:.2f} ({zone}) | PERMISSÃO: {permission}")

    for sym, keys in COINS_MAP.items():
        if not df_trades[(df_trades['symbol'] == sym) & (df_trades['status'] == 'ABERTO')].empty:
            print(f"   🟡 {sym:<5}: Posição já aberta.")
            continue
        
        try:
            ticker = yf.Ticker(keys['yf'])
            df = ticker.history(period="1y", interval="1d").reset_index()
            if df.empty: continue
            
            df["adx"] = ta.adx(df['high'], df['low'], df['close'])["ADX_14"]
            df["rsi"] = ta.rsi(df["close"], length=14)
            df["ema200"] = ta.ema(df["close"], length=EMA_FILTER)
            df["atr"] = ta.atr(df['high'], df['low'], df['close'])
            df["high_10"] = df['high'].rolling(window=10).max().shift(1)
            
            t = df.iloc[-1]
            price = t['close']
            rsi, adx, ema, atr, h10 = t['rsi'], t['adx'], t['ema200'], t['atr'], t['high_10']
            
            action, motivo = None, ""
            trade_size = valor_base_trade # Tamanho padrão
            
            # --- ESTRATÉGIAS ---
            
            # 1. PULLBACK (TENDÊNCIA)
            if price > ema and rsi < 45 and adx > 20:
                action, motivo = "LONG_PULLBACK", f"Compra Correção (RSI {rsi:.1f})"
                trade_size = valor_base_trade # 100% da mão
                sl = price - (atr * 2)

            # 2. ROMPIMENTO (TENDÊNCIA)
            elif price > h10 and adx > 20:
                action, motivo = "LONG_BREAKOUT_10", f"Rompimento Topo 10d"
                trade_size = valor_base_trade # 100% da mão
                sl = price - (atr * 2)
            
            # 3. EXAUSTÃO (GRID/LATERAL)
            elif adx < 20 and (rsi < 30 or rsi > 70):
                if rsi < 30:
                    action, motivo = "GRID_OVERSOLD", f"Exaustão Venda (RSI {rsi:.1f})"
                    sl = price - (atr * 3)
                trade_size = valor_base_trade * 0.4 # 40% da mão (Mais seguro no grid)

            # --- EXECUÇÃO ---
            if action:
                if permission == "BIAS_SHORT" and "LONG" in action:
                    print(f"   ⚪ {sym:<5}: Setup {action} bloqueado por Notícia Baixista.")
                else:
                    print(f"   ✅ {sym:<5}: ABRINDO {action}")
                    print(f"      💵 Investindo: ${trade_size:.2f} (Lev: {ALAVANCAGEM_PADRAO}x)")
                    
                    new_trade = {
                        "id": str(uuid.uuid4())[:8],
                        "data_entrada": data_hora,
                        "symbol": sym, 
                        "tipo": action, 
                        "valor_investido": round(trade_size, 2), # SALVANDO O VALOR!
                        "preco_entrada": price, 
                        "stop_loss": sl,
                        "status": "ABERTO", 
                        "resultado": "ANDAMENTO", 
                        "lucro_usd": 0.0, 
                        "motivo": motivo, 
                        "alavancagem": ALAVANCAGEM_PADRAO, 
                        "mes_referencia": get_current_month()
                    }
                    df_trades = pd.concat([df_trades, pd.DataFrame([new_trade])], ignore_index=True)
            else:
                dist_topo = ((h10/price)-1)*100
                print(f"   🔍 {sym:<5}: Aguardando RSI < 45 ({rsi:.0f}) ou Rompimento +{dist_topo:.1f}%")

        except Exception as e:
            print(f"   🔴 {sym}: Erro: {e}")

    df_trades.to_csv(CSV_FILE, index=False)
    print("\n💾 Ciclo Finalizado.")

if __name__ == "__main__":
    run_bot_v19()

import sys
import subprocess
import os

# --- AUTO-INSTALAÇÃO DE DEPENDÊNCIAS (Correção de Erros do GitHub Actions) ---
def install(package):
    try:
        __import__(package)
    except ImportError:
        print(f"📦 Instalando {package} automaticamente...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

# Lista de bibliotecas críticas
libs = ["pytz", "pandas_ta", "vaderSentiment", "feedparser", "requests", "pandas"]
for lib in libs: install(lib)

# --- IMPORTS ---
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

# Configuração de Fuso Horário (São Paulo)
try:
    FUSO = pytz.timezone('America/Sao_Paulo')
except:
    FUSO = pytz.utc # Fallback se der erro

# --- GESTÃO DE BANCA (152x STRATEGY) ---
BANCA_INICIAL_REAL = 1200.0  
RESERVA_SEGURANCA_PCT = 0.15 
RISCO_POR_TRADE_PCT = 0.20   
MAX_VALOR_TRADE = 100000.0   
ALAVANCAGEM_MAX = 5 

# --- PARÂMETROS HÍBRIDOS ---
ADX_TREND_LIMIT = 25
ADX_LATERAL_LIMIT = 20
EMA_FILTER = 200
DONCHIAN_PERIOD = 25

RSS_FEEDS = ["https://cointelegraph.com/rss", "https://www.coindesk.com/arc/outboundfeeds/rss/"]
COINS_IDS = ["bitcoin", "ethereum", "solana", "chainlink", "avalanche-2", "polkadot", "cardano"]

# --- FUNÇÕES AUXILIARES ---

def get_now_str():
    """Retorna data formatada DD/MM/YYYY HH:MM:SS no fuso de SP"""
    return datetime.now(FUSO).strftime("%d/%m/%Y %H:%M:%S")

def get_current_month():
    return datetime.now(FUSO).strftime('%Y-%m')

def load_trades():
    if os.path.exists(CSV_FILE):
        df = pd.read_csv(CSV_FILE)
        # Garante que a coluna de mês exista para cálculo de performance
        if 'mes_referencia' not in df.columns:
            if 'data_entrada' in df.columns:
                # Tenta converter datas antigas para extrair o mês
                try:
                    df['mes_referencia'] = pd.to_datetime(df['data_entrada'], dayfirst=True, errors='coerce').dt.strftime('%Y-%m')
                except:
                    df['mes_referencia'] = get_current_month()
            else:
                df['mes_referencia'] = get_current_month()
        return df
    
    columns = ["id", "data_entrada", "symbol", "tipo", "preco_entrada", "stop_loss", "status", "resultado", "data_saida", "preco_saida", "lucro_usd", "motivo", "alavancagem", "mes_referencia"]
    return pd.DataFrame(columns=columns)

def analyze_news():
    analyzer = SentimentIntensityAnalyzer()
    total_score, count, max_impact, top_headline = 0, 0, 0, ""
    print("\n📰 ANALISANDO NOTÍCIAS...")
    try:
        for url in RSS_FEEDS:
            feed = feedparser.parse(url)
            for entry in feed.entries[:2]:
                score = analyzer.polarity_scores(entry.title)['compound']
                total_score += score; count += 1
                if abs(score) > max_impact: max_impact = abs(score); top_headline = entry.title
        
        avg_score = total_score / count if count > 0 else 0
        return avg_score, max_impact >= 0.5, top_headline
    except: return 0, False, ""

def get_technicals(coin_id):
    try:
        url = f"{BASE_URL}/coins/{coin_id}/ohlc?vs_currency=usd&days=365"
        resp = requests.get(url, headers=HEADERS, timeout=10).json()
        df = pd.DataFrame(resp, columns=["time", "open", "high", "low", "close"])
        
        # Indicadores V44 (Híbrido)
        df["adx"] = ta.adx(df['high'], df['low'], df['close'], length=14)["ADX_14"]
        df["ema200"] = ta.ema(df["close"], length=EMA_FILTER)
        df["atr"] = ta.atr(df['high'], df['low'], df['close'], length=14)
        df["d_high"] = df['high'].rolling(window=DONCHIAN_PERIOD).max().shift(1)
        df["d_low"] = df['low'].rolling(window=15).min().shift(1)
        
        return df.iloc[-1].to_dict()
    except: return None

# --- CORE OPERACIONAL ---

def run_bot_v15_5():
    data_hora = get_now_str()
    print(f"🚀 ROBODERIK V15.5 | {data_hora}")
    df = load_trades()
    
    # 1. Dashboard Financeiro
    lucro_total = df['lucro_usd'].sum() if not df.empty else 0.0
    banca_atual = BANCA_INICIAL_REAL + lucro_total
    piso_seguranca = BANCA_INICIAL_REAL * RESERVA_SEGURANCA_PCT
    mes_atual = get_current_month()
    lucro_mes = df[df['mes_referencia'] == mes_atual]['lucro_usd'].sum() if not df.empty else 0.0
    
    print(f"\n🏆 --- DASHBOARD DE PERFORMANCE ---")
    print(f"   💰 Banca Atual:   ${banca_atual:.2f} (Piso: ${piso_seguranca:.2f})")
    print(f"   📈 Lucro no Mês:  ${lucro_mes:.2f}")
    print(f"   📊 Multiplicação: {banca_atual/BANCA_INICIAL_REAL:.2f}x")
    print("-" * 40)

    # 2. Análise de Sentimento
    sentimento, bombastico, manchete = analyze_news()
    status_news = "🚫 BLOQUEIO NOTÍCIA" if bombastico else "✅ OK"
    print(f"📊 SENTIMENTO: {sentimento:.2f} {status_news}")
    if bombastico: print(f"   ⚠️ Manchete: {manchete[:60]}...")

    print("\n📡 ESCANEANDO OPORTUNIDADES HÍBRIDAS...")
    params = {"vs_currency": "usd", "ids": ",".join(COINS_IDS), "sparkline": "false"}
    
    try:
        market = requests.get(f"{BASE_URL}/coins/markets", headers=HEADERS, params=params).json()
    except Exception as e:
        print(f"Erro na API CoinGecko: {e}")
        return

    # 3. Scanner de Oportunidades
    for coin in market:
        sym = coin['symbol'].upper()
        
        # Verifica se já existe trade aberto
        if not df[(df['symbol'] == sym) & (df['status'] == 'ABERTO')].empty:
            print(f"   🟡 {sym:<5}: Operação já aberta (Ignorando).")
            continue
        
        tech = get_technicals(coin['id'])
        if not tech:
            print(f"   🔴 {sym:<5}: Erro técnico (Dados insuficientes).")
            continue
        
        price = coin['current_price']
        adx, ema, d_high, d_low, atr = tech['adx'], tech['ema200'], tech['d_high'], tech['d_low'], tech['atr']
        
        action, motivo, sl = None, "", 0.0

        # LÓGICA HÍBRIDA V15.5
        if adx > ADX_TREND_LIMIT:
            if bombastico:
                motivo = "Tendência forte, mas bloqueada por notícia."
            elif price > d_high and price > ema:
                action, motivo = "TREND_LONG", "Rompimento de Alta (Donchian)"
                sl = price - (atr * 2)
            elif price < d_low and price < ema:
                action, motivo = "TREND_SHORT", "Rompimento de Baixa (Donchian)"
                sl = price + (atr * 2)
            else:
                motivo = f"Tendência, mas preço (${price:.2f}) dentro do canal."
        
        elif adx < ADX_LATERAL_LIMIT:
            if -0.2 < sentimento < 0.2:
                action, motivo = "GRID_NEUTRAL", "Lateralização (Grid Ativado)"
                sl = price - (atr * 3) # Stop técnico largo para aguentar ruído
            else:
                motivo = f"Lateral (ADX {adx:.1f}), mas sentimento instável."
        else:
            motivo = f"Zona Morta (ADX {adx:.1f}). Aguardando direção."

        # Execução
        if action:
            print(f"   ✅ {sym:<5}: ABRINDO {action} | Preço: ${price:.2f}")
            new_trade = {
                "id": str(uuid.uuid4())[:8],
                "data_entrada": data_hora, # Data formatada BR
                "symbol": sym, 
                "tipo": action, 
                "preco_entrada": price, 
                "stop_loss": sl,
                "status": "ABERTO", 
                "resultado": "ANDAMENTO", 
                "lucro_usd": 0.0, 
                "motivo": motivo, 
                "alavancagem": ALAVANCAGEM_MAX, 
                "mes_referencia": mes_atual
            }
            df = pd.concat([df, pd.DataFrame([new_trade])], ignore_index=True)
        else:
            print(f"   ⚪ {sym:<5}: {motivo}")

    # 4. Salvar Dados
    df.to_csv(CSV_FILE, index=False)
    print("\n💾 Ciclo Finalizado e Planilha Salva.")

if __name__ == "__main__":
    run_bot_v15_5()

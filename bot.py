import requests
import pandas as pd
import pandas_ta as ta
import feedparser
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import os
from datetime import datetime
import uuid

# --- CONFIGURAÇÕES INSTITUCIONAIS ---
API_KEY = os.environ.get("CG_API_KEY")
BASE_URL = "https://api.coingecko.com/api/v3"
HEADERS = {"accept": "application/json", "x-cg-demo-api-key": API_KEY}
CSV_FILE = "trades.csv"

# --- GESTÃO DE BANCA (ESTRATÉGIA 152x) ---
BANCA_INICIAL_REAL = 1200.0  # Seu capital inicial real
RESERVA_SEGURANCA_PCT = 0.15 # 15% Intocável
RISCO_POR_TRADE_PCT = 0.20   # 20% do capital livre por trade
MAX_VALOR_TRADE = 100000.0   # Teto de liquidez $100k
ALAVANCAGEM_MAX = 5 
KILL_SWITCH_PCT = 0.15       # Trava de segurança diária

# --- PARÂMETROS HÍBRIDOS ---
ADX_TREND_LIMIT = 25
ADX_LATERAL_LIMIT = 20
EMA_FILTER = 200
DONCHIAN_PERIOD = 25

RSS_FEEDS = ["https://cointelegraph.com/rss", "https://www.coindesk.com/arc/outboundfeeds/rss/"]
COINS_IDS = ["bitcoin", "ethereum", "solana", "chainlink", "avalanche-2", "polkadot", "cardano"]

# --- FUNÇÕES DE INFRAESTRUTURA ---

def load_trades():
    if os.path.exists(CSV_FILE):
        return pd.read_csv(CSV_FILE)
    columns = ["id", "data_entrada", "symbol", "tipo", "preco_entrada", "stop_loss", "status", "resultado", "data_saida", "preco_saida", "lucro_usd", "motivo", "alavancagem", "mes_referencia"]
    return pd.DataFrame(columns=columns)

def analyze_news():
    analyzer = SentimentIntensityAnalyzer()
    total_score, count, max_impact, top_headline = 0, 0, 0, ""
    print("\n📰 ANALISANDO NOTÍCIAS...")
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:2]:
                score = analyzer.polarity_scores(entry.title)['compound']
                total_score += score; count += 1
                if abs(score) > max_impact: max_impact = abs(score); top_headline = entry.title
        except: continue
    return (total_score / count if count > 0 else 0), max_impact >= 0.5, top_headline

def get_technicals(coin_id):
    try:
        url = f"{BASE_URL}/coins/{coin_id}/ohlc?vs_currency=usd&days=365"
        data = requests.get(url, headers=HEADERS).json()
        df = pd.DataFrame(data, columns=["time", "open", "high", "low", "close"])
        df["adx"] = ta.adx(df['high'], df['low'], df['close'], length=14)["ADX_14"]
        df["ema200"] = ta.ema(df["close"], length=EMA_FILTER)
        df["atr"] = ta.atr(df['high'], df['low'], df['close'], length=14)
        df["d_high"] = df['high'].rolling(window=DONCHIAN_PERIOD).max().shift(1)
        df["d_low"] = df['low'].rolling(window=15).min().shift(1)
        return df.iloc[-1].to_dict()
    except: return None

# --- CORE OPERACIONAL ---

def run_bot_v15():
    print(f"🚀 ROBODERIK V15 (HYBRID 152x MODE + NEWS ANALYZER)")
    df = load_trades()
    
    # Dashboard de Performance Realista
    lucro_total = df['lucro_usd'].sum() if not df.empty else 0.0
    banca_atual = BANCA_INICIAL_REAL + lucro_total
    piso_seguranca = BANCA_INICIAL_REAL * RESERVA_SEGURANCA_PCT
    mes_atual = datetime.now().strftime('%Y-%m')
    lucro_mes = df[df['mes_referencia'] == mes_atual]['lucro_usd'].sum()
    
    print(f"\n🏆 --- DASHBOARD DE PERFORMANCE ---")
    print(f"   💰 Banca Atual:   ${banca_atual:.2f} (Piso: ${piso_seguranca:.2f})")
    print(f"   📈 Lucro no Mês:  ${lucro_mes:.2f}")
    print(f"   📊 Multiplicação: {banca_atual/BANCA_INICIAL_REAL:.2f}x")
    print("-" * 40)

    # Análise de Sentimento
    sentimento, bombastico, manchete = analyze_news()
    print(f"📊 SENTIMENTO: {sentimento:.2f} {'🚫 BLOQUEIO NOTÍCIA' if bombastico else '✅ OK'}")

    # Escaneamento de Mercado
    print("\n📡 ESCANEANDO OPORTUNIDADES HÍBRIDAS...")
    params = {"vs_currency": "usd", "ids": ",".join(COINS_IDS), "sparkline": "false"}
    market = requests.get(f"{BASE_URL}/coins/markets", headers=HEADERS, params=params).json()

    for coin in market:
        sym = coin['symbol'].upper()
        if not df[(df['symbol'] == sym) & (df['status'] == 'ABERTO')].empty: continue
        
        tech = get_technicals(coin['id'])
        if not tech: continue
        
        price = coin['current_price']
        action, motivo, sl = None, "", 0.0
        valor_alocado = min((banca_atual - piso_seguranca) * RISCO_POR_TRADE_PCT, MAX_VALOR_TRADE)

        # Lógica V44: Tendência ou Grid?
        if tech['adx'] > ADX_TREND_LIMIT and not bombastico:
            if price > tech['d_high'] and price > tech['ema200']:
                action, motivo = "TREND_LONG", "Rompimento de Alta"
                sl = price - (tech['atr'] * 2)
            elif price < tech['d_low'] and price < tech['ema200']:
                action, motivo = "TREND_SHORT", "Rompimento de Baixa"
                sl = price + (tech['atr'] * 2)
        
        elif tech['adx'] < ADX_LATERAL_LIMIT and -0.2 < sentimento < 0.2:
            action, motivo = "GRID_NEUTRAL", "Mercado Lateral"
            valor_alocado *= 0.3 # Mão reduzida no grid
            sl = price - (tech['atr'] * 3)

        if action:
            print(f"   ✅ {sym}: Abrindo {action} (${price:.2f})")
            new_trade = {
                "id": str(uuid.uuid4())[:8], "data_entrada": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "symbol": sym, "tipo": action, "preco_entrada": price, "stop_loss": sl,
                "status": "ABERTO", "resultado": "ANDAMENTO", "lucro_usd": 0.0, 
                "motivo": motivo, "alavancagem": ALAVANCAGEM_MAX, "mes_referencia": mes_atual
            }
            df = pd.concat([df, pd.DataFrame([new_trade])], ignore_index=True)

    df.to_csv(CSV_FILE, index=False)
    print("\n💾 Planilha e Ciclo Atualizados.")

if __name__ == "__main__":
    run_bot_v15()

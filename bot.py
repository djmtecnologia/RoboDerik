import requests
import pandas as pd
import pandas_ta as ta
import feedparser
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import os
from datetime import datetime
import uuid

# --- CONFIGURAÇÕES ---
API_KEY = os.environ.get("CG_API_KEY")
BASE_URL = "https://api.coingecko.com/api/v3"
HEADERS = {"accept": "application/json", "x-cg-demo-api-key": API_KEY}
CSV_FILE = "trades.csv"

# Estratégia de Simulação
TAKE_PROFIT_PCT = 0.03  # Alvo: 3%
STOP_LOSS_PCT = 0.015   # Stop: 1.5%

RSS_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/"
]

COINS = ["bitcoin", "ethereum", "solana", "ripple", "binancecoin"]

# --- FUNÇÕES ---

def load_trades():
    if os.path.exists(CSV_FILE):
        return pd.read_csv(CSV_FILE)
    else:
        columns = ["id", "data_entrada", "symbol", "tipo", "preco_entrada", "stop_loss", "take_profit", "status", "resultado", "data_saida", "preco_saida", "lucro_pct"]
        return pd.DataFrame(columns=columns)

def save_trades(df):
    df.to_csv(CSV_FILE, index=False)
    print("💾 Planilha trades.csv atualizada com sucesso!")

def get_news_sentiment():
    try:
        analyzer = SentimentIntensityAnalyzer()
        total = 0; count = 0
        for url in RSS_FEEDS:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                score = analyzer.polarity_scores(entry.title)['compound']
                total += score; count += 1
        return total / count if count > 0 else 0
    except: return 0

def get_market_data():
    try:
        params = {"vs_currency": "usd", "ids": ",".join(COINS), "sparkline": "false"}
        return requests.get(f"{BASE_URL}/coins/markets", headers=HEADERS, params=params).json()
    except Exception as e:
        print(f"Erro API: {e}")
        return []

def get_technicals(coin_id):
    try:
        url = f"{BASE_URL}/coins/{coin_id}/ohlc?vs_currency=usd&days=1"
        data = requests.get(url, headers=HEADERS).json()
        df = pd.DataFrame(data, columns=["time", "open", "high", "low", "close"])
        df["rsi"] = ta.rsi(df["close"], length=14)
        adx = ta.adx(df['high'], df['low'], df['close'], length=14)
        return df["rsi"].iloc[-1], adx["ADX_14"].iloc[-1]
    except: return 50, 0

# ... (mantenha o resto do código igual até chegar na função run_bot) ...

def run_bot():
    print("🚀 INICIANDO SIMULAÇÃO ROBODERIK...")
    
    # 1. Carregar dados
    df = load_trades()
    market_data = get_market_data()
    news_score = get_news_sentiment()
    
    print(f"\n📰 SENTIMENTO DAS NOTÍCIAS: {news_score:.2f}")
    if news_score > 0.1: print("   -> Otimismo moderado no ar.")
    elif news_score < -0.1: print("   -> Pessimismo/Medo no ar.")
    else: print("   -> Mercado neutro de notícias.")

    if not market_data:
        print("❌ Sem dados de mercado. Abortando.")
        return

    # 2. Monitorar Posições Abertas (Se houver)
    open_trades = df[df['status'] == 'ABERTO']
    if not open_trades.empty:
        print(f"\n🔎 MONITORANDO {len(open_trades)} POSIÇÕES ABERTAS:")
        for index, trade in open_trades.iterrows():
            symbol = trade['symbol']
            current_data = next((item for item in market_data if item['symbol'].upper() == symbol), None)
            
            if current_data:
                curr_price = current_data['current_price']
                print(f"   -> {symbol}: Entrada ${trade['preco_entrada']} | Atual ${curr_price}")
                
                # Lógica de Saída (TP/SL) aqui...
                if curr_price >= trade['take_profit']:
                    print(f"   ✅ WIN em {symbol}!")
                    df.at[index, 'status'] = 'FECHADO'
                    df.at[index, 'resultado'] = 'WIN'
                    df.at[index, 'preco_saida'] = curr_price
                    df.at[index, 'lucro_pct'] = TAKE_PROFIT_PCT * 100
                    df.at[index, 'data_saida'] = datetime.now().strftime("%Y-%m-%d %H:%M")
                elif curr_price <= trade['stop_loss']:
                    print(f"   ❌ LOSS em {symbol}...")
                    df.at[index, 'status'] = 'FECHADO'
                    df.at[index, 'resultado'] = 'LOSS'
                    df.at[index, 'preco_saida'] = curr_price
                    df.at[index, 'lucro_pct'] = -STOP_LOSS_PCT * 100
                    df.at[index, 'data_saida'] = datetime.now().strftime("%Y-%m-%d %H:%M")
    else:
        print("\n💤 Nenhuma posição aberta para monitorar.")

    # 3. Procurar Novas Entradas (Scanner de Mercado)
    print("\n📡 ESCANEANDO MERCADO AGORA:")
    for coin in market_data:
        symbol = coin['symbol'].upper()
        
        # Pula se já estiver comprado
        if not df[(df['symbol'] == symbol) & (df['status'] == 'ABERTO')].empty:
            continue

        price = coin['current_price']
        rsi, adx = get_technicals(coin['id'])
        
        # IMPRIME O DIAGNÓSTICO (Aqui você vê ele trabalhando!)
        status_msg = "AGUARDAR"
        if rsi < 35: status_msg = "INTERESSANTE (Barato)"
        elif rsi > 70: status_msg = "CARO (Sobrecomprado)"
        
        print(f"   🪙 {symbol:<4} (${price:<8}): RSI {rsi:.1f} | ADX {adx:.1f} -> {status_msg}")
        
        # ESTRATÉGIA REAL
        if rsi < 35 and adx > 25 and news_score > -0.2:
            print(f"      🎯 SINAL ENCONTRADO! Comprando {symbol}...")
            tp = price * (1 + TAKE_PROFIT_PCT)
            sl = price * (1 - STOP_LOSS_PCT)
            
            new_trade = {
                "id": str(uuid.uuid4())[:8],
                "data_entrada": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "symbol": symbol,
                "tipo": "LONG",
                "preco_entrada": price,
                "stop_loss": sl,
                "take_profit": tp,
                "status": "ABERTO",
                "resultado": "EM_ANDAMENTO",
                "data_saida": "",
                "preco_saida": 0.0,
                "lucro_pct": 0.0
            }
            # Adiciona nova linha (método compatível atualizado)
            df = pd.concat([df, pd.DataFrame([new_trade])], ignore_index=True)

    # 4. Salvar
    save_trades(df)

if __name__ == "__main__":
    run_bot()

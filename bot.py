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

# --- GESTÃO DE RISCO APERFEIÇOADA V6 ---
VALOR_APOSTA = 100.0      
TAKE_PROFIT_PCT = 0.03    # Alvo: 3%
STOP_LOSS_PCT = 0.02      # Stop: 2% (Aumentei um pouco para dar respiro)
GRID_RANGE_PCT = 0.04     

# Definição de Notícia Bombástica (Impacto > 0.5)
IMPACTO_BOMBASTICO = 0.5 

RSS_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/"
]

COINS = ["bitcoin", "ethereum", "solana", "ripple", "binancecoin"]

# --- FUNÇÕES AUXILIARES ---

def load_trades():
    if os.path.exists(CSV_FILE):
        return pd.read_csv(CSV_FILE)
    else:
        columns = ["id", "data_entrada", "symbol", "tipo", "preco_entrada", "stop_loss", "take_profit", "status", "resultado", "data_saida", "preco_saida", "lucro_pct", "lucro_usd", "motivo"]
        return pd.DataFrame(columns=columns)

def save_trades(df):
    df.to_csv(CSV_FILE, index=False)
    print("💾 Planilha salva.")

def analyze_news_impact():
    try:
        analyzer = SentimentIntensityAnalyzer()
        total_score = 0; count = 0; max_impact = 0; top_headline = ""
        
        print("\n📰 ANALISANDO NOTÍCIAS...")
        for url in RSS_FEEDS:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                score = analyzer.polarity_scores(entry.title)['compound']
                total_score += score
                count += 1
                impact = abs(score)
                if impact > max_impact: max_impact = impact; top_headline = entry.title
                
                emoji = "😐"
                if score > 0.3: emoji = "🟢"
                elif score < -0.3: emoji = "🔴"
                if impact > IMPACTO_BOMBASTICO: emoji = "💣"
                print(f"   {emoji} [{score:.2f}] {entry.title[:50]}...")

        avg_score = total_score / count if count > 0 else 0
        has_bombastic = max_impact >= IMPACTO_BOMBASTICO
        return avg_score, has_bombastic, top_headline
    except: return 0, False, ""

def get_market_data():
    try:
        params = {"vs_currency": "usd", "ids": ",".join(COINS), "sparkline": "false"}
        return requests.get(f"{BASE_URL}/coins/markets", headers=HEADERS, params=params).json()
    except: return []

def get_technicals(coin_id):
    try:
        # Pega 7 dias de velas (H1) para ter dados suficientes para Média Móvel
        url = f"{BASE_URL}/coins/{coin_id}/ohlc?vs_currency=usd&days=7"
        data = requests.get(url, headers=HEADERS).json()
        df = pd.DataFrame(data, columns=["time", "open", "high", "low", "close"])
        
        # Indicadores
        df["rsi"] = ta.rsi(df["close"], length=14)
        adx = ta.adx(df['high'], df['low'], df['close'], length=14)
        
        # NOVO: Média Móvel Exponencial de 50 períodos (Filtro de Tendência)
        df["ema50"] = ta.ema(df["close"], length=50)
        
        current_rsi = df["rsi"].iloc[-1]
        current_adx = adx["ADX_14"].iloc[-1]
        current_ema = df["ema50"].iloc[-1]
        
        return current_rsi, current_adx, current_ema
    except Exception as e:
        print(f"Erro técnico em {coin_id}: {e}")
        return 50, 0, 0

# --- LÓGICA PRINCIPAL ---

def run_bot():
    print(f"🚀 ROBODERIK V6 (FILTRO DE TENDÊNCIA EMA)...")
    
    df = load_trades()
    market_data = get_market_data()
    avg_score, has_bombastic, top_headline = analyze_news_impact()
    
    print(f"\n📊 SENTIMENTO MÉDIO: {avg_score:.2f}")
    if has_bombastic:
        print(f"🚫 ALERTA 💣: {top_headline}")

    if not market_data: return

    # 1. GERENCIAR POSIÇÕES
    open_trades = df[df['status'] == 'ABERTO']
    if not open_trades.empty:
        print(f"\n🔎 GERENCIANDO POSIÇÕES:")
        for index, trade in open_trades.iterrows():
            symbol = trade['symbol']
            curr_data = next((item for item in market_data if item['symbol'].upper() == symbol), None)
            
            if curr_data:
                curr_price = curr_data['current_price']
                print(f"   -> {symbol} ({trade['tipo']}): Entrada ${trade['preco_entrada']} | Atual ${curr_price}")
                
                # ... (Lógica de Saída igual, omitida para brevidade, pode manter a anterior ou copiar do V5) ...
                # VOU REPETIR A LÓGICA DE SAÍDA AQUI PARA GARANTIR QUE NÃO QUEBRE:
                if trade['tipo'] == 'LONG':
                    if curr_price >= trade['take_profit']:
                        df.at[index, 'status'] = 'FECHADO'; df.at[index, 'resultado'] = 'WIN'
                        df.at[index, 'preco_saida'] = curr_price
                        df.at[index, 'lucro_pct'] = TAKE_PROFIT_PCT * 100
                        df.at[index, 'lucro_usd'] = VALOR_APOSTA * TAKE_PROFIT_PCT
                        df.at[index, 'data_saida'] = datetime.now().strftime("%Y-%m-%d %H:%M")
                    elif curr_price <= trade['stop_loss']:
                        df.at[index, 'status'] = 'FECHADO'; df.at[index, 'resultado'] = 'LOSS'
                        df.at[index, 'preco_saida'] = curr_price
                        df.at[index, 'lucro_pct'] = -STOP_LOSS_PCT * 100
                        df.at[index, 'lucro_usd'] = VALOR_APOSTA * -STOP_LOSS_PCT
                        df.at[index, 'data_saida'] = datetime.now().strftime("%Y-%m-%d %H:%M")
                
                elif trade['tipo'] == 'SHORT':
                    if curr_price <= trade['take_profit']:
                        df.at[index, 'status'] = 'FECHADO'; df.at[index, 'resultado'] = 'WIN'
                        df.at[index, 'preco_saida'] = curr_price
                        df.at[index, 'lucro_pct'] = TAKE_PROFIT_PCT * 100
                        df.at[index, 'lucro_usd'] = VALOR_APOSTA * TAKE_PROFIT_PCT
                        df.at[index, 'data_saida'] = datetime.now().strftime("%Y-%m-%d %H:%M")
                    elif curr_price >= trade['stop_loss']:
                        df.at[index, 'status'] = 'FECHADO'; df.at[index, 'resultado'] = 'LOSS'
                        df.at[index, 'preco_saida'] = curr_price
                        df.at[index, 'lucro_pct'] = -STOP_LOSS_PCT * 100
                        df.at[index, 'lucro_usd'] = VALOR_APOSTA * -STOP_LOSS_PCT
                        df.at[index, 'data_saida'] = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 2. ESCANEAR OPORTUNIDADES COM FILTRO DE TENDÊNCIA
    print("\n📡 ESCANEANDO OPORTUNIDADES (V6):")
    for coin in market_data:
        symbol = coin['symbol'].upper()
        if not df[(df['symbol'] == symbol) & (df['status'] == 'ABERTO')].empty: continue

        price = coin['current_price']
        rsi, adx, ema = get_technicals(coin['id'])
        
        status_msg = "AGUARDAR"
        action = None
        motivo = ""

        # FILTRO DE TENDÊNCIA
        is_uptrend = price > ema  # Preço acima da média = Alta
        is_downtrend = price < ema # Preço abaixo da média = Baixa
        
        # --- ESTRATÉGIA 1: LONG (Só se for Uptrend) ---
        # RSI < 35 (Desconto) MAS tem que estar em tendência de alta (Pullback)
        if rsi < 35 and adx > 25 and is_uptrend and avg_score > -0.2:
            status_msg = "SINAL LONG ✅"
            action = "LONG"
            motivo = f"Pullback na Alta (RSI {rsi:.0f})"
            tp = price * (1 + TAKE_PROFIT_PCT)
            sl = price * (1 - STOP_LOSS_PCT)
        
        # --- ESTRATÉGIA 2: SHORT (Só se for Downtrend) ---
        # RSI > 65 (Caro) MAS tem que estar em tendência de baixa (Repique)
        elif rsi > 65 and adx > 25 and is_downtrend and avg_score < 0.2:
            status_msg = "SINAL SHORT 📉"
            action = "SHORT"
            motivo = f"Repique na Baixa (RSI {rsi:.0f})"
            tp = price * (1 - TAKE_PROFIT_PCT)
            sl = price * (1 + STOP_LOSS_PCT)

        # Diagnóstico no Log
        trend_str = "ALTA" if is_uptrend else "BAIXA"
        if status_msg == "AGUARDAR":
            if rsi < 35 and is_downtrend: status_msg = "RSI Baixo mas Tendência de Baixa (PERIGO 🚫)"
            if rsi > 65 and is_uptrend: status_msg = "RSI Alto mas Tendência de Alta (PERIGO 🚫)"

        print(f"   🪙 {symbol:<4}: RSI {rsi:.1f} | Tendência: {trend_str} (EMA {ema:.2f}) -> {status_msg}")

        if action:
            print(f"      💾 Abrindo {action} em {symbol}...")
            new_trade = {
                "id": str(uuid.uuid4())[:8],
                "data_entrada": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "symbol": symbol,
                "tipo": action,
                "preco_entrada": price,
                "stop_loss": sl,
                "take_profit": tp,
                "status": "ABERTO",
                "resultado": "EM_ANDAMENTO",
                "data_saida": "",
                "preco_saida": 0.0,
                "lucro_pct": 0.0,
                "lucro_usd": 0.0,
                "motivo": motivo
            }
            df = pd.concat([df, pd.DataFrame([new_trade])], ignore_index=True)

    save_trades(df)

if __name__ == "__main__":
    run_bot()

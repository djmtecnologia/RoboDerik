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

# --- GESTÃO DE BANCA (NOVO) ---
TOTAL_BANCA = 100.0       # Sua banca total simulada ($100)
VALOR_POR_TRADE = 10.0    # Quanto colocar em cada operação ($10)
# (Isso permite no máximo 10 operações simultâneas)

# --- GESTÃO DE RISCO ---
TAKE_PROFIT_PCT = 0.03    # Alvo: 3%
STOP_LOSS_PCT = 0.02      # Stop: 2%
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
        df = pd.read_csv(CSV_FILE)
        # Blindagem de Data
        if 'data_saida' in df.columns:
            df['data_saida'] = df['data_saida'].astype('object')
        if 'data_entrada' in df.columns:
            df['data_entrada'] = df['data_entrada'].astype('object')
        return df
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
            try:
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
            except: continue

        avg_score = total_score / count if count > 0 else 0
        has_bombastic = max_impact >= IMPACTO_BOMBASTICO
        return avg_score, has_bombastic, top_headline
    except: return 0, False, ""

def get_market_data():
    try:
        params = {"vs_currency": "usd", "ids": ",".join(COINS), "sparkline": "false"}
        response = requests.get(f"{BASE_URL}/coins/markets", headers=HEADERS, params=params)
        return response.json() if response.status_code == 200 else []
    except: return []

def get_technicals(coin_id):
    try:
        url = f"{BASE_URL}/coins/{coin_id}/ohlc?vs_currency=usd&days=7"
        resp = requests.get(url, headers=HEADERS)
        if resp.status_code != 200: return 50, 0, 0
        data = resp.json()
        if not data: return 50, 0, 0

        df = pd.DataFrame(data, columns=["time", "open", "high", "low", "close"])
        df["rsi"] = ta.rsi(df["close"], length=14)
        adx = ta.adx(df['high'], df['low'], df['close'], length=14)
        df["ema50"] = ta.ema(df["close"], length=50)
        
        # Blindagem contra valores vazios
        current_rsi = df["rsi"].iloc[-1] if not pd.isna(df["rsi"].iloc[-1]) else 50.0
        current_ema = df["ema50"].iloc[-1] if not pd.isna(df["ema50"].iloc[-1]) else 0.0
        
        current_adx = 0.0
        if adx is not None and not adx.empty and "ADX_14" in adx.columns:
             val = adx["ADX_14"].iloc[-1]
             if not pd.isna(val): current_adx = val
        
        return current_rsi, current_adx, current_ema
    except Exception as e:
        print(f"Erro técnico silencioso em {coin_id}: {e}")
        return 50, 0, 0

# --- LÓGICA PRINCIPAL ---

def run_bot():
    print(f"🚀 ROBODERIK V8 (GESTÃO DE BANCA)...")
    
    df = load_trades()
    market_data = get_market_data()
    avg_score, has_bombastic, top_headline = analyze_news_impact()
    
    print(f"\n📊 SENTIMENTO MÉDIO: {avg_score:.2f}")
    if has_bombastic: print(f"🚫 ALERTA 💣: {top_headline}")

    if not market_data: return

    # --- 1. CÁLCULO DA BANCA ---
    ordens_abertas = df[df['status'] == 'ABERTO']
    qtd_abertas = len(ordens_abertas)
    saldo_usado = qtd_abertas * VALOR_POR_TRADE
    saldo_livre = TOTAL_BANCA - saldo_usado
    
    print(f"\n💰 EXTRATO DA BANCA:")
    print(f"   Total: ${TOTAL_BANCA:.2f} | Em Jogo: ${saldo_usado:.2f} (x{qtd_abertas})")
    print(f"   LIVRE: ${saldo_livre:.2f}")
    
    # 2. GERENCIAR POSIÇÕES
    if not ordens_abertas.empty:
        print(f"\n🔎 GERENCIANDO POSIÇÕES:")
        for index, trade in ordens_abertas.iterrows():
            symbol = trade['symbol']
            curr_data = next((item for item in market_data if item['symbol'].upper() == symbol), None)
            
            if curr_data:
                curr_price = curr_data['current_price']
                print(f"   -> {symbol} ({trade['tipo']}): Entrada ${trade['preco_entrada']} | Atual ${curr_price}")
                
                # LÓGICA DE SAÍDA (RESUMIDA)
                resultado = None
                lucro_pct = 0.0
                
                if trade['tipo'] == 'LONG':
                    if curr_price >= trade['take_profit']: resultado = 'WIN'; lucro_pct = TAKE_PROFIT_PCT
                    elif curr_price <= trade['stop_loss']: resultado = 'LOSS'; lucro_pct = -STOP_LOSS_PCT
                elif trade['tipo'] == 'SHORT':
                    if curr_price <= trade['take_profit']: resultado = 'WIN'; lucro_pct = TAKE_PROFIT_PCT
                    elif curr_price >= trade['stop_loss']: resultado = 'LOSS'; lucro_pct = -STOP_LOSS_PCT
                
                if resultado:
                    df.at[index, 'status'] = 'FECHADO'
                    df.at[index, 'resultado'] = resultado
                    df.at[index, 'preco_saida'] = curr_price
                    df.at[index, 'lucro_pct'] = lucro_pct * 100
                    df.at[index, 'lucro_usd'] = VALOR_POR_TRADE * lucro_pct
                    df.at[index, 'data_saida'] = datetime.now().strftime("%Y-%m-%d %H:%M")
                    print(f"      {'✅' if resultado == 'WIN' else '❌'} {resultado}! ${df.at[index, 'lucro_usd']:.2f}")

    # 3. ESCANEAR OPORTUNIDADES (COM TRAVA DE BANCA)
    print("\n📡 ESCANEANDO OPORTUNIDADES (V8):")
    
    # --- AQUI ESTÁ A TRAVA ---
    if saldo_livre < VALOR_POR_TRADE:
        print(f"   🚫 BLOQUEADO: Saldo insuficiente para novo trade (Min: ${VALOR_POR_TRADE:.2f})")
        save_trades(df)
        return  # Encerra a função aqui, não deixa escanear
    # -------------------------

    for coin in market_data:
        symbol = coin['symbol'].upper()
        if not df[(df['symbol'] == symbol) & (df['status'] == 'ABERTO')].empty: continue

        price = coin['current_price']
        rsi, adx, ema = get_technicals(coin['id'])
        
        status_msg = "AGUARDAR"
        action = None
        motivo = ""

        is_uptrend = price > ema 
        is_downtrend = price < ema
        
        # ESTRATÉGIAS (Com Filtro EMA)
        if rsi < 35 and adx > 25 and is_uptrend and avg_score > -0.2:
            status_msg = "SINAL LONG ✅"
            action = "LONG"
            motivo = f"Pullback Alta (RSI {rsi:.0f})"
            tp = price * (1 + TAKE_PROFIT_PCT); sl = price * (1 - STOP_LOSS_PCT)
        
        elif rsi > 65 and adx > 25 and is_downtrend and avg_score < 0.2:
            status_msg = "SINAL SHORT 📉"
            action = "SHORT"
            motivo = f"Repique Baixa (RSI {rsi:.0f})"
            tp = price * (1 - TAKE_PROFIT_PCT); sl = price * (1 + STOP_LOSS_PCT)

        trend_str = "ALTA" if is_uptrend else "BAIXA"
        if ema == 0: trend_str = "SEM DADOS"
            
        print(f"   🪙 {symbol:<4}: RSI {rsi:.1f} | Tendência: {trend_str} -> {status_msg}")

        if action:
            # Verifica saldo novamente (caso tenha aberto outro trade no mesmo loop)
            # Mas como já travamos antes do loop, e o loop é rápido, está ok.
            
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
            
            # Atualiza saldo visualmente para o log
            saldo_livre -= VALOR_POR_TRADE
            if saldo_livre < VALOR_POR_TRADE:
                print("      ⚠️ Banca Esgotada para próximos trades.")
                break # Sai do loop para não abrir mais nada

    save_trades(df)

if __name__ == "__main__":
    run_bot()

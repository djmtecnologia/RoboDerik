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

# --- GESTÃO DE BANCA E FUTURES ---
TOTAL_BANCA = 100.0       # Banca Inicial ($)
VALOR_POR_TRADE = 10.0    # Margem por operação ($)
ALAVANCAGEM = 5           # Alavancagem (5x)

# --- GESTÃO DE RISCO PADRÃO ---
DEFAULT_TP_PCT = 0.03     # 3%
DEFAULT_SL_PCT = 0.02     # 2%

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
        # Blindagem de Data e Tipos
        for col in ['data_entrada', 'data_saida']:
            if col in df.columns:
                df[col] = df[col].astype('object')
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
        response = requests.get(f"{BASE_URL}/coins/markets", headers=HEADERS, params=params, timeout=10)
        return response.json() if response.status_code == 200 else []
    except: return []

def get_technicals(coin_id):
    try:
        url = f"{BASE_URL}/coins/{coin_id}/ohlc?vs_currency=usd&days=14"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200: return None
        
        data = resp.json()
        if not data: return None

        df = pd.DataFrame(data, columns=["time", "open", "high", "low", "close"])
        
        # --- CÁLCULO DE INDICADORES ---
        df["rsi"] = ta.rsi(df["close"], length=14)
        adx = ta.adx(df['high'], df['low'], df['close'], length=14)
        df["ema50"] = ta.ema(df["close"], length=50)
        df["sma200"] = ta.sma(df["close"], length=200) 
        df["min_20"] = df["low"].rolling(window=20).min() 
        df["max_20"] = df["high"].rolling(window=20).max()

        last = df.iloc[-1].copy()
        
        technicals = {
            "rsi": last["rsi"] if not pd.isna(last["rsi"]) else 50.0,
            "ema50": last["ema50"] if not pd.isna(last["ema50"]) else 0.0,
            "sma200": last["sma200"] if not pd.isna(last["sma200"]) else 0.0,
            "min_20": last["min_20"] if not pd.isna(last["min_20"]) else 0.0,
            "max_20": last["max_20"] if not pd.isna(last["max_20"]) else 0.0,
            "adx": 0.0
        }

        if adx is not None and not adx.empty and "ADX_14" in adx.columns:
             val = adx["ADX_14"].iloc[-1]
             if not pd.isna(val): technicals["adx"] = val
        
        return technicals
    except Exception as e:
        print(f"Erro técnico em {coin_id}: {e}")
        return None

# --- LÓGICA PRINCIPAL ---

def run_bot():
    print(f"🚀 ROBODERIK V10 (DASHBOARD COMPLETO)...")
    print(f"💰 Alavancagem: {ALAVANCAGEM}x | Margem: ${VALOR_POR_TRADE}")
    
    df = load_trades()
    market_data = get_market_data()
    avg_score, has_bombastic, top_headline = analyze_news_impact()
    
    print(f"\n📊 SENTIMENTO MÉDIO: {avg_score:.2f}")
    if has_bombastic: print(f"🚫 ALERTA 💣: {top_headline}")

    if not market_data: return

    # --- 1. DASHBOARD DE PERFORMANCE E BANCA ---
    ordens_abertas = df[df['status'] == 'ABERTO']
    fechados = df[df['status'] == 'FECHADO']
    
    # Cálculos Estatísticos
    total_fechados = len(fechados)
    wins = len(fechados[fechados['resultado'] == 'WIN'])
    losses = len(fechados[fechados['resultado'] == 'LOSS'])
    taxa_acerto = (wins / total_fechados * 100) if total_fechados > 0 else 0.0
    lucro_total = fechados['lucro_usd'].sum() if total_fechados > 0 else 0.0
    
    # Cálculo de Saldo Disponível (Banca Inicial + Lucro - Margem Travada)
    saldo_atual = TOTAL_BANCA + lucro_total
    saldo_usado = len(ordens_abertas) * VALOR_POR_TRADE
    saldo_livre = saldo_atual - saldo_usado
    
    print(f"\n🏆 --- DASHBOARD DO ROBÔ ---")
    print(f"   🎯 Placar: {wins} WINs | {losses} LOSSes")
    print(f"   📊 Assertividade: {taxa_acerto:.2f}%")
    print(f"   💸 PnL Acumulado: ${lucro_total:.2f}")
    print(f"   💰 Banca Atual: ${saldo_atual:.2f} (Livre: ${saldo_livre:.2f})")
    print(f"-----------------------------")
    
    # --- 2. GERENCIAR POSIÇÕES ---
    if not ordens_abertas.empty:
        print(f"\n🔎 GERENCIANDO POSIÇÕES:")
        for index, trade in ordens_abertas.iterrows():
            symbol = trade['symbol']
            curr_data = next((item for item in market_data if item['symbol'].upper() == symbol), None)
            
            if curr_data:
                curr_price = curr_data['current_price']
                entrada = float(trade['preco_entrada'])
                tp = float(trade['take_profit'])
                sl = float(trade['stop_loss'])
                
                print(f"   -> {symbol} ({trade['tipo']}): Entrada ${entrada} | Atual ${curr_price}")
                
                resultado = None
                
                if trade['tipo'] == 'LONG':
                    if curr_price >= tp: resultado = 'WIN'
                    elif curr_price <= sl: resultado = 'LOSS'
                elif trade['tipo'] == 'SHORT':
                    if curr_price <= tp: resultado = 'WIN'
                    elif curr_price >= sl: resultado = 'LOSS'
                
                if resultado:
                    # Cálculo PnL Futures
                    diff_pct = (abs(curr_price - entrada) / entrada)
                    pnl_liquido = diff_pct * ALAVANCAGEM * VALOR_POR_TRADE
                    if resultado == 'LOSS': pnl_liquido = -pnl_liquido
                    
                    df.at[index, 'status'] = 'FECHADO'
                    df.at[index, 'resultado'] = resultado
                    df.at[index, 'preco_saida'] = curr_price
                    df.at[index, 'lucro_pct'] = (diff_pct * ALAVANCAGEM * 100) if resultado == 'WIN' else -(diff_pct * ALAVANCAGEM * 100)
                    df.at[index, 'lucro_usd'] = pnl_liquido
                    df.at[index, 'data_saida'] = datetime.now().strftime("%Y-%m-%d %H:%M")
                    
                    print(f"      {'✅' if resultado == 'WIN' else '❌'} {resultado}! PnL: ${pnl_liquido:.2f}")

    # --- 3. ESCANEAR OPORTUNIDADES ---
    print("\n📡 ESCANEANDO OPORTUNIDADES (V10):")
    
    if saldo_livre < VALOR_POR_TRADE:
        print(f"   🚫 Sem saldo livre para operar. (Mínimo: ${VALOR_POR_TRADE})")
        save_trades(df)
        return

    for coin in market_data:
        symbol = coin['symbol'].upper()
        if not df[(df['symbol'] == symbol) & (df['status'] == 'ABERTO')].empty: continue

        price = coin['current_price']
        tech = get_technicals(coin['id'])
        
        if not tech: continue
        
        rsi = tech['rsi']; adx = tech['adx']; ema = tech['ema50']
        sma200 = tech['sma200']; min_20 = tech['min_20']; max_20 = tech['max_20']
        
        action = None; motivo = ""; sl = 0.0; tp = 0.0
        
        is_uptrend = price > ema
        is_downtrend = price < ema
        
        # ESTRATÉGIAS V10
        if rsi < 35 and adx > 25 and is_uptrend and avg_score > -0.2:
            action = "LONG"; motivo = f"Trend Pullback (RSI {rsi:.0f})"
            tp = price * (1 + DEFAULT_TP_PCT); sl = price * (1 - DEFAULT_SL_PCT)

        elif rsi > 65 and adx > 25 and is_downtrend and avg_score < 0.2:
            action = "SHORT"; motivo = f"Trend Repique (RSI {rsi:.0f})"
            tp = price * (1 - DEFAULT_TP_PCT); sl = price * (1 + DEFAULT_SL_PCT)

        elif sma200 > 0:
            distancia_sma = (price - sma200) / sma200
            if rsi > 75 and abs(distancia_sma) < 0.02: 
                action = "SHORT"; motivo = "Resistência SMA200"
                tp = price * (1 - 0.04); sl = price * (1 + 0.02)

        elif rsi < 20: 
             action = "LONG"; motivo = f"Oversold Extremo (RSI {rsi:.0f})"
             tp = price * (1 + 0.02); sl = price * (1 - 0.03)

        elif min_20 > 0 and price < min_20 and rsi < 40 and is_downtrend:
             action = "SHORT"; motivo = "Breakout Suporte (Donchian)"
             tp = price * (1 - 0.05); sl = price * (1 + 0.02)

        print(f"   🪙 {symbol:<4}: RSI {rsi:.1f} | EMA {ema:.1f} | SMA200 {sma200:.1f} -> {motivo if action else 'AGUARDAR'}")

        if action:
            print(f"      ⚡ Abrindo {action} em {symbol} ({motivo})...")
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
            
            saldo_livre -= VALOR_POR_TRADE
            if saldo_livre < VALOR_POR_TRADE: break

    save_trades(df)

if __name__ == "__main__":
    run_bot()

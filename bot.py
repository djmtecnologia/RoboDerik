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

# --- GESTÃO DE BANCA E RISCO INSTITUCIONAL ---
TOTAL_BANCA = 100.0       
VALOR_POR_TRADE = 10.0    
ALAVANCAGEM = 5
MAX_OPEN_POSITIONS = 3    # Diversificação forçada
KILL_SWITCH_PCT = 0.10    # Trava de Pânico (10% de perda no dia)

# --- PARAMETROS PRO (ATR & TRAILING) ---
ATR_PERIOD = 14           
ATR_MULTIPLIER_SL = 1.5   
ATR_MULTIPLIER_TP = 3.0   
TRAILING_TRIGGER = 1.0    

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
        for col in ['data_entrada', 'data_saida']:
            if col in df.columns: df[col] = df[col].astype('object')
        return df
    else:
        columns = ["id", "data_entrada", "symbol", "tipo", "preco_entrada", "stop_loss", "take_profit", "status", "resultado", "data_saida", "preco_saida", "lucro_pct", "lucro_usd", "motivo", "atr_entrada"]
        return pd.DataFrame(columns=columns)

def save_trades(df):
    df.to_csv(CSV_FILE, index=False)
    print("💾 Planilha salva.")

def check_kill_switch(df):
    hoje = datetime.now().strftime("%Y-%m-%d")
    trades_hoje = df[df['data_saida'].astype(str).str.startswith(hoje)]
    
    pnl_hoje = 0.0
    if not trades_hoje.empty:
        pnl_hoje = trades_hoje['lucro_usd'].sum()
        perda_maxima = TOTAL_BANCA * -KILL_SWITCH_PCT
        
        if pnl_hoje <= perda_maxima:
            return True, pnl_hoje 
            
    return False, pnl_hoje

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
                    total_score += score; count += 1; impact = abs(score)
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
        df["rsi"] = ta.rsi(df["close"], length=14)
        df["adx"] = ta.adx(df['high'], df['low'], df['close'], length=14)["ADX_14"]
        df["ema50"] = ta.ema(df["close"], length=50)
        df["sma200"] = ta.sma(df["close"], length=200) 
        df["atr"] = ta.atr(df['high'], df['low'], df['close'], length=ATR_PERIOD)
        df["min_20"] = df["low"].rolling(window=20).min() 
        df["max_20"] = df["high"].rolling(window=20).max()
        last = df.iloc[-1].copy()
        technicals = {
            "rsi": last["rsi"] if not pd.isna(last["rsi"]) else 50.0,
            "ema50": last["ema50"] if not pd.isna(last["ema50"]) else 0.0,
            "sma200": last["sma200"] if not pd.isna(last["sma200"]) else 0.0,
            "atr": last["atr"] if not pd.isna(last["atr"]) else 0.0,
            "min_20": last["min_20"] if not pd.isna(last["min_20"]) else 0.0,
            "max_20": last["max_20"] if not pd.isna(last["max_20"]) else 0.0,
            "adx": last["adx"] if not pd.isna(last["adx"]) else 0.0,
        }
        return technicals
    except Exception as e:
        print(f"Erro técnico em {coin_id}: {e}")
        return None

# --- LÓGICA PRINCIPAL ---

def run_bot():
    print(f"🚀 ROBODERIK V13 (DASHBOARD + RISK MANAGER)...")
    
    df = load_trades()
    
    # --- 1. DASHBOARD DE PERFORMANCE (Assertividade) ---
    ordens_abertas = df[df['status'] == 'ABERTO']
    fechados = df[df['status'] == 'FECHADO']
    
    total_fechados = len(fechados)
    wins = len(fechados[fechados['resultado'] == 'WIN'])
    losses = len(fechados[fechados['resultado'] == 'LOSS'])
    
    # Cálculo da Assertividade
    taxa_acerto = (wins / total_fechados * 100) if total_fechados > 0 else 0.0
    
    lucro_total = fechados['lucro_usd'].sum() if not fechados.empty else 0.0
    saldo_atual = TOTAL_BANCA + lucro_total
    saldo_livre = saldo_atual - (len(ordens_abertas) * VALOR_POR_TRADE)
    
    print(f"\n🏆 --- DASHBOARD DE PERFORMANCE ---")
    print(f"   🎯 Placar:       {wins} WINs  |  {losses} LOSSes")
    print(f"   📊 Assertividade: {taxa_acerto:.2f}%")
    print(f"   💸 Lucro Líquido: ${lucro_total:.2f}")
    print(f"   💰 Banca Atual:   ${saldo_atual:.2f} (Livre: ${saldo_livre:.2f})")
    print(f"------------------------------------")

    # 2. VERIFICAÇÃO DE KILL SWITCH
    kill_activated, pnl_hoje = check_kill_switch(df)
    if kill_activated:
        print(f"\n💀 KILL SWITCH ATIVADO! Perda do dia: ${pnl_hoje:.2f}")
        print("🚫 Robô bloqueado temporariamente.")
        return 
        
    market_data = get_market_data()
    avg_score, has_bombastic, top_headline = analyze_news_impact()
    
    print(f"\n📊 SENTIMENTO: {avg_score:.2f}")
    if has_bombastic: print(f"🚫 ALERTA 💣: {top_headline}")

    if not market_data: return

    # --- 3. GERENCIAR POSIÇÕES (COM TRAILING) ---
    if not ordens_abertas.empty:
        print(f"\n🔎 GERENCIANDO POSIÇÕES:")
        for index, trade in ordens_abertas.iterrows():
            symbol = trade['symbol']
            curr_data = next((item for item in market_data if item['symbol'].upper() == symbol), None)
            if curr_data:
                curr_price = curr_data['current_price']
                entrada = float(trade['preco_entrada'])
                sl = float(trade['stop_loss'])
                tp = float(trade['take_profit'])
                atr_entrada = float(trade['atr_entrada']) if 'atr_entrada' in trade and pd.notna(trade['atr_entrada']) else (entrada * 0.01)
                
                print(f"   -> {symbol} ({trade['tipo']}): ${entrada} | Atual ${curr_price} | SL ${sl:.2f}")
                
                novo_sl = sl; resultado = None; msg_trailing = ""

                # TRAILING LONG
                if trade['tipo'] == 'LONG':
                    if curr_price > (entrada + (atr_entrada * TRAILING_TRIGGER)) and sl < entrada:
                        novo_sl = entrada * 1.001
                        msg_trailing = "🛡️ Trailing Long: 0x0"
                    elif curr_price > (sl + (atr_entrada * 2)):
                        novo_sl = curr_price - (atr_entrada * 1.5)
                        msg_trailing = "🛡️ Trailing Long: Subindo"
                    if curr_price >= tp: resultado = 'WIN'
                    elif curr_price <= sl: resultado = 'LOSS'

                # TRAILING SHORT
                elif trade['tipo'] == 'SHORT':
                    if curr_price < (entrada - (atr_entrada * TRAILING_TRIGGER)) and sl > entrada:
                        novo_sl = entrada * 0.999
                        msg_trailing = "🛡️ Trailing Short: 0x0"
                    elif curr_price < (sl - (atr_entrada * 2)):
                        novo_sl = curr_price + (atr_entrada * 1.5)
                        msg_trailing = "🛡️ Trailing Short: Descendo"
                    if curr_price <= tp: resultado = 'WIN'
                    elif curr_price >= sl: resultado = 'LOSS'

                # TRAILING NEUTRO
                elif trade['tipo'] == 'NEUTRO':
                    if curr_price > (entrada + atr_entrada) and sl < entrada:
                        novo_sl = entrada * 1.001
                        msg_trailing = "🛡️ Grid: 0x0"
                    elif curr_price > (sl + (atr_entrada * 2)):
                        novo_sl = curr_price - (atr_entrada * 1.5)
                        msg_trailing = "🛡️ Grid: Seguindo Alta"
                    if curr_price >= tp: resultado = 'WIN'
                    elif curr_price <= sl: resultado = 'LOSS'

                if novo_sl != sl and not resultado:
                    df.at[index, 'stop_loss'] = novo_sl
                    print(f"      {msg_trailing}")

                if resultado:
                    diff_pct = (abs(curr_price - entrada) / entrada)
                    pnl_liquido = diff_pct * ALAVANCAGEM * VALOR_POR_TRADE
                    if resultado == 'LOSS': pnl_liquido = -pnl_liquido
                    df.at[index, 'status'] = 'FECHADO'
                    df.at[index, 'resultado'] = resultado
                    df.at[index, 'preco_saida'] = curr_price
                    df.at[index, 'lucro_usd'] = pnl_liquido
                    df.at[index, 'data_saida'] = datetime.now().strftime("%Y-%m-%d %H:%M")
                    print(f"      {'✅' if resultado == 'WIN' else '❌'} {resultado}! PnL: ${pnl_liquido:.2f}")

    # --- 4. ESCANEAR ---
    print("\n📡 ESCANEANDO (V13):")
    
    if saldo_livre < VALOR_POR_TRADE:
        print(f"   🚫 Sem saldo livre.")
        save_trades(df); return
        
    if len(ordens_abertas) >= MAX_OPEN_POSITIONS:
        print(f"   🚫 Limite de exposição atingido ({len(ordens_abertas)}/{MAX_OPEN_POSITIONS}).")
        save_trades(df); return

    for coin in market_data:
        symbol = coin['symbol'].upper()
        if not df[(df['symbol'] == symbol) & (df['status'] == 'ABERTO')].empty: continue
        
        price = coin['current_price']
        tech = get_technicals(coin['id'])
        if not tech or tech['atr'] == 0: continue
        
        rsi = tech['rsi']; adx = tech['adx']; ema = tech['ema50']
        atr = tech['atr']; min_20 = tech['min_20']

        action = None; motivo = ""; sl = 0.0; tp = 0.0
        is_uptrend = price > ema; is_downtrend = price < ema
        dist_sl = atr * ATR_MULTIPLIER_SL; dist_tp = atr * ATR_MULTIPLIER_TP

        # ESTRATÉGIAS V13
        if rsi < 35 and adx > 25 and is_uptrend and avg_score > -0.2:
            action = "LONG"; motivo = f"Trend Pullback (RSI {rsi:.0f})"
            sl = price - dist_sl; tp = price + dist_tp

        elif rsi > 65 and adx > 25 and is_downtrend and avg_score < 0.2:
            action = "SHORT"; motivo = f"Trend Repique (RSI {rsi:.0f})"
            sl = price + dist_sl; tp = price - dist_tp
            
        elif adx < 20 and 45 <= rsi <= 55 and not has_bombastic:
            action = "NEUTRO"; motivo = "Grid Lateral"
            sl = price - (atr * 2); tp = price + (atr * 2)

        print(f"   🪙 {symbol:<4}: RSI {rsi:.1f} | ATR ${atr:.2f} -> {motivo if action else 'AGUARDAR'}")

        if action:
            print(f"      ⚡ Abrindo {action} em {symbol}...")
            new_trade = {
                "id": str(uuid.uuid4())[:8], "data_entrada": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "symbol": symbol, "tipo": action, "preco_entrada": price,
                "stop_loss": sl, "take_profit": tp, "atr_entrada": atr,
                "status": "ABERTO", "resultado": "EM_ANDAMENTO",
                "data_saida": "", "preco_saida": 0.0, "lucro_pct": 0.0, "lucro_usd": 0.0, "motivo": motivo
            }
            df = pd.concat([df, pd.DataFrame([new_trade])], ignore_index=True)
            
            saldo_livre -= VALOR_POR_TRADE
            if saldo_livre < VALOR_POR_TRADE: break
            if len(df[df['status']=='ABERTO']) >= MAX_OPEN_POSITIONS: break

    save_trades(df)

if __name__ == "__main__":
    run_bot()

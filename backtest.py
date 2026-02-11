import yfinance as yf
import pandas as pd
import pandas_ta as ta
import numpy as np

# --- CONFIGURAÇÕES DA SIMULAÇÃO ---
START_DATE = "2025-01-01"
END_DATE = "2026-02-10"
BANCA_INICIAL = 100.0
VALOR_POR_TRADE = 10.0  # Entra com $10 por trade
ALAVANCAGEM = 5         # Futures 5x
TAXA_CORRETORA = 0.0006 # 0.06% por ordem (padrão Binance Futures)

# --- ATIVOS PARA TESTE ---
# Vamos testar os principais que o robô opera
SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD"]

# --- PARÂMETROS DA ESTRATÉGIA V13 ---
ATR_PERIOD = 14
EMA_PERIOD = 50
RSI_PERIOD = 14
ATR_SL_MULT = 1.5
ATR_TP_MULT = 3.0

def rodar_backtest(symbol):
    print(f"⏳ Baixando dados para {symbol}...")
    # Baixa dados diários (ou horários se disponível, yfinance limita horário antigo)
    # Para período longo (1 ano), usamos 1h ou 1d. O ideal para scalp é 15m, 
    # mas yfinance só dá 60 dias de 15m. Vamos testar no Gráfico de 1H (Hourly).
    df = yf.download(symbol, start=START_DATE, end=END_DATE, interval="1h", progress=False)
    
    if df.empty:
        print("❌ Sem dados.")
        return [], 0, 0

    # --- CÁLCULO DE INDICADORES (IGUAL V13) ---
    df['RSI'] = ta.rsi(df['Close'], length=RSI_PERIOD)
    df['EMA50'] = ta.ema(df['Close'], length=EMA_PERIOD)
    df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=ATR_PERIOD)
    df['ADX'] = ta.adx(df['High'], df['Low'], df['Close'], length=14)['ADX_14']
    
    trades = []
    banca = BANCA_INICIAL
    posicao = None # None, 'LONG', 'SHORT'
    
    entry_price = 0
    sl = 0
    tp = 0
    
    wins = 0
    losses = 0
    
    # Loop Candle a Candle (Simulação)
    for i in range(50, len(df)):
        curr = df.iloc[i]
        prev = df.iloc[i-1]
        
        price = float(curr['Close'])
        rsi = float(curr['RSI'])
        adx = float(curr['ADX'])
        ema = float(curr['EMA50'])
        atr = float(curr['ATR'])
        
        # 1. VERIFICAR SAÍDA (Se tiver posição)
        if posicao:
            resultado = None
            pnl = 0
            
            if posicao == 'LONG':
                if price >= tp: resultado = 'WIN'
                elif price <= sl: resultado = 'LOSS'
            elif posicao == 'SHORT':
                if price <= tp: resultado = 'WIN'
                elif price >= sl: resultado = 'LOSS'
            
            if resultado:
                # Calculo PnL com Alavancagem e Taxas
                diff_pct = abs(price - entry_price) / entry_price
                bruto = diff_pct * ALAVANCAGEM * VALOR_POR_TRADE
                
                if resultado == 'LOSS': bruto = -bruto
                
                # Desconta taxas (entrada + saida)
                custo_taxas = (VALOR_POR_TRADE * ALAVANCAGEM) * (TAXA_CORRETORA * 2)
                liquido = bruto - custo_taxas
                
                trades.append(liquido)
                if liquido > 0: wins += 1
                else: losses += 1
                
                posicao = None # Zera posição
                continue # Vai pro próximo candle

        # 2. VERIFICAR ENTRADA (Lógica V13)
        if posicao is None:
            # Filtro de Tendência
            is_uptrend = price > ema
            is_downtrend = price < ema
            
            # Distâncias ATR
            dist_sl = atr * ATR_SL_MULT
            dist_tp = atr * ATR_TP_MULT
            
            # LONG (Trend Pullback)
            if rsi < 35 and adx > 25 and is_uptrend:
                posicao = 'LONG'
                entry_price = price
                sl = price - dist_sl
                tp = price + dist_tp
            
            # SHORT (Trend Repique)
            elif rsi > 65 and adx > 25 and is_downtrend:
                posicao = 'SHORT'
                entry_price = price
                sl = price + dist_sl
                tp = price - dist_tp

    return trades, wins, losses

# --- EXECUÇÃO GERAL ---
print(f"📊 INICIANDO BACKTEST V13 ({START_DATE} a {END_DATE})")
print(f"💰 Banca Inicial: ${BANCA_INICIAL} | Alavancagem: {ALAVANCAGEM}x\n")

total_pnl = 0
total_wins = 0
total_losses = 0

for symbol in SYMBOLS:
    trades, w, l = rodar_backtest(symbol)
    pnl_symbol = sum(trades)
    total_pnl += pnl_symbol
    total_wins += w
    total_losses += l
    
    print(f"   🪙 {symbol}: {w} Wins / {l} Losses | Lucro Líquido: ${pnl_symbol:.2f}")

print("\n" + "="*30)
print(f"🏆 RESULTADO FINAL DA SIMULAÇÃO")
print("="*30)
saldo_final = BANCA_INICIAL + total_pnl
total_trades = total_wins + total_losses
assertividade = (total_wins / total_trades * 100) if total_trades > 0 else 0

print(f"💵 Saldo Final:   ${saldo_final:.2f}")
print(f"📈 Lucro Total:   ${total_pnl:.2f} ({(total_pnl/BANCA_INICIAL)*100:.1f}%)")
print(f"🎯 Assertividade: {assertividade:.2f}%")
print(f"🎲 Total Trades:  {total_trades}")
print("="*30)

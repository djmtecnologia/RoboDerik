import sys
import subprocess
import time
from datetime import datetime
import json
import requests
import pandas as pd
import numpy as np

# --- ESCOLHA O CENÁRIO ---
CENARIO = 1

if CENARIO == 1:
    DATA_INICIO_STR = "2021-01-01"
    DATA_FIM_STR    = "2021-12-31"
    NOME_CENARIO    = "🚀 BULL RUN 2021 (ALVO: $7K)"
elif CENARIO == 2:
    DATA_INICIO_STR = "2022-01-01"
    DATA_FIM_STR    = "2022-12-31"
    NOME_CENARIO    = "🛡️ BEAR 2022"
else:
    DATA_INICIO_STR = "2025-01-01"
    DATA_FIM_STR    = "2026-02-16"
    NOME_CENARIO    = "🛡️ MARKET 2025/26"

# --- CONFIGURAÇÕES V134 (THE LEVIATHAN - STREAK BOOSTER) ---
BANCA_INICIAL = 60.00

# PORTFÓLIO
COINS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT"] 
TIMEFRAME = "4h"

# PARÂMETROS TÉCNICOS (O MOTOR V132)
EMA_TREND       = 200   
ADX_MIN         = 30    # O Filtro que salvou a banca
ATR_LEN         = 14
ST_MULTIPLIER   = 3.0   

# GESTÃO LEVIATÃ (RISCO VARIÁVEL POR SEQUÊNCIA)
ALAVANCAGEM     = 5     
RISCO_BASE      = 0.04  # 4% (Entrada Padrão)
RISCO_MAX       = 0.08  # 8% (Teto de Agressividade)
BOOST_STEP      = 0.01  # Aumenta 1% a cada vitória seguida
MAX_PYRAMID     = 4     
PYRAMID_STEP    = 1.0   
MAX_TRADES_SIMULTANEOS = 3

# CUSTOS
TAXA_OPERACIONAL = 0.001

# --- MOTOR DE DADOS ---
def fetch_binance_data(symbol, start_date_str, end_date_str=None):
    interval = TIMEFRAME
    limit = 1000
    base_url = "https://data-api.binance.vision/api/v3/klines"
    
    start_dt = datetime.strptime(start_date_str, "%Y-%m-%d")
    start_ts = int(start_dt.timestamp() * 1000)
    
    if end_date_str:
        end_ts = int(datetime.strptime(end_date_str, "%Y-%m-%d").timestamp() * 1000)
    else:
        end_ts = int(datetime.now().timestamp() * 1000)

    print(f"📥 {symbol}...", end=" ", flush=True)
    all_klines = []
    current_start = start_ts
    
    while True:
        params = {"symbol": symbol, "interval": interval, "startTime": current_start, "limit": limit}
        try:
            response = requests.get(base_url, params=params, timeout=10)
            if response.status_code != 200: break
            data = response.json()
            if not data: break
            
            chunk = [x for x in data if x[0] <= end_ts]
            if not chunk: break
            
            all_klines.extend(chunk)
            current_start = chunk[-1][0] + 1
            if len(data) < limit or current_start > end_ts: break
            time.sleep(0.1) 
        except: break
            
    print(f"✅ {len(all_klines)}")
    if not all_klines: return None
    
    df = pd.DataFrame(all_klines, columns=["open_time", "open", "high", "low", "close", "volume", "ct", "qv", "tr", "tb", "tq", "ig"])
    df["date"] = pd.to_datetime(df["open_time"], unit="ms")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df.set_index("date", inplace=True)
    return df

# --- INDICADORES ---
def calcular_indicadores_nativos(df):
    close = df['close']
    high = df['high']
    low = df['low']
    
    # EMA TREND
    df['ema_trend'] = close.ewm(span=EMA_TREND, adjust=False).mean()

    # ATR
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    df['atr'] = tr.ewm(alpha=1/ATR_LEN, adjust=False).mean()

    # ADX
    up, down = high - high.shift(1), low.shift(1) - low
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr_smooth = tr.ewm(alpha=1/14, adjust=False).mean()
    plus_di = 100 * (pd.Series(plus_dm, index=df.index).ewm(alpha=1/14, adjust=False).mean() / tr_smooth)
    minus_di = 100 * (pd.Series(minus_dm, index=df.index).ewm(alpha=1/14, adjust=False).mean() / tr_smooth)
    dx = 100 * (abs(plus_di - minus_di) / (plus_di + minus_di))
    df['adx'] = dx.ewm(alpha=1/14, adjust=False).mean()

    # SuperTrend
    hl2 = (high + low) / 2
    df['st_basic_upper'] = hl2 + (ST_MULTIPLIER * df['atr'])
    df['st_basic_lower'] = hl2 - (ST_MULTIPLIER * df['atr'])
    
    st_lower = [0.0] * len(df)
    st_upper = [0.0] * len(df)
    st_trend = [1] * len(df)
    
    close_vals = close.values
    basic_upper = df['st_basic_upper'].values
    basic_lower = df['st_basic_lower'].values
    
    for i in range(1, len(df)):
        if basic_lower[i] > st_lower[i-1] or close_vals[i-1] < st_lower[i-1]: st_lower[i] = basic_lower[i]
        else: st_lower[i] = st_lower[i-1]
        if basic_upper[i] < st_upper[i-1] or close_vals[i-1] > st_upper[i-1]: st_upper[i] = basic_upper[i]
        else: st_upper[i] = st_upper[i-1]
        if st_trend[i-1] == 1:
            if close_vals[i] < st_lower[i]: st_trend[i] = -1
            else: st_trend[i] = 1
        else:
            if close_vals[i] > st_upper[i]: st_trend[i] = 1
            else: st_trend[i] = -1
                
    df['supertrend'] = np.where(np.array(st_trend) == 1, st_lower, st_upper)
    df['st_dir'] = st_trend

    df.dropna(inplace=True)
    return df

# --- GESTÃO ---
def calcular_tamanho_posicao(banca_atual, streak_wins):
    # Risco Base + (Wins * Boost), travado no Max
    risco_atual = RISCO_BASE + (streak_wins * BOOST_STEP)
    if risco_atual > RISCO_MAX: risco_atual = RISCO_MAX
    return banca_atual * risco_atual

def run_backtest_v134():
    print(f"🐋 INICIANDO V134 THE LEVIATHAN (STREAK COMPOUNDING)...")
    print(f"🌍 Cenário: {NOME_CENARIO} ({DATA_INICIO_STR} -> {DATA_FIM_STR})")
    
    datasets = {}
    todos_timestamps = set()
    
    for coin in COINS:
        df = fetch_binance_data(coin, DATA_INICIO_STR, DATA_FIM_STR)
        if df is not None and not df.empty:
            df = calcular_indicadores_nativos(df)
            datasets[coin] = df.to_dict('index')
            todos_timestamps.update(df.index)
    
    timeline = sorted(list(todos_timestamps))
    print(f"\n⚡ Processando {len(timeline)} velas de 4H...")

    banca_atual = BANCA_INICIAL
    pico_banca = BANCA_INICIAL
    max_drawdown = 0.0
    
    posicoes_abertas = {} 
    historico = []
    
    # CONTROLE DE STREAK (SEQUÊNCIA DE VITÓRIAS)
    # { 'BTCUSDT': 0, 'ETHUSDT': 2 ... }
    streak_map = {coin: 0 for coin in COINS}

    for ts in timeline:
        if banca_atual > pico_banca: pico_banca = banca_atual
        dd_atual = (pico_banca - banca_atual) / pico_banca
        if dd_atual > max_drawdown: max_drawdown = dd_atual

        # A. GESTÃO ATIVA
        for symbol in list(posicoes_abertas.keys()):
            pos = posicoes_abertas[symbol]
            if ts not in datasets[symbol]: continue
            candle = datasets[symbol][ts]
            
            fechou = False; motivo = ""; p_saida = 0.0
            
            # 1. SAÍDA (SuperTrend Reversal) - SIMPLES E EFICIENTE
            if candle['close'] < candle['supertrend']:
                fechou = True; motivo = "TP/SL (SuperTrend)"; p_saida = candle['close']
            
            # 2. LIQUIDAÇÃO
            elif candle['low'] <= (pos['preco_medio'] * (1 - (0.90 / ALAVANCAGEM))):
                fechou = True; motivo = "💀 LIQUIDADO"; p_saida = pos['preco_medio'] * (1 - (0.90 / ALAVANCAGEM))
            
            # 3. PIRAMIDAGEM (V132 Style)
            elif pos['adds'] < MAX_PYRAMID:
                # Só adiciona se tendência EXPLOSIVA continuar
                if candle['adx'] > ADX_MIN:
                    trigger = candle['atr'] * PYRAMID_STEP
                    if (candle['close'] - pos['ultima_entrada']) > trigger:
                        # Nota: Adições usam o risco ATUAL do streak
                        streak_atual = streak_map[symbol]
                        margem_extra = calcular_tamanho_posicao(banca_atual, streak_atual)
                        
                        if (banca_atual - pos['margem_total'] - margem_extra) > 0:
                            novo_preco = candle['close']
                            total_notional = pos['margem_total'] * ALAVANCAGEM
                            novo_notional = margem_extra * ALAVANCAGEM
                            pos['preco_medio'] = ((total_notional * pos['preco_medio']) + (novo_notional * novo_preco)) / (total_notional + novo_notional)
                            
                            pos['margem_total'] += margem_extra
                            pos['adds'] += 1
                            pos['ultima_entrada'] = novo_preco

            if fechou:
                if motivo != "💀 LIQUIDADO":
                    pnl_pct = (p_saida / pos['preco_medio']) - 1
                    notional = pos['margem_total'] * ALAVANCAGEM
                    custo_taxas = notional * (TAXA_OPERACIONAL * 2)
                    lucro_bruto = notional * pnl_pct
                    lucro_liquido = lucro_bruto - custo_taxas
                else:
                    lucro_liquido = -pos['margem_total']
                
                banca_atual += lucro_liquido
                if banca_atual < 5: banca_atual = 0; break
                
                # ATUALIZA STREAK
                if lucro_liquido > 0:
                    streak_map[symbol] += 1
                else:
                    streak_map[symbol] = 0 # Reset se perder
                
                historico.append({"data": ts, "symbol": symbol, "res": "WIN" if lucro_liquido > 0 else "LOSS", "lucro": lucro_liquido, "banca": banca_atual})
                del posicoes_abertas[symbol]

        if banca_atual <= 0: break

        # B. ENTRADAS V134 (LEVIATHAN)
        if len(posicoes_abertas) < MAX_TRADES_SIMULTANEOS and banca_atual > 10:
            for symbol in COINS:
                if symbol in posicoes_abertas: continue
                if ts not in datasets[symbol]: continue
                candle = datasets[symbol][ts]
                
                sinal = None
                
                # ADX > 30 (Qualidade Máxima)
                if candle['adx'] > ADX_MIN:
                    if candle['close'] > candle['ema_trend']:
                        if candle['st_dir'] == 1:
                            sinal = 'buy'
                
                if sinal:
                    # Risco baseado na sequência de vitórias
                    streak_atual = streak_map[symbol]
                    margem_ini = calcular_tamanho_posicao(banca_atual, streak_atual)
                    
                    posicoes_abertas[symbol] = {
                        "tipo": sinal, 
                        "preco_medio": candle['close'],
                        "ultima_entrada": candle['close'], 
                        "margem_total": margem_ini,
                        "adds": 0
                    }
                    if len(posicoes_abertas) >= MAX_TRADES_SIMULTANEOS: break

    # RELATÓRIO
    if banca_atual <= 5: lucro_liq = -BANCA_INICIAL; roi = -100
    else: lucro_liq = banca_atual - BANCA_INICIAL; roi = (lucro_liq / BANCA_INICIAL) * 100

    wins = len([x for x in historico if x['res'] == 'WIN'])
    total = len(historico)
    
    print("\n" + "="*60)
    print(f"🐋 RESULTADO V134 (THE LEVIATHAN)")
    print("="*60)
    print(f"💰 Banca Inicial:   ${BANCA_INICIAL:.2f}")
    print(f"💰 Banca Final:     ${banca_atual:.2f}")
    print(f"📉 Max Drawdown:    {max_drawdown*100:.2f}%")
    print(f"📈 Lucro Líquido:   ${lucro_liq:.2f} ({roi:.2f}%)")
    print(f"🎲 Trades Totais:   {total}")
    print(f"🎯 Win Rate:        {(wins/total*100) if total > 0 else 0:.2f}%")
    print("="*60)
    
    if total > 0:
        tops = sorted(historico, key=lambda x: x['lucro'], reverse=True)[:3]
        print("🏆 Monstros do Mar:")
        for t in tops:
            print(f"   {t['symbol']} | +${t['lucro']:.2f}")

if __name__ == "__main__":
    try: run_backtest_v134()
    except KeyboardInterrupt: print("\n🛑 Interrompido.")
  

import sys
import subprocess
import os
import json
import time
from datetime import datetime
import traceback

# --- AUTO-INSTALAÇÃO ---
def install(package):
    try:
        __import__(package)
    except ImportError:
        print(f"📦 Instalando {package}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", package])

for lib in ["yfinance", "pandas", "pandas_ta", "numpy", "pytz"]:
    install(lib)

import yfinance as yf
import pandas as pd
import pandas_ta as ta
import numpy as np
import pytz

# --- CONFIGURAÇÕES DE AMBIENTE ---
FUSO_BR = pytz.timezone('America/Sao_Paulo')

def obter_data_hora_br():
    return datetime.now(FUSO_BR).strftime("%d/%m/%Y %H:%M:%S")

def obter_data_hoje_br():
    return datetime.now(FUSO_BR).strftime("%d/%m/%Y")

# --- 💎 CONFIGURAÇÕES V164 (ASYMMETRIC COMPOUNDER) ---
SYMBOL_MAP = {
    "BTC-USD": "Bitcoin", 
    "ETH-USD": "Ethereum", 
    "SOL-USD": "Solana",
    "BNB-USD": "Binance Coin",
    "ADA-USD": "Cardano"
}

# V164 roda melhor em 4H, mas para teste rápido em bot usamos 1H ou 15m.
# Se usar 15m, a EMA 800 representa ~8 dias de tendência.
TIMEFRAME = "15m" 
ALAVANCAGEM = 1 # Spot ou ajuste na exchange (O bot calcula o lote)

# RISK MANAGEMENT V164
RISK_SUMMER = 0.06    # 6% da banca em Tendência de Alta Limpa
RISK_WINTER = 0.02    # 2% da banca em Mercado de Baixa (Defesa)
MAX_ADDS = 1          # Máximo de 1 piramidagem (Dobra a mão 1 vez)

STATE_FILE = "estado_v164.json"

def carregar_estado():
    padrao = {
        "banca_atual": 60.0,
        "pico_banca": 60.0,
        "posicao_aberta": None,
        "historico_trades": [],
        "data_hoje": obter_data_hoje_br(),
        "pnl_hoje": 0.0
    }
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                carregado = json.load(f)
                padrao.update(carregado)
        except Exception as e:
            print(f"⚠️ Resetando estado: {e}")
    return padrao

def salvar_estado(estado):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(estado, f, indent=4)
    except Exception as e:
        print(f"❌ Erro ao salvar: {e}")

def obter_dados_v164(symbol):
    try:
        # Precisa de bastante histórico para a EMA 800
        df = yf.download(symbol, period="60d", interval=TIMEFRAME, progress=False)
        
        if df.empty or len(df) < 805: 
            # print(f"⚠️ Dados insuficientes para {symbol} (Need 800+ candles)")
            return None
        
        if isinstance(df.columns, pd.MultiIndex): 
            df.columns = df.columns.get_level_values(0)
        
        df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
        df.columns = [c.lower() for c in df.columns]

        # --- INDICADORES V164 ---
        # Médias Móveis
        df['ema20'] = ta.ema(df['close'], length=20)
        df['ema50'] = ta.ema(df['close'], length=50)   # Exit Lento
        df['ema200'] = ta.ema(df['close'], length=200) # Trend Filter
        df['ema800'] = ta.ema(df['close'], length=800) # THE SHIELD (Macro)

        # Volatilidade e Força
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
        df['adx'] = ta.adx(df['high'], df['low'], df['close'])['ADX_14']

        # Bollinger (Para Trap)
        bb = ta.bbands(df['close'], length=20, std=2)
        if bb is not None:
            df['bb_l'] = bb.iloc[:, 0]
            df['bb_u'] = bb.iloc[:, 2]

        return df.iloc[-1]
    except Exception as e:
        # print(f"Erro dados {symbol}: {e}")
        return None

def run_bot():
    hora_atual = obter_data_hora_br()
    print(f"\n🧬 ROBODERIK V164 (ASYMMETRIC COMPOUNDER) - {hora_atual}")
    
    estado = carregar_estado()
    print(f"💰 Banca: ${estado['banca_atual']:.2f} | PnL Hoje: ${estado['pnl_hoje']:.2f}")

    # Reinicia PnL diário
    hoje = obter_data_hoje_br()
    if estado["data_hoje"] != hoje:
        estado["data_hoje"] = hoje
        estado["pnl_hoje"] = 0.0

    # --- 1. GESTÃO DA POSIÇÃO ABERTA ---
    if estado["posicao_aberta"]:
        pos = estado["posicao_aberta"]
        symbol = pos["symbol"]
        dados = obter_dados_v164(symbol)
        
        if dados is not None:
            atual = float(dados['close'])
            ema20 = float(dados['ema20'])
            ema50 = float(dados['ema50'])
            atr = float(dados['atr'])
            adx = float(dados['adx'])
            
            lucro_usd = 0
            fechou = False
            motivo = ""
            
            # Cálculo de Lucro Atual (Não realizado)
            if pos['side'] == 'buy':
                lucro_unrealized_pct = (atual - pos['entry']) / pos['entry']
            else:
                lucro_unrealized_pct = (pos['entry'] - atual) / pos['entry']

            print(f"👀 {symbol} ({pos['strat']}) | PnL: {lucro_unrealized_pct*100:.2f}% | Adds: {pos['adds']}")

            # --- A. SAÍDAS ASSIMÉTRICAS ---
            if pos['strat'] == 'TREND':
                # Se estamos no SUMMER (Macro Bull), usamos EMA 50 (Exit Lento)
                if pos['side'] == 'buy' and pos['macro'] == "SUMMER":
                    if atual < ema50:
                        fechou = True; motivo = "TP Deep Trend (EMA50)"
                
                # Se for Winter ou Short, usa EMA 20 (Exit Rápido)
                else:
                    if pos['side'] == 'buy' and atual < ema20:
                        fechou = True; motivo = "TP Fast (EMA20)"
                    elif pos['side'] == 'sell' and atual > ema20:
                        fechou = True; motivo = "TP Fast (EMA20)"
            
            elif pos['strat'] == 'TRAP':
                # Trap sai na Média Rápida
                target = ema50
                if pos['side'] == 'buy' and dados['high'] >= target:
                    fechou = True; motivo = "TP Trap"
                elif pos['side'] == 'sell' and dados['low'] <= target:
                    fechou = True; motivo = "TP Trap"

            # --- B. STOP LOSS TÉCNICO ---
            if not fechou:
                if pos['side'] == 'buy' and atual <= pos['sl']:
                    fechou = True; motivo = "⛔ STOP LOSS"
                elif pos['side'] == 'sell' and atual >= pos['sl']:
                    fechou = True; motivo = "⛔ STOP LOSS"

            # --- C. PIRAMIDAGEM (GOLDEN ADD) ---
            # Só adiciona se: Trend + Summer + Lucro > 5% + Não adicionou ainda
            if not fechou and pos['strat'] == 'TREND' and pos['macro'] == "SUMMER" and pos['adds'] < MAX_ADDS:
                if pos['side'] == 'buy' and lucro_unrealized_pct > 0.05:
                    
                    add_usd = pos['initial_size_usd'] # Dobra a mão
                    if estado['banca_atual'] > add_usd:
                        # Preço Médio Novo
                        total_size = pos['size_usd'] + add_usd
                        new_entry = ((pos['size_usd'] * pos['entry']) + (add_usd * atual)) / total_size
                        
                        pos['size_usd'] = total_size
                        pos['entry'] = new_entry
                        pos['adds'] += 1
                        
                        # Stop Loss sobe, mas mantém técnico (ATR)
                        pos['sl'] = new_entry - (atr * 2.0)
                        
                        print(f"🔥 PIRAMIDAGEM EXECUTADA EM {symbol}! Novo PM: {new_entry:.2f}")
                        salvar_estado(estado)

            # --- D. FECHAMENTO ---
            if fechou:
                # Calcula Lucro Real em USD
                if pos['side'] == 'buy':
                    pnl_final = (atual - pos['entry']) / pos['entry'] * pos['size_usd']
                else:
                    pnl_final = (pos['entry'] - atual) / pos['entry'] * pos['size_usd']
                
                estado['banca_atual'] += pnl_final
                estado['pnl_hoje'] += pnl_final
                
                # Log
                trade_log = {
                    "data": obter_data_hora_br(),
                    "symbol": symbol,
                    "strat": pos['strat'],
                    "side": pos['side'],
                    "lucro": round(pnl_final, 2),
                    "motivo": motivo,
                    "adds": pos['adds']
                }
                estado['historico_trades'].append(trade_log)
                estado['posicao_aberta'] = None
                
                if estado['banca_atual'] > estado['pico_banca']:
                    estado['pico_banca'] = estado['banca_atual']
                
                print(f"✨ TRADE FECHADO: {motivo} | PnL: ${pnl_final:.2f}")
                salvar_estado(estado)
                return

    # --- 2. ESCANEAMENTO (SÓ SE NÃO TIVER POSIÇÃO) ---
    if estado["posicao_aberta"] is None:
        print(f"🔎 Escaneando V164...")
        for symbol, nome in SYMBOL_MAP.items():
            row = obter_dados_v164(symbol)
            if row is None: continue

            # Indicadores
            close = float(row['close'])
            ema20 = float(row['ema20'])
            ema200 = float(row['ema200'])
            ema800 = float(row['ema800'])
            adx = float(row['adx'])
            atr = float(row['atr'])
            
            # V164 INTELLIGENCE LAYER
            macro = "SUMMER" if close > ema800 else "WINTER"
            bias = "BULL" if close > ema200 else "BEAR"
            
            signal = None; side = ""; strat = ""; risk_profile = RISK_WINTER

            # ESTRATÉGIA 1: TREND (ADX > 20)
            if adx > 20:
                if macro == "SUMMER":
                    if close > ema20:
                        signal = True; side = "buy"; strat = "TREND"
                        risk_profile = RISK_SUMMER # 6% (Ataque)
                
                # Proteção V164: No Winter (Bear Market), PROIBIDO LONG DE TENDÊNCIA
                elif macro == "WINTER":
                    if close < ema20:
                        signal = True; side = "sell"; strat = "TREND"
                        risk_profile = RISK_WINTER # 2% (Defesa)

            # ESTRATÉGIA 2: TRAP (ADX < 30)
            if not signal and adx < 30:
                if bias == "BULL" and float(row['low']) <= float(row['bb_l']):
                    # Wicks longos
                    body = abs(float(row['open']) - close)
                    wick = min(float(row['open']), close) - float(row['low'])
                    if wick > body: # Martelo/Rejeição
                        signal = True; side = "buy"; strat = "TRAP"
                        risk_profile = RISK_WINTER

                elif bias == "BEAR" and macro == "WINTER": # Trap de topo só no inverno
                    if float(row['high']) >= float(row['bb_u']):
                        signal = True; side = "sell"; strat = "TRAP"
                        risk_profile = RISK_WINTER

            if signal:
                print(f"🚀 SINAL V164: {side.upper()} {symbol} ({strat} - {macro})")
                
                # Position Sizing
                risk_usd = estado['banca_atual'] * risk_profile
                sl_dist = atr * 2.0
                
                if side == "buy":
                    sl_price = close - sl_dist
                else:
                    sl_price = close + sl_dist
                
                # Evita divisão por zero
                dist_abs = abs(close - sl_price)
                if dist_abs == 0: continue

                # Tamanho da posição baseado no risco do Stop Loss
                pos_size_usd = risk_usd / (dist_abs / close)
                
                # Trava de segurança (Max 30% da banca no Summer, 15% no Winter)
                max_alloc = 0.30 if (macro == "SUMMER" and strat == "TREND") else 0.15
                if pos_size_usd > estado['banca_atual'] * max_alloc:
                    pos_size_usd = estado['banca_atual'] * max_alloc

                estado['posicao_aberta'] = {
                    "symbol": symbol,
                    "strat": strat,
                    "side": side,
                    "macro": macro,
                    "entry": close,
                    "sl": sl_price,
                    "size_usd": pos_size_usd,
                    "initial_size_usd": pos_size_usd, # Para calcular a dobra
                    "adds": 0,
                    "data": obter_data_hora_br()
                }
                
                print(f"   💵 Entrada: ${pos_size_usd:.2f} | Stop: {sl_price:.4f}")
                salvar_estado(estado)
                break
            else:
                print(f"   ⚪ {symbol:<9} | {macro:<6} | {bias:<4} | ADX {adx:.1f}")

    salvar_estado(estado)

if __name__ == "__main__":
    try:
        run_bot()
    except Exception as e:
        traceback.print_exc()
        

import sys
import subprocess
import os
import json
import time
from datetime import datetime
import traceback

# --- AUTO-INSTALAÇÃO DE DEPENDÊNCIAS ---
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

# Configuração de Tempo
TIMEFRAME = "15m" 
ALAVANCAGEM = 1 

# GESTÃO DE RISCO V164
RISK_SUMMER = 0.10    # 10% da banca em Tendência de Alta Limpa
RISK_WINTER = 0.015   # 1,5% da banca em Mercado de Baixa
MAX_ADDS = 1          # Máximo de 1 piramidagem 

# ZONA DE RUÍDO (BUFFER) PARA EVITAR VIOLINADAS DE MESMA VELA
BUFFER_PCT = 0.002    # 0.2% de margem acima/abaixo da média

# ARQUIVO DE ESTADO
STATE_FILE = "estado_v164.json"

def inicializar_arquivo():
    if not os.path.exists(STATE_FILE):
        dados_iniciais = {
            "banca_atual": 60.0,      
            "pico_banca": 60.0,
            "posicao_aberta": None,
            "historico_trades": [],
            "data_hoje": obter_data_hoje_br(),
            "pnl_hoje": 0.0
        }
        try:
            with open(STATE_FILE, "w") as f:
                json.dump(dados_iniciais, f, indent=4)
            print(f"✅ Arquivo '{STATE_FILE}' criado com sucesso! Banca: $60.00")
        except Exception as e:
            print(f"❌ Erro crítico ao criar arquivo: {e}")

def carregar_estado():
    if not os.path.exists(STATE_FILE):
        inicializar_arquivo()
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ Erro ao ler estado: {e}")
        return None

def salvar_estado(estado):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(estado, f, indent=4)
    except Exception as e:
        print(f"❌ Erro ao salvar: {e}")

def obter_dados_v164(symbol):
    try:
        df = yf.download(symbol, period="60d", interval=TIMEFRAME, progress=False)
        if df.empty or len(df) < 805: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
        df.columns = [c.lower() for c in df.columns]

        df['ema20'] = ta.ema(df['close'], length=20)
        df['ema50'] = ta.ema(df['close'], length=50)   
        df['ema200'] = ta.ema(df['close'], length=200) 
        df['ema800'] = ta.ema(df['close'], length=800) 

        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
        df['adx'] = ta.adx(df['high'], df['low'], df['close'])['ADX_14']

        bb = ta.bbands(df['close'], length=20, std=2)
        if bb is not None:
            df['bb_l'] = bb.iloc[:, 0]
            df['bb_u'] = bb.iloc[:, 2]

        return df.iloc[-1]
    except Exception as e:
        return None

def run_bot():
    inicializar_arquivo()
    hora_atual = obter_data_hora_br()
    print(f"\n💎 ROBODERIK V164 (ASYMMETRIC COMPOUNDER) - {hora_atual}")
    
    estado = carregar_estado()
    if not estado: return

    print(f"💰 Banca: ${estado['banca_atual']:.2f} | PnL Hoje: ${estado['pnl_hoje']:.2f}")

    hoje = obter_data_hoje_br()
    if estado["data_hoje"] != hoje:
        estado["data_hoje"] = hoje
        estado["pnl_hoje"] = 0.0
        salvar_estado(estado)

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
            
            fechou = False
            motivo = ""
            
            if pos['side'] == 'buy':
                lucro_unrealized_pct = (atual - pos['entry']) / pos['entry']
            else:
                lucro_unrealized_pct = (pos['entry'] - atual) / pos['entry']

            print(f"👀 Monitorando {symbol} ({pos['strat']}) | PnL Unrealized: {lucro_unrealized_pct*100:.2f}%")

            # --- A. SAÍDAS ASSIMÉTRICAS COM BUFFER DE RUÍDO ---
            if pos['strat'] == 'TREND':
                if pos['side'] == 'buy' and pos['macro'] == "SUMMER":
                    # Exige que perca a EMA 50 por uma margem clara (0.2%) para sair
                    if atual < (ema50 * (1 - BUFFER_PCT)):
                        fechou = True; motivo = "✅ TP Deep Trend (Rompeu EMA50)"
                else:
                    if pos['side'] == 'buy' and atual < (ema20 * (1 - BUFFER_PCT)):
                        fechou = True; motivo = "⚠️ Saída Dinâmica (Perdeu EMA20)"
                    elif pos['side'] == 'sell' and atual > (ema20 * (1 + BUFFER_PCT)):
                        fechou = True; motivo = "⚠️ Saída Dinâmica (Rompeu EMA20)"
            
            elif pos['strat'] == 'TRAP':
                target = ema50
                if pos['side'] == 'buy' and float(dados['high']) >= target:
                    fechou = True; motivo = "✅ TP Trap (Alvo Atingido)"
                elif pos['side'] == 'sell' and float(dados['low']) <= target:
                    fechou = True; motivo = "✅ TP Trap (Alvo Atingido)"

            # --- B. STOP LOSS TÉCNICO MAXIMO ---
            if not fechou:
                if pos['side'] == 'buy' and atual <= pos['sl']:
                    fechou = True; motivo = "⛔ STOP LOSS"
                elif pos['side'] == 'sell' and atual >= pos['sl']:
                    fechou = True; motivo = "⛔ STOP LOSS"

            # --- C. PIRAMIDAGEM ---
            if not fechou and pos['strat'] == 'TREND' and pos['macro'] == "SUMMER" and pos['adds'] < MAX_ADDS:
                if pos['side'] == 'buy' and lucro_unrealized_pct > 0.05:
                    add_usd = pos['initial_size_usd'] 
                    if estado['banca_atual'] > add_usd:
                        total_size = pos['size_usd'] + add_usd
                        new_entry = ((pos['size_usd'] * pos['entry']) + (add_usd * atual)) / total_size
                        
                        pos['size_usd'] = total_size
                        pos['entry'] = new_entry
                        pos['adds'] += 1
                        pos['sl'] = new_entry - (atr * 2.0)
                        salvar_estado(estado)

            # --- D. FECHAMENTO COM TAXAS REAIS ---
            if fechou:
                # Calcula Lucro Bruto
                if pos['side'] == 'buy': pnl_bruto = (atual - pos['entry']) / pos['entry'] * pos['size_usd']
                else: pnl_bruto = (pos['entry'] - atual) / pos['entry'] * pos['size_usd']
                
                # Desconta Taxa Binance Spot (0.1% Entrada + 0.1% Saída) = 0.2%
                taxa_corretora_usd = pos['size_usd'] * 0.002
                pnl_final = pnl_bruto - taxa_corretora_usd

                estado['banca_atual'] += pnl_final
                estado['pnl_hoje'] += pnl_final
                
                log_trade = {
                    "data": obter_data_hora_br(),
                    "symbol": symbol,
                    "strat": pos['strat'],
                    "side": pos['side'],
                    "criterio": pos.get('criterio', 'N/A'),
                    "entrada": pos['entry'],
                    "saida": atual,
                    "tp": pos.get('tp', 0.0),
                    "sl": pos['sl'],
                    "lucro": round(pnl_final, 2), 
                    "motivo": motivo,
                    "adds": pos['adds']
                }
                estado['historico_trades'].append(log_trade)
                if len(estado['historico_trades']) > 50: estado['historico_trades'].pop(0)

                estado['posicao_aberta'] = None
                if estado['banca_atual'] > estado['pico_banca']: estado['pico_banca'] = estado['banca_atual']
                
                print(f"✨ TRADE FECHADO: {motivo} | PnL Bruto: ${pnl_bruto:.2f} | PnL c/ Taxa: ${pnl_final:.2f}")
                salvar_estado(estado)
                return

    # --- 2. ESCANEAMENTO ---
    if estado["posicao_aberta"] is None:
        print(f"🔎 Escaneando oportunidades V164...")
        
        for symbol, nome in SYMBOL_MAP.items():
            row = obter_dados_v164(symbol)
            if row is None: continue

            close = float(row['close'])
            ema20 = float(row['ema20'])
            ema50 = float(row['ema50'])
            ema200 = float(row['ema200'])
            ema800 = float(row['ema800'])
            adx = float(row['adx'])
            atr = float(row['atr'])
            
            macro = "SUMMER" if close > ema800 else "WINTER"
            bias = "BULL" if close > ema200 else "BEAR"
            
            signal = None; side = ""; strat = ""; risk_profile = RISK_WINTER
            criterio_desc = ""
            tp_alvo_inicial = 0.0 

            if adx > 20:
                if macro == "SUMMER":
                    # BUFFER: Exige que o preço esteja 0.2% ACIMA da Média para confirmar a força
                    if close > (ema20 * (1 + BUFFER_PCT)):
                        signal = True; side = "buy"; strat = "TREND"
                        risk_profile = RISK_SUMMER
                        criterio_desc = f"SUMMER TREND | ADX {adx:.1f} > 20"
                        tp_alvo_inicial = ema50 
                
                elif macro == "WINTER":
                    # BUFFER: Exige que o preço esteja 0.2% ABAIXO da Média para confirmar fraqueza
                    if close < (ema20 * (1 - BUFFER_PCT)):
                        signal = True; side = "sell"; strat = "TREND"
                        risk_profile = RISK_WINTER
                        criterio_desc = f"WINTER TREND SHORT | ADX {adx:.1f} > 20"
                        tp_alvo_inicial = ema20

            if not signal and adx < 30:
                if bias == "BULL" and float(row['low']) <= float(row['bb_l']):
                    body = abs(float(row['open']) - close)
                    wick = min(float(row['open']), close) - float(row['low'])
                    if wick > body: 
                        signal = True; side = "buy"; strat = "TRAP"
                        risk_profile = RISK_WINTER
                        criterio_desc = f"TRAP FUNDO | Rejeição BB Inferior"
                        tp_alvo_inicial = ema50

                elif bias == "BEAR" and macro == "WINTER": 
                    if float(row['high']) >= float(row['bb_u']):
                        signal = True; side = "sell"; strat = "TRAP"
                        risk_profile = RISK_WINTER
                        criterio_desc = f"TRAP TOPO | Toque BB Superior"
                        tp_alvo_inicial = ema50

            if signal:
                print(f"🚀 SINAL ENCONTRADO: {side.upper()} {symbol} ({strat} - {macro})")
                
                risk_usd = estado['banca_atual'] * risk_profile
                sl_dist = atr * 2.0
                
                if side == "buy": sl_price = close - sl_dist
                else: sl_price = close + sl_dist
                
                dist_pct = sl_dist / close
                if dist_pct == 0: continue

                pos_size_usd = risk_usd / dist_pct
                
                max_alloc = 0.30 if (macro == "SUMMER" and strat == "TREND") else 0.15
                if pos_size_usd > estado['banca_atual'] * max_alloc:
                    pos_size_usd = estado['banca_atual'] * max_alloc

                estado['posicao_aberta'] = {
                    "symbol": symbol,
                    "strat": strat,
                    "side": side,
                    "macro": macro,
                    "criterio": criterio_desc,
                    "entry": close,
                    "tp": tp_alvo_inicial,
                    "sl": sl_price,
                    "size_usd": pos_size_usd,
                    "initial_size_usd": pos_size_usd,
                    "adds": 0,
                    "data": obter_data_hora_br()
                }
                
                print(f"   💵 Entrada: ${pos_size_usd:.2f} | Stop: {sl_price:.4f} | TP Ref: {tp_alvo_inicial:.4f}")
                salvar_estado(estado)
                break 
            else:
                print(f"   ⚪ {symbol:<9} | {macro:<6} | {bias:<4} | ADX {adx:.1f}")

    salvar_estado(estado)

if __name__ == "__main__":
    try:
        run_bot()
    except Exception as e:
        print(f"Erro fatal: {e}")
        traceback.print_exc()

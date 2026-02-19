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
RISK_SUMMER = 0.10    # 10% da banca em Tendência de Alta
RISK_WINTER = 0.015   # 1,5% da banca em Mercado de Baixa
MAX_ADDS = 1          # Máximo de 1 piramidagem 

# ZONA DE RUÍDO (BUFFER)
BUFFER_PCT = 0.002    # 0.2% de margem 

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
            print(f"✅ Arquivo '{STATE_FILE}' criado com sucesso!")
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

# --- MOTOR DE DADOS (SEPARANDO VELA FECHADA DE PREÇO ATUAL) ---

def obter_dados_v164(symbol):
    try:
        df = yf.download(symbol, period="60d", interval=TIMEFRAME, progress=False)
        if df.empty or len(df) < 805: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
        df.columns = [c.lower() for c in df.columns]

        # Calcula indicadores na série toda
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

        # O SEGREDO DO 1 MINUTO:
        # Pega o preço atual em TEMPO REAL (vela aberta - índice -1)
        current_price = float(df['close'].iloc[-1])
        
        # Pega os INDICADORES da última vela FECHADA (índice -2) para evitar repintura
        row_closed = df.iloc[-2]

        return {
            "current_price": current_price,
            "ema20": float(row_closed['ema20']),
            "ema50": float(row_closed['ema50']),
            "ema200": float(row_closed['ema200']),
            "ema800": float(row_closed['ema800']),
            "atr": float(row_closed['atr']),
            "adx": float(row_closed['adx']),
            "bb_l": float(row_closed['bb_l']),
            "bb_u": float(row_closed['bb_u']),
            "closed_open": float(row_closed['open']),
            "closed_close": float(row_closed['close']),
            "closed_high": float(row_closed['high']),
            "closed_low": float(row_closed['low'])
        }

    except Exception as e:
        print(f"❌ Erro ao baixar {symbol}: {e}")
        return None

# --- LÓGICA PRINCIPAL ---

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
        print(f"👀 Monitorando {symbol} ({pos['strat']} - {pos['macro']})...")
        
        dados = obter_dados_v164(symbol)
        
        if dados is not None:
            atual = dados['current_price'] # Preço batendo agora
            ema20 = dados['ema20']         # Média travada da vela fechada
            ema50 = dados['ema50']
            atr = dados['atr']
            
            fechou = False
            motivo = ""
            
            if pos['side'] == 'buy':
                lucro_unrealized_pct = (atual - pos['entry']) / pos['entry']
            else:
                lucro_unrealized_pct = (pos['entry'] - atual) / pos['entry']

            print(f"   📊 PnL Unrealized: {lucro_unrealized_pct*100:.2f}% | Adds: {pos['adds']}")

            # Mínimo de lucro para TP (cobre 0.2% de taxa Binance Spot)
            MIN_PROFIT_PCT = 0.003 

            # --- A. SAÍDAS ASSIMÉTRICAS ---
            if pos['strat'] == 'TREND':
                if pos['side'] == 'buy' and pos['macro'] == "SUMMER":
                    if atual < (ema50 * (1 - BUFFER_PCT)) and lucro_unrealized_pct > MIN_PROFIT_PCT:
                        fechou = True; motivo = "✅ TP Deep Trend (EMA50)"
                else:
                    if pos['side'] == 'buy' and atual < (ema20 * (1 - BUFFER_PCT)) and lucro_unrealized_pct > MIN_PROFIT_PCT:
                        fechou = True; motivo = "✅ TP Fast (EMA20)"
                    elif pos['side'] == 'sell' and atual > (ema20 * (1 + BUFFER_PCT)) and lucro_unrealized_pct > MIN_PROFIT_PCT:
                        fechou = True; motivo = "✅ TP Fast (EMA20)"
            
            elif pos['strat'] == 'TRAP':
                target = ema50
                if pos['side'] == 'buy' and atual >= target and lucro_unrealized_pct > MIN_PROFIT_PCT:
                    fechou = True; motivo = "✅ TP Trap"
                elif pos['side'] == 'sell' and atual <= target and lucro_unrealized_pct > MIN_PROFIT_PCT:
                    fechou = True; motivo = "✅ TP Trap"

            # --- B. STOP LOSS TÉCNICO ---
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
                        
                        print(f"🔥 PIRAMIDAGEM! Novo PM: {new_entry:.2f}")
                        salvar_estado(estado)

            # --- D. FECHAMENTO ---
            if fechou:
                if pos['side'] == 'buy':
                    pnl_bruto = (atual - pos['entry']) / pos['entry'] * pos['size_usd']
                else:
                    pnl_bruto = (pos['entry'] - atual) / pos['entry'] * pos['size_usd']
                
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
                
                print(f"✨ TRADE FECHADO: {motivo} | PnL Bruto: ${pnl_bruto:.2f} | Líquido: ${pnl_final:.2f}")
                salvar_estado(estado)
                return

    # --- 2. ESCANEAMENTO ---
    if estado["posicao_aberta"] is None:
        print(f"🔎 Escaneando mercado (Vela Fechada)...")
        
        for symbol, nome in SYMBOL_MAP.items():
            dados = obter_dados_v164(symbol)
            if dados is None: continue

            current_price = dados['current_price']
            ema20 = dados['ema20']
            ema50 = dados['ema50']
            ema200 = dados['ema200']
            ema800 = dados['ema800']
            adx = dados['adx']
            atr = dados['atr']
            
            macro = "SUMMER" if current_price > ema800 else "WINTER"
            bias = "BULL" if current_price > ema200 else "BEAR"
            
            signal = None; side = ""; strat = ""; risk_profile = RISK_WINTER
            criterio_desc = ""
            tp_alvo_inicial = 0.0 

            # ESTRATÉGIA 1: TREND (Confirma com preço atual quebrando a média da vela anterior)
            if adx > 20:
                if macro == "SUMMER":
                    if current_price > (ema20 * (1 + BUFFER_PCT)):
                        signal = True; side = "buy"; strat = "TREND"
                        risk_profile = RISK_SUMMER
                        criterio_desc = f"SUMMER TREND | ADX {adx:.1f} > 20"
                        tp_alvo_inicial = ema50 
                
                elif macro == "WINTER":
                    if current_price < (ema20 * (1 - BUFFER_PCT)):
                        signal = True; side = "sell"; strat = "TREND"
                        risk_profile = RISK_WINTER
                        criterio_desc = f"WINTER TREND SHORT | ADX {adx:.1f} > 20"
                        tp_alvo_inicial = ema20 

            # ESTRATÉGIA 2: TRAP (Formato da vela anterior FECHADA)
            if not signal and adx < 30:
                dist_alvo_pct = abs(ema50 - current_price) / current_price
                
                if dist_alvo_pct >= 0.004: # Tem espaço pra lucrar?
                    if bias == "BULL" and dados['closed_low'] <= dados['bb_l']:
                        # Martelo na vela fechada
                        body = abs(dados['closed_open'] - dados['closed_close'])
                        wick = min(dados['closed_open'], dados['closed_close']) - dados['closed_low']
                        if wick > body: 
                            signal = True; side = "buy"; strat = "TRAP"
                            risk_profile = RISK_WINTER
                            criterio_desc = f"TRAP FUNDO | Rejeição BB Inferior"
                            tp_alvo_inicial = ema50

                    elif bias == "BEAR" and macro == "WINTER": 
                        # Estrela Cadente na vela fechada
                        if dados['closed_high'] >= dados['bb_u']:
                            body = abs(dados['closed_open'] - dados['closed_close'])
                            wick = dados['closed_high'] - max(dados['closed_open'], dados['closed_close'])
                            if wick > body:
                                signal = True; side = "sell"; strat = "TRAP"
                                risk_profile = RISK_WINTER
                                criterio_desc = f"TRAP TOPO | Rejeição BB Superior"
                                tp_alvo_inicial = ema50

            if signal:
                print(f"🚀 SINAL ENCONTRADO: {side.upper()} {symbol} ({strat} - {macro})")
                
                risk_usd = estado['banca_atual'] * risk_profile
                sl_dist = atr * 2.0
                
                if side == "buy": sl_price = current_price - sl_dist
                else: sl_price = current_price + sl_dist
                
                dist_pct = sl_dist / current_price
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
                    "entry": current_price,
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

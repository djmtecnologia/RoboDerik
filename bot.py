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
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

for lib in ["ccxt", "pandas", "pandas_ta", "numpy", "pytz"]:
    install(lib)

import ccxt
import pandas as pd
import pandas_ta as ta
import pytz

# --- CONFIGURAÇÕES V56 (ADAPTIVE SCALPER) ---
SYMBOL_LIST = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT"]
TIMEFRAME = "15m"
ALAVANCAGEM = 3
PERCENTUAL_MAO_BASE = 0.10
MARTINGALE_LEVELS = [1.0, 2.5, 5.5, 10.5]

# ALVOS PADRÃO (Sniper)
TP_NORMAL = 0.020  # 2.0%
SL_NORMAL = 0.015  # 1.5%

# ALVOS LATERAL (Scalper - Mercado Chato)
TP_SCALP = 0.008   # 0.8% (Lucro rápido)
SL_SCALP = 0.010   # 1.0%

# SEGURANÇA
STOP_LOSS_DIARIO_PERC = 0.20 
STOP_DRAWDOWN_GLOBAL = 0.25 
MAX_TRADES_DIA = 10 # Aumentei pois no lateral ele opera mais

STATE_FILE = "estado.json"

def carregar_estado():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except: pass
            
    return {
        "banca_inicial": 60.0,
        "pico_banca": 60.0,
        "martingale_idx": 0,
        "trades_hoje": 0,
        "data_hoje": datetime.now().strftime("%Y-%m-%d"),
        "pnl_hoje": 0.0,
        "em_quarentena": False,
        "ultima_banca": 60.0
    }

def salvar_estado(estado):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(estado, f, indent=4)
        print("💾 Estado salvo.")
    except Exception as e:
        print(f"❌ Erro ao salvar: {e}")

def conectar_binance():
    api_key = os.environ.get("BINANCE_API_KEY")
    secret_key = os.environ.get("BINANCE_SECRET_KEY")
    if not api_key: return None
    return ccxt.binance({'apiKey': api_key, 'secret': secret_key, 'options': {'defaultType': 'future'}})

def obter_dados(exchange, symbol):
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=100)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        df['adx'] = ta.adx(df['high'], df['low'], df['close'])['ADX_14']
        df['rsi'] = ta.rsi(df['close'], length=14)
        bb = ta.bbands(df['close'], length=20, std=2)
        df['lower'] = bb['BBL_20_2.0']
        df['upper'] = bb['BBU_20_2.0']
        
        return df.iloc[-1]
    except: return None

def run_bot():
    print("🚀 INICIANDO ROBODERIK V56 (ADAPTIVE SCALPER)...")
    estado = carregar_estado()
    
    try:
        exchange = conectar_binance()
        if not exchange: return 

        try:
            balance = exchange.fetch_balance()
            banca_atual = float(balance['total']['USDT'])
            print(f"💰 Banca Atual: ${banca_atual:.2f}")
        except: return 

        # Atualiza PnL
        pnl_ciclo = banca_atual - estado["ultima_banca"]
        hoje = datetime.now().strftime("%Y-%m-%d")
        
        if estado["data_hoje"] != hoje:
            estado["data_hoje"] = hoje
            estado["trades_hoje"] = 0
            estado["pnl_hoje"] = 0.0
            print("📅 Novo dia iniciado.")

        if abs(pnl_ciclo) > 0.5:
            estado["pnl_hoje"] += pnl_ciclo
            if pnl_ciclo > 0:
                print("✅ WIN! Resetando Martingale.")
                estado["martingale_idx"] = 0
                if estado["em_quarentena"]: estado["em_quarentena"] = False
            else:
                print("🔻 LOSS! Subindo Nível.")
                estado["martingale_idx"] = min(estado["martingale_idx"] + 1, 3)

        if banca_atual > estado["pico_banca"]: estado["pico_banca"] = banca_atual
        estado["ultima_banca"] = banca_atual

        # Travas
        drawdown = (estado["pico_banca"] - banca_atual) / estado["pico_banca"]
        if drawdown >= STOP_DRAWDOWN_GLOBAL:
            estado["em_quarentena"] = True
            print(f"🛑 Quarentena Ativada (DD {drawdown*100:.1f}%)")
            return

        if estado["em_quarentena"] or estado["pnl_hoje"] <= -(banca_atual * STOP_LOSS_DIARIO_PERC):
            print("💤 Robô Parado (Quarentena ou Stop Diário).")
            return

        if estado["trades_hoje"] >= MAX_TRADES_DIA:
            print("⏸️ Limite de trades atingido.")
            return

        # --- ESTRATÉGIA HÍBRIDA (SNIPER vs SCALPER) ---
        print("🔎 Escaneando mercado (Modo Adaptativo)...")
        
        for symbol in SYMBOL_LIST:
            current = obter_dados(exchange, symbol)
            if current is None: continue

            adx = current['adx']
            rsi = current['rsi']
            close = current['close']
            lower = current['lower']
            upper = current['upper']
            
            signal = None
            modo = "NORMAL"
            target_tp = TP_NORMAL
            target_sl = SL_NORMAL

            # 1. MODO LATERAL (SCALPER) - ADX < 20
            # Mercado muito chato. Entramos mais fácil para pegar movimentos curtos.
            if adx < 20:
                modo = "SCALPER (LATERAL)"
                # Afrouxa o RSI (entra mais fácil)
                if rsi < 35 and close < lower: signal = 'buy'
                elif rsi > 65 and close > upper: signal = 'sell'
                # Alvos Curtos
                target_tp = TP_SCALP
                target_sl = SL_SCALP

            # 2. MODO SNIPER (NORMAL) - ADX entre 20 e 30
            # Mercado padrão. Exige condições perfeitas.
            elif adx < 30:
                modo = "SNIPER (PADRÃO)"
                if rsi < 28 and close < lower: signal = 'buy'
                elif rsi > 72 and close > upper: signal = 'sell'
            
            # 3. TENDÊNCIA FORTE - ADX > 30 (PERIGO)
            else:
                modo = "TENDÊNCIA (PERIGO)"
                # Não opera contra tendência forte no V56

            if signal:
                print(f"🚀 SINAL {signal.upper()} em {symbol}!")
                print(f"   📊 Modo: {modo} | RSI: {rsi:.1f} | ADX: {adx:.1f}")
                
                multiplicador = MARTINGALE_LEVELS[estado["martingale_idx"]]
                tamanho_usd = (banca_atual * PERCENTUAL_MAO_BASE) * multiplicador
                if tamanho_usd > banca_atual * 0.95: tamanho_usd = banca_atual * 0.95
                if tamanho_usd < 6: tamanho_usd = 6

                amount = (tamanho_usd * ALAVANCAGEM) / close
                
                try:
                    exchange.set_leverage(ALAVANCAGEM, symbol)
                    order = exchange.create_market_order(symbol, signal, amount)
                    
                    entry = float(order['average']) if order['average'] else close
                    
                    # Define TP/SL baseado no modo (Scalp ou Normal)
                    if signal == 'buy':
                        tp = entry * (1 + target_tp)
                        sl = entry * (1 - target_sl)
                    else:
                        tp = entry * (1 - target_tp)
                        sl = entry * (1 + target_sl)
                    
                    exchange.create_order(symbol, 'STOP_MARKET', amount, params={'stopPrice': sl, 'reduceOnly': True})
                    exchange.create_order(symbol, 'TAKE_PROFIT_MARKET', amount, params={'stopPrice': tp, 'reduceOnly': True})
                    
                    print(f"✅ Ordem {modo} enviada! Alvo: {target_tp*100:.1f}%")
                    estado["trades_hoje"] += 1
                    break 
                except Exception as e:
                    print(f"❌ Erro na ordem: {e}")
            else:
                print(f"   ⚪ {symbol}: {modo} | RSI {rsi:.1f} | ADX {adx:.1f} -> Sem entrada")

    except Exception as e:
        print(f"❌ Erro Geral: {e}")
        traceback.print_exc()
    finally:
        salvar_estado(estado)

if __name__ == "__main__":
    run_bot()
                

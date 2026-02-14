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
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

for lib in ["ccxt", "pandas", "pandas_ta", "numpy", "pytz"]:
    install(lib)

import ccxt
import pandas as pd
import pandas_ta as ta
import pytz

# --- CONFIGURAÇÕES V55 (REAL TRADING) ---
SYMBOL_LIST = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT"]
TIMEFRAME = "15m"
ALAVANCAGEM = 3
PERCENTUAL_MAO_BASE = 0.10  # 10% da banca
MARTINGALE_LEVELS = [1.0, 2.5, 5.5, 10.5]

TARGET_TP = 0.020 
TARGET_SL = 0.015 

STOP_LOSS_DIARIO_PERC = 0.20 
STOP_DRAWDOWN_GLOBAL = 0.25 
MAX_TRADES_DIA = 5

STATE_FILE = "estado.json"

def carregar_estado():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except:
            pass # Se arquivo estiver corrompido, recria
            
    # Estado padrão (Primeira execução)
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
        print("💾 Estado salvo com sucesso.")
    except Exception as e:
        print(f"❌ Erro ao salvar estado: {e}")

def conectar_binance():
    api_key = os.environ.get("BINANCE_API_KEY")
    secret_key = os.environ.get("BINANCE_SECRET_KEY")
    
    if not api_key or not secret_key:
        print("❌ ERRO CRÍTICO: API Keys não configuradas nos Secrets.")
        # Não damos exit aqui para permitir que o 'finally' salve o estado vazio se necessário
        return None

    try:
        exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': secret_key,
            'options': {'defaultType': 'future'}
        })
        return exchange
    except Exception as e:
        print(f"❌ Erro ao instanciar exchange: {e}")
        return None

def obter_dados(exchange, symbol):
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=100)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Indicadores
        df['adx'] = ta.adx(df['high'], df['low'], df['close'])['ADX_14']
        df['rsi'] = ta.rsi(df['close'], length=14)
        bb = ta.bbands(df['close'], length=20, std=2)
        df['lower'] = bb['BBL_20_2.0']
        df['upper'] = bb['BBU_20_2.0']
        
        return df.iloc[-1]
    except:
        return None

def run_bot():
    print("🚀 INICIANDO ROBODERIK V55 (REAL)...")
    
    estado = carregar_estado()
    
    # BLOCO TRY/FINALLY: Garante que o estado seja salvo mesmo se der erro no meio
    try:
        exchange = conectar_binance()
        if not exchange:
            return # Sai, mas vai pro finally salvar o estado inicial

        # Verificar Banca
        try:
            balance = exchange.fetch_balance()
            banca_atual = float(balance['total']['USDT'])
            print(f"💰 Banca Atual: ${banca_atual:.2f}")
        except Exception as e:
            print(f"❌ Erro ao ler saldo (Check API Permissions): {e}")
            return # Sai, mas salva

        # Atualizar PnL e Martingale
        pnl_ciclo = banca_atual - estado["ultima_banca"]
        hoje = datetime.now().strftime("%Y-%m-%d")
        
        if estado["data_hoje"] != hoje:
            estado["data_hoje"] = hoje
            estado["trades_hoje"] = 0
            estado["pnl_hoje"] = 0.0
            print("📅 Novo dia iniciado.")

        if abs(pnl_ciclo) > 0.5:
            estado["pnl_hoje"] += pnl_ciclo
            print(f"🔔 Variação detectada: ${pnl_ciclo:.2f}")
            if pnl_ciclo > 0:
                estado["martingale_idx"] = 0
                if estado["em_quarentena"]: estado["em_quarentena"] = False
            else:
                estado["martingale_idx"] = min(estado["martingale_idx"] + 1, 3)

        if banca_atual > estado["pico_banca"]: estado["pico_banca"] = banca_atual
        estado["ultima_banca"] = banca_atual

        # Verificações de Segurança
        drawdown = (estado["pico_banca"] - banca_atual) / estado["pico_banca"]
        if drawdown >= STOP_DRAWDOWN_GLOBAL:
            estado["em_quarentena"] = True
            print(f"🛑 ALERTA: Drawdown {drawdown*100:.2f}%. Entrando em Quarentena.")
            return

        if estado["em_quarentena"]:
            print("💤 Robô em Quarentena.")
            return

        limite_perda = -(banca_atual * STOP_LOSS_DIARIO_PERC)
        if estado["pnl_hoje"] <= limite_perda:
            print("🛑 Stop Loss Diário atingido.")
            return

        if estado["trades_hoje"] >= MAX_TRADES_DIA:
            print("⏸️ Limite de trades diários atingido.")
            return

        # Escaneamento
        print("🔎 Escaneando mercado...")
        for symbol in SYMBOL_LIST:
            current = obter_dados(exchange, symbol)
            if current is None: continue

            signal = None
            if current['adx'] < 30:
                if current['rsi'] < 28 and current['close'] < current['lower']:
                    signal = 'buy'
                elif current['rsi'] > 72 and current['close'] > current['upper']:
                    signal = 'sell'

            if signal:
                print(f"✅ SINAL {signal.upper()} em {symbol}")
                multiplicador = MARTINGALE_LEVELS[estado["martingale_idx"]]
                tamanho_usd = (banca_atual * PERCENTUAL_MAO_BASE) * multiplicador
                
                if tamanho_usd > banca_atual * 0.95: tamanho_usd = banca_atual * 0.95
                if tamanho_usd < 6: tamanho_usd = 6 # Garante minimo da Binance

                price = current['close']
                amount = (tamanho_usd * ALAVANCAGEM) / price
                
                try:
                    exchange.set_leverage(ALAVANCAGEM, symbol)
                    order = exchange.create_market_order(symbol, signal, amount)
                    
                    entry_price = float(order['average']) if order['average'] else price
                    if signal == 'buy':
                        tp = entry_price * (1 + TARGET_TP)
                        sl = entry_price * (1 - TARGET_SL)
                        side_exit = 'sell'
                    else:
                        tp = entry_price * (1 - TARGET_TP)
                        sl = entry_price * (1 + TARGET_SL)
                        side_exit = 'buy'
                    
                    exchange.create_order(symbol, 'STOP_MARKET', amount, params={'stopPrice': sl, 'reduceOnly': True})
                    exchange.create_order(symbol, 'TAKE_PROFIT_MARKET', amount, params={'stopPrice': tp, 'reduceOnly': True})
                    
                    print(f"🚀 Ordem Executada! {symbol}")
                    estado["trades_hoje"] += 1
                    break 
                except Exception as e:
                    print(f"❌ Erro na ordem: {e}")

    except Exception as e:
        print(f"❌ Erro Geral: {e}")
        traceback.print_exc()
    
    finally:
        # ISSO GARANTE QUE O ARQUIVO SEJA CRIADO SEMPRE
        salvar_estado(estado)

if __name__ == "__main__":
    run_bot()

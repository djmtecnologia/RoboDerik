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

# ALVOS (Baseados no Backtest)
TARGET_TP = 0.020  # 2.0% de Alvo
TARGET_SL = 0.015  # 1.5% de Stop

# SEGURANÇA
STOP_LOSS_DIARIO_PERC = 0.20 # Para se perder 20% no dia
STOP_DRAWDOWN_GLOBAL = 0.25  # Quarentena se cair 25% do topo
MAX_TRADES_DIA = 5

# --- ARQUIVO DE ESTADO (PERSISTÊNCIA) ---
STATE_FILE = "estado.json"

def carregar_estado():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {
        "banca_inicial": 60.0, # Começando com $60 conforme solicitado
        "pico_banca": 60.0,
        "martingale_idx": 0,
        "trades_hoje": 0,
        "data_hoje": datetime.now().strftime("%Y-%m-%d"),
        "pnl_hoje": 0.0,
        "em_quarentena": False,
        "ultima_banca": 60.0 # Para calcular o PnL entre execuções
    }

def salvar_estado(estado):
    with open(STATE_FILE, "w") as f:
        json.dump(estado, f, indent=4)

def conectar_binance():
    api_key = os.environ.get("BINANCE_API_KEY")
    secret_key = os.environ.get("BINANCE_SECRET_KEY")
    
    if not api_key or not secret_key:
        print("❌ ERRO: API Keys não encontradas nas Variáveis de Ambiente.")
        sys.exit(1)

    exchange = ccxt.binance({
        'apiKey': api_key,
        'secret': secret_key,
        'options': {'defaultType': 'future'}
    })
    return exchange

def obter_dados(exchange, symbol):
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=100)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        # Indicadores V55
        df['adx'] = ta.adx(df['high'], df['low'], df['close'])['ADX_14']
        df['rsi'] = ta.rsi(df['close'], length=14)
        
        # Bandas de Bollinger (para filtro extra do backtest)
        bb = ta.bbands(df['close'], length=20, std=2)
        df['lower'] = bb['BBL_20_2.0']
        df['upper'] = bb['BBU_20_2.0']
        
        return df.iloc[-1], df.iloc[-2] # Retorna vela atual e anterior
    except Exception as e:
        print(f"⚠️ Erro ao baixar dados de {symbol}: {e}")
        return None, None

def run_bot():
    print("🚀 INICIANDO ROBODERIK V55 (REAL)...")
    
    # 1. Carregar Estado e Conectar
    estado = carregar_estado()
    exchange = conectar_binance()
    
    # 2. Verificar Banca Atual na Binance
    try:
        balance = exchange.fetch_balance()
        banca_atual = float(balance['total']['USDT'])
        print(f"💰 Banca Atual: ${banca_atual:.2f} | Pico Histórico: ${estado['pico_banca']:.2f}")
    except Exception as e:
        print(f"❌ Erro ao ler saldo: {e}")
        return

    # 3. Atualizar Lógica de PnL e Martingale (Baseado na variação de saldo)
    pnl_ciclo = banca_atual - estado["ultima_banca"]
    
    # Reseta dia se mudou a data
    hoje = datetime.now().strftime("%Y-%m-%d")
    if estado["data_hoje"] != hoje:
        estado["data_hoje"] = hoje
        estado["trades_hoje"] = 0
        estado["pnl_hoje"] = 0.0
        print("📅 Novo dia iniciado. Resetando contadores diários.")

    # Se houve variação de saldo (trade fechou)
    if abs(pnl_ciclo) > 0.5: # Margem para evitar poeira
        estado["pnl_hoje"] += pnl_ciclo
        print(f"🔔 Trade detectado desde a última execução. PnL: ${pnl_ciclo:.2f}")
        
        if pnl_ciclo > 0:
            print("✅ WIN! Resetando Martingale para Nível 0.")
            estado["martingale_idx"] = 0
            if estado["em_quarentena"]:
                print("🛡️ Saiu da Quarentena (Lucro realizado).")
                estado["em_quarentena"] = False
        else:
            print(f"🔻 LOSS! Subindo Martingale para Nível {min(estado['martingale_idx'] + 1, 3)}.")
            estado["martingale_idx"] = min(estado["martingale_idx"] + 1, 3)

    # Atualiza Pico e Última Banca
    if banca_atual > estado["pico_banca"]:
        estado["pico_banca"] = banca_atual
    estado["ultima_banca"] = banca_atual

    # 4. Verificações de Segurança (Circuit Breakers)
    
    # Drawdown Global (Quarentena)
    drawdown = (estado["pico_banca"] - banca_atual) / estado["pico_banca"]
    if drawdown >= STOP_DRAWDOWN_GLOBAL:
        print(f"🛑 ALERTA: Drawdown de {drawdown*100:.2f}% atingido. Entrando em QUARENTENA.")
        estado["em_quarentena"] = True
        salvar_estado(estado)
        return

    if estado["em_quarentena"]:
        print("💤 Robô em QUARENTENA. Aguardando intervenção manual ou reset.")
        salvar_estado(estado)
        return

    # Stop Loss Diário
    limite_perda = -(banca_atual * STOP_LOSS_DIARIO_PERC)
    if estado["pnl_hoje"] <= limite_perda:
        print(f"🛑 Stop Loss Diário atingido (${estado['pnl_hoje']:.2f}). Encerrando por hoje.")
        salvar_estado(estado)
        return

    # Limite de Trades
    if estado["trades_hoje"] >= MAX_TRADES_DIA:
        print(f"⏸️ Limite de trades diários ({MAX_TRADES_DIA}) atingido.")
        salvar_estado(estado)
        return

    # 5. Verificar se já existe posição aberta
    try:
        positions = exchange.fetch_positions()
        tem_posicao = False
        for pos in positions:
            if float(pos['notional']) > 5: # Considera posição aberta se valor > $5
                print(f"⚠️ Posição aberta em {pos['symbol']}. Aguardando fechar.")
                tem_posicao = True
                break
        
        if tem_posicao:
            salvar_estado(estado)
            return
    except:
        pass

    # 6. Procurar Oportunidades (Estratégia V55)
    print("🔎 Escaneando mercado...")
    
    for symbol in SYMBOL_LIST:
        current, prev = obter_dados(exchange, symbol)
        if current is None: continue

        # Lógica V55: ADX < 30 (Mercado sem tendência forte, propício a reversão RSI)
        # RSI < 28 (Sobreventa -> COMPRA) ou RSI > 72 (Sobrecompra -> VENDA)
        
        signal = None
        
        if current['adx'] < 30 and current['volume'] > 0:
            if current['rsi'] < 28 and current['close'] < current['lower']:
                signal = 'buy'
                print(f"✅ SINAL COMPRA em {symbol} (RSI: {current['rsi']:.2f})")
            elif current['rsi'] > 72 and current['close'] > current['upper']:
                signal = 'sell'
                print(f"✅ SINAL VENDA em {symbol} (RSI: {current['rsi']:.2f})")

        if signal:
            # Calcular Tamanho da Posição com Martingale
            multiplicador = MARTINGALE_LEVELS[estado["martingale_idx"]]
            tamanho_usd = (banca_atual * PERCENTUAL_MAO_BASE) * multiplicador
            
            # Ajuste de segurança para não usar 100% da banca no Martingale alto
            if tamanho_usd > banca_atual * 0.95:
                tamanho_usd = banca_atual * 0.95

            price = current['close']
            amount = (tamanho_usd * ALAVANCAGEM) / price
            
            print(f"🚀 Executando {signal.upper()} em {symbol} | Valor: ${tamanho_usd:.2f} (Lvl {estado['martingale_idx']})")
            
            try:
                # Definir alavancagem
                exchange.set_leverage(ALAVANCAGEM, symbol)
                
                # Enviar Ordem a Mercado
                order = exchange.create_market_order(symbol, signal, amount)
                
                # Calcular Preços de TP e SL
                entry_price = float(order['average']) if order['average'] else price
                if signal == 'buy':
                    tp_price = entry_price * (1 + TARGET_TP)
                    sl_price = entry_price * (1 - TARGET_SL)
                else:
                    tp_price = entry_price * (1 - TARGET_TP)
                    sl_price = entry_price * (1 + TARGET_SL)
                
                # Enviar Ordens de Saída (TP e SL)
                # Nota: Na Binance Futures, enviamos ordens opostas com reduceOnly=True
                side_exit = 'sell' if signal == 'buy' else 'buy'
                
                # Stop Loss
                exchange.create_order(symbol, 'STOP_MARKET', amount, params={
                    'stopPrice': sl_price,
                    'reduceOnly': True
                })
                
                # Take Profit
                exchange.create_order(symbol, 'TAKE_PROFIT_MARKET', amount, params={
                    'stopPrice': tp_price,
                    'reduceOnly': True
                })
                
                print(f"✅ Ordens enviadas! Entrada: {entry_price} | TP: {tp_price} | SL: {sl_price}")
                
                # Atualizar Estado
                estado["trades_hoje"] += 1
                salvar_estado(estado)
                
                # Encerra loop após abrir 1 trade (evita overtrading simultâneo)
                break 
                
            except Exception as e:
                print(f"❌ Erro na execução: {e}")
                traceback.print_exc()

    salvar_estado(estado)

if __name__ == "__main__":
    run_bot()

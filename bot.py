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

for lib in ["yfinance", "pandas", "pandas_ta", "numpy", "pytz"]:
    install(lib)

import yfinance as yf
import pandas as pd
import pandas_ta as ta
import pytz

# --- CONFIGURAÇÕES V55 (SIMULAÇÃO YFINANCE) ---
# Símbolos no Yahoo Finance tem sufixo diferente
SYMBOL_MAP = {
    "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum", "SOL-USD": "Solana",
    "BNB-USD": "Binance Coin", "XRP-USD": "XRP", "ADA-USD": "Cardano"
}
TIMEFRAME = "15m"
ALAVANCAGEM = 3
PERCENTUAL_MAO_BASE = 0.10
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
        except: pass
            
    return {
        "banca_atual": 60.0,
        "pico_banca": 60.0,
        "martingale_idx": 0,
        "trades_hoje": 0,
        "data_hoje": datetime.now().strftime("%Y-%m-%d"),
        "pnl_hoje": 0.0,
        "em_quarentena": False,
        "posicao_aberta": None # Guarda o trade simulado
    }

def salvar_estado(estado):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(estado, f, indent=4)
    except Exception as e:
        print(f"❌ Erro ao salvar estado: {e}")

def obter_dados_yfinance(symbol):
    try:
        # Baixa 5 dias para garantir indicadores
        df = yf.download(symbol, period="5d", interval="15m", progress=False)
        if df.empty: return None
        
        # Ajuste para MultiIndex do Pandas novo
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
        
        # Indicadores V55
        df['adx'] = ta.adx(df['high'], df['low'], df['close'])['ADX_14']
        df['rsi'] = ta.rsi(df['close'], length=14)
        bb = ta.bbands(df['close'], length=20, std=2)
        df['lower'] = bb['BBL_20_2.0']
        df['upper'] = bb['BBU_20_2.0']
        
        return df.iloc[-1]
    except:
        return None

def run_bot():
    print("🚀 INICIANDO ROBODERIK V55 (SIMULAÇÃO REAL)...")
    estado = carregar_estado()
    
    # Reset Diário
    hoje = datetime.now().strftime("%Y-%m-%d")
    if estado["data_hoje"] != hoje:
        estado["data_hoje"] = hoje
        estado["trades_hoje"] = 0
        estado["pnl_hoje"] = 0.0
        print("📅 Novo dia iniciado.")

    # --- 1. VERIFICAR POSIÇÃO ABERTA (TP/SL) ---
    if estado["posicao_aberta"]:
        pos = estado["posicao_aberta"]
        symbol = pos["symbol"]
        print(f"👀 Monitorando posição em {symbol}...")
        
        dados = obter_dados_yfinance(symbol)
        if dados is None: 
            print("⚠️ Sem dados para monitorar.")
            return

        atual = dados['close']
        lucro = 0
        fechou = False
        motivo = ""

        # Lógica de Saída Simulada
        if pos["tipo"] == "buy":
            if atual >= pos["tp"]:
                lucro = (pos["valor_investido"] * ALAVANCAGEM * TARGET_TP)
                fechou = True; motivo = "TAKE PROFIT ✅"
            elif atual <= pos["sl"]:
                lucro = -(pos["valor_investido"] * ALAVANCAGEM * TARGET_SL)
                fechou = True; motivo = "STOP LOSS 🔻"
        else: # Sell
            if atual <= pos["tp"]:
                lucro = (pos["valor_investido"] * ALAVANCAGEM * TARGET_TP)
                fechou = True; motivo = "TAKE PROFIT ✅"
            elif atual >= pos["sl"]:
                lucro = -(pos["valor_investido"] * ALAVANCAGEM * TARGET_SL)
                fechou = True; motivo = "STOP LOSS 🔻"

        if fechou:
            estado["banca_atual"] += lucro
            estado["pnl_hoje"] += lucro
            estado["posicao_aberta"] = None # Limpa posição
            
            print(f"{motivo} | PnL: ${lucro:.2f} | Banca: ${estado['banca_atual']:.2f}")
            
            if lucro > 0:
                estado["martingale_idx"] = 0
                if estado["em_quarentena"]: 
                    estado["em_quarentena"] = False
                    print("🛡️ Saiu da Quarentena!")
            else:
                estado["martingale_idx"] = min(estado["martingale_idx"] + 1, 3)
                print(f"⚠️ Martingale subiu para Nível {estado['martingale_idx']}")
            
            if estado["banca_atual"] > estado["pico_banca"]:
                estado["pico_banca"] = estado["banca_atual"]
            
            salvar_estado(estado)
            return # Encerra execução para não abrir outro imediatamente

    # --- 2. VERIFICAÇÕES DE SEGURANÇA ---
    drawdown = (estado["pico_banca"] - estado["banca_atual"]) / estado["pico_banca"]
    
    if drawdown >= STOP_DRAWDOWN_GLOBAL:
        if not estado["em_quarentena"]:
            print(f"🛑 ALERTA: Drawdown {drawdown*100:.2f}%. Entrando em Quarentena.")
            estado["em_quarentena"] = True
            salvar_estado(estado)
        # Na simulação, continuamos operando mas marcamos como quarentena para saber
        # Se quiser parar total, descomente o return abaixo
        # return 

    limite_perda = -(estado["banca_atual"] * STOP_LOSS_DIARIO_PERC)
    if estado["pnl_hoje"] <= limite_perda:
        print(f"🛑 Stop Loss Diário atingido (${estado['pnl_hoje']:.2f}).")
        return

    if estado["trades_hoje"] >= MAX_TRADES_DIA:
        print(f"⏸️ Limite de trades diários ({MAX_TRADES_DIA}) atingido.")
        return

    # --- 3. PROCURAR NOVAS ENTRADAS ---
    if estado["posicao_aberta"] is None:
        print(f"🔎 Escaneando mercado (Banca: ${estado['banca_atual']:.2f})...")
        
        for symbol in SYMBOL_MAP.keys():
            data = obter_dados_yfinance(symbol)
            if data is None: continue

            # Lógica V55
            signal = None
            if data['adx'] < 30:
                if data['rsi'] < 28 and data['close'] < data['lower']:
                    signal = 'buy'
                elif data['rsi'] > 72 and data['close'] > data['upper']:
                    signal = 'sell'

            if signal:
                # Setup do Trade Simulado
                multiplicador = MARTINGALE_LEVELS[estado["martingale_idx"]]
                valor_entrada = (estado["banca_atual"] * PERCENTUAL_MAO_BASE) * multiplicador
                
                # Travas de tamanho
                if valor_entrada > estado["banca_atual"] * 0.95: 
                    valor_entrada = estado["banca_atual"] * 0.95
                
                price = data['close']
                
                # Calcula alvos
                if signal == 'buy':
                    tp = price * (1 + TARGET_TP)
                    sl = price * (1 - TARGET_SL)
                else:
                    tp = price * (1 - TARGET_TP)
                    sl = price * (1 + TARGET_SL)

                print(f"🚀 SINAL {signal.upper()} em {symbol}!")
                print(f"   Entrada: {price:.2f} | TP: {tp:.2f} | SL: {sl:.2f} | Valor: ${valor_entrada:.2f}")

                # Registra a "Ordem"
                estado["posicao_aberta"] = {
                    "symbol": symbol,
                    "tipo": signal,
                    "entrada": price,
                    "tp": tp,
                    "sl": sl,
                    "valor_investido": valor_entrada,
                    "data_hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                estado["trades_hoje"] += 1
                salvar_estado(estado)
                break # Um trade por vez

    salvar_estado(estado)

if __name__ == "__main__":
    try:
        run_bot()
    except Exception as e:
        print(f"Erro fatal: {e}")
        traceback.print_exc()
        

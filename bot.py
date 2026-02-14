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
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", package])

for lib in ["yfinance", "pandas", "pandas_ta", "numpy", "pytz"]:
    install(lib)

import yfinance as yf
import pandas as pd
import pandas_ta as ta
import numpy as np
import pytz

# --- CONFIGURAÇÕES V58 (SIMULAÇÃO YFINANCE) ---
SYMBOL_MAP = {
    "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum", "SOL-USD": "Solana",
    "BNB-USD": "Binance Coin", "XRP-USD": "XRP", "ADA-USD": "Cardano"
}
TIMEFRAME = "15m"
ALAVANCAGEM = 3
PERCENTUAL_MAO_BASE = 0.10
MARTINGALE_LEVELS = [1.0, 2.5, 5.5, 10.5]

# ALVOS ADAPTATIVOS
TP_NORMAL = 0.020
SL_NORMAL = 0.015
TP_SCALP = 0.008
SL_SCALP = 0.010

STOP_LOSS_DIARIO_PERC = 0.20
STOP_DRAWDOWN_GLOBAL = 0.25
MAX_TRADES_DIA = 10

STATE_FILE = "estado.json"

def carregar_estado():
    estado_padrao = {
        "banca_atual": 60.0,
        "pico_banca": 60.0,
        "martingale_idx": 0,
        "trades_hoje": 0,
        "data_hoje": datetime.now().strftime("%Y-%m-%d"),
        "pnl_hoje": 0.0,
        "em_quarentena": False,
        "posicao_aberta": None 
    }
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                estado_padrao.update(json.load(f))
        except: pass
    return estado_padrao

def salvar_estado(estado):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(estado, f, indent=4)
        print("💾 Estado salvo.")
    except Exception as e:
        print(f"❌ Erro ao salvar: {e}")

def obter_dados_yfinance(symbol):
    try:
        # Baixa dados (silencioso)
        df = yf.download(symbol, period="5d", interval=TIMEFRAME, progress=False)
        if df.empty: return None
        
        # Correção MultiIndex
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        # Padronizar nomes
        df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
        # Forçar minúsculo
        df.columns = [c.lower() for c in df.columns]

        if len(df) < 30: return None # Dados insuficientes

        # Indicadores
        df['adx'] = ta.adx(df['high'], df['low'], df['close'])['ADX_14']
        df['rsi'] = ta.rsi(df['close'], length=14)
        
        # --- CORREÇÃO DO ERRO BBL ---
        bb = ta.bbands(df['close'], length=20, std=2)
        if bb is not None:
            df['lower'] = bb.iloc[:, 0] # Coluna 0 é Lower
            df['upper'] = bb.iloc[:, 2] # Coluna 2 é Upper
        else:
            return None
        
        return df.iloc[-1]
    except Exception as e:
        print(f"⚠️ Erro dados {symbol}: {e}")
        return None

def run_bot():
    print(f"🚀 ROBODERIK V58 (SIMULAÇÃO) - {datetime.now().strftime('%H:%M')}")
    estado = carregar_estado()
    
    print(f"💰 Banca: ${estado['banca_atual']:.2f} | Hoje: {estado['trades_hoje']} trades")

    hoje = datetime.now().strftime("%Y-%m-%d")
    if estado["data_hoje"] != hoje:
        estado["data_hoje"] = hoje
        estado["trades_hoje"] = 0
        estado["pnl_hoje"] = 0.0
        print("📅 Novo dia iniciado.")

    # --- 1. MONITORAR POSIÇÃO ABERTA ---
    if estado["posicao_aberta"]:
        pos = estado["posicao_aberta"]
        symbol = pos["symbol"]
        print(f"👀 Acompanhando {symbol} ({pos['tipo']})...")
        
        dados = obter_dados_yfinance(symbol)
        if dados is not None:
            atual = float(dados['close'])
            lucro = 0; fechou = False; motivo = ""

            if pos["tipo"] == "buy":
                if atual >= pos["tp"]:
                    lucro = (pos["valor_investido"] * ALAVANCAGEM * ((atual/pos["entrada"])-1))
                    fechou = True; motivo = "✅ TAKE PROFIT"
                elif atual <= pos["sl"]:
                    lucro = (pos["valor_investido"] * ALAVANCAGEM * ((atual/pos["entrada"])-1))
                    fechou = True; motivo = "🔻 STOP LOSS"
            else: # sell
                if atual <= pos["tp"]:
                    lucro = (pos["valor_investido"] * ALAVANCAGEM * ((pos["entrada"]/atual)-1))
                    fechou = True; motivo = "✅ TAKE PROFIT"
                elif atual >= pos["sl"]:
                    lucro = (pos["valor_investido"] * ALAVANCAGEM * ((pos["entrada"]/atual)-1))
                    fechou = True; motivo = "🔻 STOP LOSS"

            if fechou:
                estado["banca_atual"] += lucro
                estado["pnl_hoje"] += lucro
                estado["posicao_aberta"] = None
                print(f"{motivo} | PnL: ${lucro:.2f} | Banca: ${estado['banca_atual']:.2f}")
                
                if lucro > 0:
                    estado["martingale_idx"] = 0
                    if estado["em_quarentena"]: estado["em_quarentena"] = False
                else:
                    estado["martingale_idx"] = min(estado["martingale_idx"] + 1, 3)
                
                if estado["banca_atual"] > estado["pico_banca"]: estado["pico_banca"] = estado["banca_atual"]
                salvar_estado(estado)
                return

    # --- 2. TRAVAS DE SEGURANÇA ---
    drawdown = (estado["pico_banca"] - estado["banca_atual"]) / estado["pico_banca"]
    if drawdown >= STOP_DRAWDOWN_GLOBAL:
        estado["em_quarentena"] = True
        print(f"🛑 Quarentena (DD {drawdown*100:.1f}%)")

    if estado["pnl_hoje"] <= -(estado["banca_atual"] * STOP_LOSS_DIARIO_PERC):
        print("🛑 Stop Diário atingido.")
        return

    if estado["trades_hoje"] >= MAX_TRADES_DIA:
        print("⏸️ Limite de trades atingido.")
        return

    # --- 3. ESCANEAMENTO ---
    if estado["posicao_aberta"] is None:
        print(f"🔎 Escaneando mercado...")
        
        for symbol, nome in SYMBOL_MAP.items():
            data = obter_dados_yfinance(symbol)
            if data is None: continue

            adx = data['adx']
            rsi = data['rsi']
            close = data['close']
            lower = data['lower']
            upper = data['upper']
            
            signal = None; modo = ""; tp_pct = 0; sl_pct = 0; msg = ""

            # Lógica Híbrida V56
            if adx < 20:
                modo = "SCALPER"
                if rsi < 35 and close < lower: signal = 'buy'
                elif rsi > 65 and close > upper: signal = 'sell'
                else: msg = f"RSI {rsi:.1f} (Neutro Scalp)"
                tp_pct = TP_SCALP; sl_pct = SL_SCALP

            elif adx < 30:
                modo = "SNIPER"
                if rsi < 28 and close < lower: signal = 'buy'
                elif rsi > 72 and close > upper: signal = 'sell'
                else: msg = f"RSI {rsi:.1f} (Aguardando Extremo)"
                tp_pct = TP_NORMAL; sl_pct = SL_NORMAL
            
            else:
                modo = "PERIGO"
                msg = f"Tendência Forte (ADX {adx:.1f})"

            if signal:
                print(f"🚀 SINAL {signal.upper()} em {nome} ({modo})")
                
                mult = MARTINGALE_LEVELS[estado["martingale_idx"]]
                valor = (estado["banca_atual"] * PERCENTUAL_MAO_BASE) * mult
                if valor > estado["banca_atual"] * 0.95: valor = estado["banca_atual"] * 0.95
                
                price = float(close)
                if signal == 'buy':
                    tp = price * (1 + tp_pct)
                    sl = price * (1 - sl_pct)
                else:
                    tp = price * (1 - tp_pct)
                    sl = price * (1 + sl_pct)

                estado["posicao_aberta"] = {
                    "symbol": symbol, "tipo": signal, "entrada": price,
                    "tp": tp, "sl": sl, "valor_investido": valor,
                    "data_hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                estado["trades_hoje"] += 1
                salvar_estado(estado)
                print(f"   💵 Entrada: ${valor:.2f} | TP: {tp:.4f} | SL: {sl:.4f}")
                break
            else:
                # Log Transparente
                print(f"   ⚪ {symbol:<9} | {modo:<8} | {msg}")

    salvar_estado(estado)

if __name__ == "__main__":
    try:
        run_bot()
    except Exception as e:
        print(f"❌ Erro: {e}")
        traceback.print_exc()
                

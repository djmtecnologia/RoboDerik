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
        # Instalação silenciosa
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", package])

for lib in ["yfinance", "pandas", "pandas_ta", "numpy", "pytz"]:
    install(lib)

import yfinance as yf
import pandas as pd
import pandas_ta as ta
import numpy as np
import pytz # Importante para o fuso horário

# --- CONFIGURAÇÕES DE FUSO E DATA ---
FUSO_BR = pytz.timezone('America/Sao_Paulo')

def obter_data_hora_br():
    """Retorna data e hora atuais em SP no formato DD/MM/YYYY HH:MM:SS"""
    return datetime.now(FUSO_BR).strftime("%d/%m/%Y %H:%M:%S")

def obter_data_hoje_br():
    """Retorna apenas a data atual em SP no formato DD/MM/YYYY"""
    return datetime.now(FUSO_BR).strftime("%d/%m/%Y")

# --- CONFIGURAÇÕES V71 (SIMULAÇÃO HÍBRIDA) ---
SYMBOL_MAP = {
    "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum", "SOL-USD": "Solana",
    "BNB-USD": "Binance Coin", "XRP-USD": "XRP", "ADA-USD": "Cardano"
}
TIMEFRAME = "15m"
ALAVANCAGEM = 3

# GESTÃO DE RISCO HÍBRIDA
PERC_MAO_GRID = 0.04    # 4%
PERC_MAO_SNIPER = 0.10  # 10%

# MARTINGALE ADAPTATIVO
NIVEIS_GRID = [1.0, 1.5, 2.5, 4.0]
NIVEIS_SNIPER = [1.0, 2.5, 5.5, 10.5]

# ALVOS
TP_GRID = 0.010; SL_GRID = 0.008
TP_SNIPER = 0.025; SL_SNIPER = 0.015

# SEGURANÇA
STOP_LOSS_DIARIO_PERC = 0.20
STOP_DRAWDOWN_GLOBAL = 0.25
MAX_TRADES_DIA = 12

STATE_FILE = "estado.json"

def carregar_estado():
    # Estado padrão com datas BR
    padrao = {
        "banca_atual": 60.0,
        "pico_banca": 60.0,
        "martingale_idx": 0,
        "trades_hoje": 0,
        "data_hoje": obter_data_hoje_br(), # Data BR
        "pnl_hoje": 0.0,
        "em_quarentena": False,
        "posicao_aberta": None
    }
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                padrao.update(json.load(f))
        except: pass
    return padrao

def salvar_estado(estado):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(estado, f, indent=4)
        print(f"💾 [{obter_data_hora_br()}] Estado salvo.")
    except Exception as e:
        print(f"❌ Erro ao salvar: {e}")

def obter_dados_yfinance(symbol):
    try:
        df = yf.download(symbol, period="5d", interval=TIMEFRAME, progress=False)
        if df.empty: return None
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
        df.columns = [c.lower() for c in df.columns]

        if len(df) < 30: return None

        df['adx'] = ta.adx(df['high'], df['low'], df['close'])['ADX_14']
        df['rsi'] = ta.rsi(df['close'], length=14)
        df['vol_ma'] = ta.sma(df['volume'], length=20)
        
        bb = ta.bbands(df['close'], length=20, std=2)
        if bb is not None:
            df['lower'] = bb.iloc[:, 0]
            df['upper'] = bb.iloc[:, 2]
        else:
            return None
        
        return df.iloc[-1]
    except Exception as e:
        print(f"⚠️ Erro dados {symbol}: {e}")
        return None

def run_bot():
    hora_atual = obter_data_hora_br()
    print(f"🚀 ROBODERIK V71 (SIMULAÇÃO HÍBRIDA) - {hora_atual} (BR)")
    
    estado = carregar_estado()
    
    print(f"💰 Banca Virtual: ${estado['banca_atual']:.2f} | Hoje: {estado['trades_hoje']} trades")

    # Verifica virada de dia (Fuso Brasil)
    hoje_br = obter_data_hoje_br()
    if estado["data_hoje"] != hoje_br:
        estado["data_hoje"] = hoje_br
        estado["trades_hoje"] = 0
        estado["pnl_hoje"] = 0.0
        print(f"📅 Novo dia iniciado em SP: {hoje_br}")

    # --- 1. MONITORAR POSIÇÃO ABERTA ---
    if estado["posicao_aberta"]:
        pos = estado["posicao_aberta"]
        symbol = pos["symbol"]
        print(f"👀 Acompanhando {symbol} ({pos['modo']})...")
        
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
                    if estado["em_quarentena"] and estado["banca_atual"] > estado["pico_banca"] * 0.90:
                        estado["em_quarentena"] = False
                        print("🛡️ Saiu da Quarentena!")
                else:
                    estado["martingale_idx"] += 1
                
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

    # --- 3. ESCANEAMENTO HÍBRIDO ---
    if estado["posicao_aberta"] is None:
        print(f"🔎 Analisando mercado ({obter_data_hora_br()})...")
        
        for symbol, nome in SYMBOL_MAP.items():
            row = obter_dados_yfinance(symbol)
            if row is None: continue

            adx = row['adx']; rsi = row['rsi']; close = row['close']
            lower = row['lower']; upper = row['upper']
            
            signal = None; modo = ""; tp_pct = 0; sl_pct = 0
            mao_base = 0; niveis = []

            # Lógica GRID (Lateral - ADX < 25)
            if adx < 25:
                if (close < lower and rsi < 45): signal = 'buy'
                elif (close > upper and rsi > 55): signal = 'sell'
                
                if signal:
                    modo = "GRID"
                    tp_pct = TP_GRID; sl_pct = SL_GRID
                    mao_base = estado["banca_atual"] * PERC_MAO_GRID
                    niveis = NIVEIS_GRID

            # Lógica SNIPER (Tendência - 25 <= ADX < 40)
            elif 25 <= adx < 40 and row['volume'] > row['vol_ma']:
                if (rsi < 28 and close < lower): signal = 'buy'
                elif (rsi > 72 and close > upper): signal = 'sell'
                
                if signal:
                    modo = "SNIPER"
                    tp_pct = TP_SNIPER; sl_pct = SL_SNIPER
                    mao_base = estado["banca_atual"] * PERC_MAO_SNIPER
                    niveis = NIVEIS_SNIPER

            if signal:
                print(f"🚀 SINAL {signal.upper()} em {nome} ({modo})")
                
                nivel_idx = min(estado["martingale_idx"], len(niveis)-1)
                mult = niveis[nivel_idx]
                valor = mao_base * mult
                
                if valor > estado["banca_atual"] * 0.95: valor = estado["banca_atual"] * 0.95
                
                price = float(close)
                if signal == 'buy':
                    tp = price * (1 + tp_pct)
                    sl = price * (1 - sl_pct)
                else:
                    tp = price * (1 - tp_pct)
                    sl = price * (1 + sl_pct)

                # REGISTRO COM DATA FORMATADA BR
                estado["posicao_aberta"] = {
                    "symbol": symbol, 
                    "tipo": signal, 
                    "modo": modo,
                    "entrada": price, 
                    "tp": tp, 
                    "sl": sl, 
                    "valor_investido": valor,
                    "data_hora": obter_data_hora_br() # <--- AQUI A MÁGICA
                }
                estado["trades_hoje"] += 1
                salvar_estado(estado)
                print(f"   💵 Entrada: ${valor:.2f} (Lvl {nivel_idx}) | Data: {obter_data_hora_br()}")
                break
            else:
                status = "GRID" if adx < 25 else ("SNIPER" if adx < 40 else "PERIGO")
                print(f"   ⚪ {symbol:<9} | {status:<6} | ADX {adx:.1f} | RSI {rsi:.1f}")

    salvar_estado(estado)

if __name__ == "__main__":
    try:
        run_bot()
    except Exception as e:
        print(f"❌ Erro Fatal: {e}")
        traceback.print_exc()
        

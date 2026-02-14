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

for lib in ["yfinance", "pandas", "pandas_ta", "numpy", "pytz"]:
    install(lib)

import yfinance as yf
import pandas as pd
import pandas_ta as ta
import numpy as np
import pytz

# --- CONFIGURAÇÕES V55 (SIMULAÇÃO YFINANCE) ---
# Mapeamento para nomes amigáveis no Log
SYMBOL_MAP = {
    "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum", "SOL-USD": "Solana",
    "BNB-USD": "Binance Coin", "XRP-USD": "XRP", "ADA-USD": "Cardano"
}

TIMEFRAME = "15m"
ALAVANCAGEM = 3
PERCENTUAL_MAO_BASE = 0.10  # 10% da banca
MARTINGALE_LEVELS = [1.0, 2.5, 5.5, 10.5]

# ALVOS
TARGET_TP = 0.020  # 2.0%
TARGET_SL = 0.015  # 1.5%

# SEGURANÇA
STOP_LOSS_DIARIO_PERC = 0.20 
STOP_DRAWDOWN_GLOBAL = 0.25 
MAX_TRADES_DIA = 5

STATE_FILE = "estado.json"

def carregar_estado():
    # Estado inicial padrão
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
                salvo = json.load(f)
                estado_padrao.update(salvo) # Mescla o salvo com o padrão (evita erros de chave)
                return estado_padrao
        except Exception as e:
            print(f"⚠️ Arquivo de estado corrompido ou ilegível: {e}. Iniciando novo.")
            
    return estado_padrao

def salvar_estado(estado):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(estado, f, indent=4)
        print("💾 Estado salvo com sucesso.")
    except Exception as e:
        print(f"❌ Erro ao salvar estado: {e}")

def obter_dados_yfinance(symbol):
    try:
        # Baixa dados recentes
        df = yf.download(symbol, period="5d", interval=TIMEFRAME, progress=False)
        
        if df.empty: return None
        
        # Tratamento para MultiIndex (Pandas novo)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
        
        # Indicadores V55
        df['adx'] = ta.adx(df['high'], df['low'], df['close'])['ADX_14']
        df['rsi'] = ta.rsi(df['close'], length=14)
        
        # Bandas de Bollinger (para refinar entrada)
        bb = ta.bbands(df['close'], length=20, std=2)
        df['lower'] = bb['BBL_20_2.0']
        df['upper'] = bb['BBU_20_2.0']
        
        return df.iloc[-1]
    except Exception as e:
        print(f"⚠️ Erro ao baixar {symbol}: {e}")
        return None

def run_bot():
    print("🚀 INICIANDO ROBODERIK V55 (SIMULAÇÃO YFINANCE)...")
    estado = carregar_estado()
    
    print(f"💰 Banca Virtual: ${estado['banca_atual']:.2f} | Martingale Lvl: {estado['martingale_idx']}")

    # --- RESET DIÁRIO ---
    hoje = datetime.now().strftime("%Y-%m-%d")
    if estado["data_hoje"] != hoje:
        estado["data_hoje"] = hoje
        estado["trades_hoje"] = 0
        estado["pnl_hoje"] = 0.0
        print("📅 Novo dia iniciado. Contadores zerados.")

    # --- 1. GERENCIAR POSIÇÃO ABERTA (SIMULAÇÃO DE SAÍDA) ---
    if estado["posicao_aberta"]:
        pos = estado["posicao_aberta"]
        symbol = pos["symbol"]
        print(f"👀 Monitorando posição aberta em {symbol} ({pos['tipo'].upper()})...")
        
        dados = obter_dados_yfinance(symbol)
        
        if dados is not None:
            atual = float(dados['close'])
            lucro = 0.0
            fechou = False
            motivo = ""

            # Verifica TP ou SL
            if pos["tipo"] == "buy":
                if atual >= pos["tp"]:
                    lucro = (pos["valor_investido"] * ALAVANCAGEM * TARGET_TP)
                    fechou = True; motivo = "✅ TAKE PROFIT"
                elif atual <= pos["sl"]:
                    lucro = -(pos["valor_investido"] * ALAVANCAGEM * TARGET_SL)
                    fechou = True; motivo = "🔻 STOP LOSS"
            else: # sell
                if atual <= pos["tp"]:
                    lucro = (pos["valor_investido"] * ALAVANCAGEM * TARGET_TP)
                    fechou = True; motivo = "✅ TAKE PROFIT"
                elif atual >= pos["sl"]:
                    lucro = -(pos["valor_investido"] * ALAVANCAGEM * TARGET_SL)
                    fechou = True; motivo = "🔻 STOP LOSS"

            if fechou:
                estado["banca_atual"] += lucro
                estado["pnl_hoje"] += lucro
                estado["posicao_aberta"] = None # Libera para novo trade
                
                print(f"{motivo} | Resultado: ${lucro:.2f} | Nova Banca: ${estado['banca_atual']:.2f}")
                
                if lucro > 0:
                    estado["martingale_idx"] = 0
                    if estado["em_quarentena"]:
                        estado["em_quarentena"] = False
                        print("🛡️ Saiu da Quarentena (Lucro realizado)!")
                else:
                    estado["martingale_idx"] = min(estado["martingale_idx"] + 1, 3)
                    print(f"⚠️ Martingale subiu para Nível {estado['martingale_idx']}")
                
                # Atualiza pico histórico para cálculo de drawdown
                if estado["banca_atual"] > estado["pico_banca"]:
                    estado["pico_banca"] = estado["banca_atual"]
                
                salvar_estado(estado)
                return # Sai para não abrir outro trade no mesmo segundo

    # --- 2. TRAVAS DE SEGURANÇA (CIRCUIT BREAKERS) ---
    
    # Drawdown Global (Quarentena)
    drawdown = (estado["pico_banca"] - estado["banca_atual"]) / estado["pico_banca"]
    if drawdown >= STOP_DRAWDOWN_GLOBAL:
        if not estado["em_quarentena"]:
            print(f"🛑 ALERTA CRÍTICO: Drawdown de {drawdown*100:.2f}% atingido.")
            estado["em_quarentena"] = True
            salvar_estado(estado)
    
    # Se estiver em quarentena, o robô continua operando (Simulado) para tentar sair dela com um Win
    if estado["em_quarentena"]:
        print("💤 Robô em MODO QUARENTENA (Tentando recuperar)...")

    # Stop Loss Diário
    limite_perda = -(estado["banca_atual"] * STOP_LOSS_DIARIO_PERC)
    if estado["pnl_hoje"] <= limite_perda:
        print(f"🛑 Stop Loss Diário atingido (${estado['pnl_hoje']:.2f}). Encerrando por hoje.")
        return

    # Limite de Trades
    if estado["trades_hoje"] >= MAX_TRADES_DIA:
        print(f"⏸️ Limite de trades diários ({MAX_TRADES_DIA}) atingido.")
        return

    # --- 3. ESCANEAMENTO DE MERCADO (BUSCAR ENTRADA) ---
    if estado["posicao_aberta"] is None:
        print(f"🔎 Escaneando mercado...")
        
        for symbol, nome in SYMBOL_MAP.items():
            data = obter_dados_yfinance(symbol)
            if data is None: 
                print(f"   ⚠️ {symbol}: Sem dados.")
                continue

            # Valores
            rsi = data['rsi']
            adx = data['adx']
            close = data['close']
            lower = data['lower']
            upper = data['upper']
            
            signal = None
            motivo_log = ""

            # Lógica V55: ADX < 30 (Lateral) + RSI Extremo
            if adx < 30:
                if rsi < 28:
                    if close < lower:
                        signal = 'buy'
                    else:
                        motivo_log = f"RSI {rsi:.1f} (OK), mas preço dentro da Banda."
                elif rsi > 72:
                    if close > upper:
                        signal = 'sell'
                    else:
                        motivo_log = f"RSI {rsi:.1f} (OK), mas preço dentro da Banda."
                else:
                    motivo_log = f"Neutro (RSI: {rsi:.1f})"
            else:
                motivo_log = f"Tendência muito forte (ADX: {adx:.1f})"

            if signal:
                print(f"🚀 SINAL {signal.upper()} em {nome} ({symbol})!")
                
                # Cálculo da Posição (Martingale)
                multiplicador = MARTINGALE_LEVELS[estado["martingale_idx"]]
                valor_entrada = (estado["banca_atual"] * PERCENTUAL_MAO_BASE) * multiplicador
                
                # Trava de segurança de tamanho
                if valor_entrada > estado["banca_atual"] * 0.95:
                    valor_entrada = estado["banca_atual"] * 0.95
                
                # Definição de TP e SL
                price = float(close)
                if signal == 'buy':
                    tp = price * (1 + TARGET_TP)
                    sl = price * (1 - TARGET_SL)
                else:
                    tp = price * (1 - TARGET_TP)
                    sl = price * (1 + TARGET_SL)

                print(f"   💵 Entrada: ${valor_entrada:.2f} (Lvl {estado['martingale_idx']})")
                print(f"   🎯 Alvos: Entrada {price:.4f} | TP {tp:.4f} | SL {sl:.4f}")

                # Registra a Posição no JSON
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
                break # Encerra o loop para focar neste trade
            
            else:
                # Log discreto do motivo de não entrada
                print(f"   ⚪ {symbol}: {motivo_log}")

    salvar_estado(estado)

if __name__ == "__main__":
    try:
        run_bot()
    except Exception as e:
        print(f"❌ Erro Fatal: {e}")
        traceback.print_exc()

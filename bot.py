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

# --- CONFIGURAÇÕES DE FUSO E DATA ---
FUSO_BR = pytz.timezone('America/Sao_Paulo')

def obter_data_hora_br():
    return datetime.now(FUSO_BR).strftime("%d/%m/%Y %H:%M:%S")

def obter_data_hoje_br():
    return datetime.now(FUSO_BR).strftime("%d/%m/%Y")

# --- CONFIGURAÇÕES V80 (AUDITORIA DETALHADA MARTINGALE) ---
SYMBOL_MAP = {
    "BTC-USD": "Bitcoin", 
    "ETH-USD": "Ethereum", 
    "SOL-USD": "Solana",
    "BNB-USD": "Binance Coin", 
    "XRP-USD": "XRP", 
    "ADA-USD": "Cardano"
}
TIMEFRAME = "15m"
ALAVANCAGEM = 3

# GESTÃO DE RISCO
PERC_MAO_GRID = 0.04    # 4% da banca em mercados laterais
PERC_MAO_SNIPER = 0.10  # 10% da banca em tendências claras

# MARTINGALE ADAPTATIVO (FATORES DE MULTIPLICAÇÃO)
# Nível 0 = 1.0x, Nível 1 = 1.5x, etc.
NIVEIS_GRID = [1.0, 1.5, 2.5, 4.0]
NIVEIS_SNIPER = [1.0, 2.5, 5.5, 10.5]

# ALVOS (Take Profit / Stop Loss)
TP_GRID = 0.010; SL_GRID = 0.008
TP_SNIPER = 0.025; SL_SNIPER = 0.015

# SEGURANÇA
STOP_LOSS_DIARIO_PERC = 0.20  # Para se perder 20% da banca no dia
STOP_DRAWDOWN_GLOBAL = 0.25   # Quarentena se cair 25% do topo histórico
MAX_TRADES_DIA = 12

STATE_FILE = "estado.json"

def carregar_estado():
    padrao = {
        "banca_atual": 60.0,
        "pico_banca": 60.0,
        "martingale_idx": 0,
        "trades_hoje": 0,
        "data_hoje": obter_data_hoje_br(),
        "pnl_hoje": 0.0,
        "em_quarentena": False,
        "posicao_aberta": None,
        "historico_trades": []
    }
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                carregado = json.load(f)
                padrao.update(carregado)
                if "historico_trades" not in padrao: padrao["historico_trades"] = []
        except Exception as e:
            print(f"⚠️ Erro ao carregar estado: {e}. Usando padrão.")
    return padrao

def salvar_estado(estado):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(estado, f, indent=4)
        # print(f"💾 [{obter_data_hora_br()}] Estado salvo.") # Comentei para limpar o log
    except Exception as e:
        print(f"❌ Erro ao salvar: {e}")

def obter_dados_yfinance(symbol):
    try:
        # Baixa dados (progress=False remove a barra de carregamento)
        df = yf.download(symbol, period="5d", interval=TIMEFRAME, progress=False)
        
        if df.empty: return None
        
        # Tratamento para novas versões do YFinance (MultiIndex)
        if isinstance(df.columns, pd.MultiIndex): 
            df.columns = df.columns.get_level_values(0)
            
        # Renomear para minúsculo para padronizar
        df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
        df.columns = [c.lower() for c in df.columns]
        
        if len(df) < 30: return None

        # Indicadores
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
        # print(f"Erro dados {symbol}: {e}")
        return None

def run_bot():
    hora_atual = obter_data_hora_br()
    print(f"🚀 ROBODERIK V80 (MARTINGALE FACTOR) - {hora_atual} (BR)")
    
    estado = carregar_estado()
    trades_totais = len(estado.get("historico_trades", []))
    print(f"💰 Banca: ${estado['banca_atual']:.2f} | PnL Hoje: ${estado['pnl_hoje']:.2f} | Histórico: {trades_totais} trades")
    print(f"🔥 Nível Martingale Atual: {estado['martingale_idx']}")

    # Verifica virada do dia
    hoje_br = obter_data_hoje_br()
    if estado["data_hoje"] != hoje_br:
        estado["data_hoje"] = hoje_br
        estado["trades_hoje"] = 0
        estado["pnl_hoje"] = 0.0
        print(f"📅 Novo dia iniciado: {hoje_br}")

    # --- 1. MONITORAMENTO DE POSIÇÃO ABERTA ---
    if estado["posicao_aberta"]:
        pos = estado["posicao_aberta"]
        symbol = pos["symbol"]
        print(f"👀 Acompanhando {symbol} ({pos['modo']})... Entrada: {pos['entrada']:.4f}")
        
        dados = obter_dados_yfinance(symbol)
        if dados is not None:
            atual = float(dados['close'])
            lucro = 0; fechou = False; motivo = ""

            # Cálculo de PnL (Long ou Short)
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
                
                # --- REGISTRO COMPLETO V80 ---
                novo_trade = {
                    "data": obter_data_hora_br(),
                    "symbol": symbol,
                    "modo": pos['modo'],
                    "tipo": pos['tipo'].upper(),
                    "nivel_mg": pos.get('nivel_mg', 0),    # Nivel (0, 1, 2)
                    "fator_mg": pos.get('fator_mg', 1.0),  # Fator (1.0x, 1.5x)
                    "investido": round(pos['valor_investido'], 2),
                    "perc_banca": pos.get('perc_banca', 0.0),
                    "entrada": pos['entrada'],
                    "saida": atual,
                    "criterio": pos.get("criterio", "N/A"),
                    "resultado": motivo,
                    "lucro_usd": round(lucro, 2),
                    "saldo_pos_trade": round(estado["banca_atual"], 2)
                }
                
                estado["historico_trades"].append(novo_trade)
                # Mantém apenas os últimos 100 trades no JSON para não ficar gigante
                if len(estado["historico_trades"]) > 100: 
                    estado["historico_trades"].pop(0)

                estado["posicao_aberta"] = None
                print(f"{motivo} | PnL: ${lucro:.2f} | Fator MG: {novo_trade['fator_mg']}x")
                
                # Lógica Martingale: Reset se ganhar, +1 se perder
                if lucro > 0:
                    estado["martingale_idx"] = 0
                    # Sai da quarentena se recuperar 90% do topo
                    if estado["em_quarentena"] and estado["banca_atual"] > estado["pico_banca"] * 0.90:
                        estado["em_quarentena"] = False
                else:
                    estado["martingale_idx"] += 1
                
                # Atualiza pico histórico da banca
                if estado["banca_atual"] > estado["pico_banca"]: 
                    estado["pico_banca"] = estado["banca_atual"]
                
                salvar_estado(estado)
                return

    # --- 2. TRAVAS DE SEGURANÇA ---
    drawdown = (estado["pico_banca"] - estado["banca_atual"]) / estado["pico_banca"]
    if drawdown >= STOP_DRAWDOWN_GLOBAL:
        estado["em_quarentena"] = True
        print(f"🛑 Quarentena Global Ativada (DD {drawdown*100:.1f}%)")

    if estado["pnl_hoje"] <= -(estado["banca_atual"] * STOP_LOSS_DIARIO_PERC):
        print("🛑 Stop Loss Diário atingido. O bot vai descansar até amanhã.")
        return

    if estado["trades_hoje"] >= MAX_TRADES_DIA:
        print("⏸️ Limite de trades diários atingido.")
        return

    # --- 3. ESCANEAMENTO DE OPORTUNIDADES ---
    if estado["posicao_aberta"] is None:
        print(f"🔎 Escaneando mercado...")
        for symbol, nome in SYMBOL_MAP.items():
            row = obter_dados_yfinance(symbol)
            if row is None: continue

            adx = row['adx']; rsi = row['rsi']; close = row['close']
            lower = row['lower']; upper = row['upper']
            volume = row['volume']; vol_ma = row['vol_ma']
            
            signal = None; modo = ""; tp_pct = 0; sl_pct = 0
            mao_base = 0; niveis = []
            criterio_desc = ""

            # ESTRATÉGIA 1: GRID (Mercado Lateral / ADX Baixo)
            if adx < 25:
                if (close < lower and rsi < 45): 
                    signal = 'buy'; criterio_desc = f"GRID: ADX {adx:.1f} | RSI {rsi:.1f} < 45 | Low BB"
                elif (close > upper and rsi > 55): 
                    signal = 'sell'; criterio_desc = f"GRID: ADX {adx:.1f} | RSI {rsi:.1f} > 55 | High BB"
                
                if signal:
                    modo = "GRID"; tp_pct = TP_GRID; sl_pct = SL_GRID
                    mao_base = estado["banca_atual"] * PERC_MAO_GRID; niveis = NIVEIS_GRID

            # ESTRATÉGIA 2: SNIPER (Tendência / ADX Médio + Volume)
            elif 25 <= adx < 40 and volume > vol_ma:
                if (rsi < 28 and close < lower): 
                    signal = 'buy'; criterio_desc = f"SNIPER: ADX {adx:.1f} | RSI {rsi:.1f} < 28 | Vol High"
                elif (rsi > 72 and close > upper): 
                    signal = 'sell'; criterio_desc = f"SNIPER: ADX {adx:.1f} | RSI {rsi:.1f} > 72 | Vol High"
                
                if signal:
                    modo = "SNIPER"; tp_pct = TP_SNIPER; sl_pct = SL_SNIPER
                    mao_base = estado["banca_atual"] * PERC_MAO_SNIPER; niveis = NIVEIS_SNIPER

            # EXECUÇÃO DA ENTRADA
            if signal:
                print(f"🚀 SINAL ENCONTRADO: {signal.upper()} em {nome} ({modo})")
                
                # Cálculo do Martingale
                nivel_idx = min(estado["martingale_idx"], len(niveis)-1)
                mult = niveis[nivel_idx] # Fator de multiplicação
                valor = mao_base * mult
                
                # Trava de segurança para não usar 100% da banca num hit kill
                if valor > estado["banca_atual"] * 0.95: 
                    valor = estado["banca_atual"] * 0.95
                
                price = float(close)
                tp = price * (1 + tp_pct) if signal == 'buy' else price * (1 - tp_pct)
                sl = price * (1 - sl_pct) if signal == 'buy' else price * (1 + sl_pct)
                
                perc_banca_usada = round((valor / estado["banca_atual"]) * 100, 2)

                estado["posicao_aberta"] = {
                    "symbol": symbol, "tipo": signal, "modo": modo,
                    "entrada": price, "tp": tp, "sl": sl, 
                    "valor_investido": valor,
                    "nivel_mg": nivel_idx,      
                    "fator_mg": mult,           
                    "perc_banca": perc_banca_usada,
                    "criterio": criterio_desc,
                    "data_hora": obter_data_hora_br()
                }
                estado["trades_hoje"] += 1
                salvar_estado(estado)
                print(f"   💵 Ordem executada: ${valor:.2f} (Fator {mult}x | {perc_banca_usada}% da banca)")
                break # Sai do loop para focar neste trade
            else:
                status = "GRID" if adx < 25 else ("SNIPER" if adx < 40 else "PERIGO")
                print(f"   ⚪ {symbol:<9} | {status:<6} | ADX {adx:.1f} | RSI {rsi:.1f}")

    salvar_estado(estado)

if __name__ == "__main__":
    try: 
        run_bot()
    except Exception as e:
        traceback.print_exc()
                

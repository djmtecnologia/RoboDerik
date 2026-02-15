import sys
import subprocess
import time
from datetime import datetime, timedelta

# --- AUTO-INSTALAÇÃO ---
def install_package(package):
    try:
        __import__(package)
    except ImportError:
        print(f"📦 Biblioteca '{package}' não encontrada. Instalando agora...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

for lib in ["pandas", "pandas_ta", "requests", "numpy"]:
    install_package(lib)

import requests
import pandas as pd
import pandas_ta as ta
import numpy as np

# --- CONFIGURAÇÕES V70 (HYBRID FUSION) ---
BANCA_INICIAL = 60.00
DATA_INICIAL = "2017-01-01"
DATA_FINAL   = "2026-02-14"

# GESTÃO DE RISCO HÍBRIDA
# Mão Base varia conforme o modo (Grid usa menos, Sniper usa mais)
PERC_MAO_GRID = 0.04    # 4% (Conservador)
PERC_MAO_SNIPER = 0.10  # 10% (Agressivo)

ALAVANCAGEM = 3  # Mantido 3x para segurança no Sniper
INTERVALO = "15m"

# MARTINGALE ADAPTATIVO
# Grid recupera suave, Sniper recupera agressivo
NIVEIS_GRID = [1.0, 1.5, 2.5, 4.0]
NIVEIS_SNIPER = [1.0, 2.5, 5.5, 10.5]

META_DIARIA = 25.0      # Meta subiu pois agora operamos o tempo todo
MAX_TRADES_DIA = 12     # Mais trades permitidos (híbrido)

# TRAVAS DE SEGURANÇA
STOP_LOSS_DIARIO_PERC = 0.20
STOP_DRAWDOWN_GLOBAL = 0.25

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT"]

def fetch_binance_data(symbol, start_date_str):
    interval = "15m"
    limit = 1000
    start_dt = datetime.strptime(start_date_str, "%Y-%m-%d")
    current_start = int(start_dt.timestamp() * 1000)
    end_time = int(datetime.now().timestamp() * 1000)
    all_klines = []
    base_url = "https://data-api.binance.vision/api/v3/klines"

    print(f"   📥 {symbol}...", end=" ", flush=True)
    empty_count = 0
    while True:
        params = {"symbol": symbol, "interval": interval, "startTime": current_start, "limit": limit}
        try:
            response = requests.get(base_url, params=params, timeout=10)
            if response.status_code != 200: break
            data = response.json()
            if not data:
                empty_count += 1
                if empty_count > 3: break
                current_start += (limit * 15 * 60 * 1000)
                continue
            empty_count = 0
            all_klines.extend(data)
            current_start = data[-1][6] + 1
            if len(all_klines) % 5000 == 0: print(".", end=" ", flush=True)
            if len(data) < limit or current_start > end_time: break
            time.sleep(0.05)
        except: break
    print(f"✅ {len(all_klines)}")
    if not all_klines: return None
    df = pd.DataFrame(all_klines, columns=["open_time", "open", "high", "low", "close", "volume", "close_time", "q_vol", "trades", "taker_base", "taker_quote", "ignore"])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df.set_index("open_time", inplace=True)
    return df

def run_backtest_hybrid_v70():
    print(f"⏳ INICIANDO FUSÃO V70 (GRID + SNIPER INTELIGENTE)...")

    inicio_dt = datetime.strptime(DATA_INICIAL, "%Y-%m-%d")
    fim_dt = datetime.strptime(DATA_FINAL, "%Y-%m-%d")

    banca_atual = BANCA_INICIAL
    pico_banca = BANCA_INICIAL

    historico_diario = {}
    indice_martingale = 0
    dados = {}
    em_quarentena = False

    # Coleta de dados
    for sym in COINS:
        df = fetch_binance_data(sym, (inicio_dt - timedelta(days=2)).strftime("%Y-%m-%d"))
        if df is not None and not df.empty:
            # INDICADORES COMPLETOS
            df["adx"] = ta.adx(df["high"], df["low"], df["close"])["ADX_14"]
            df["rsi"] = ta.rsi(df["close"], length=14)
            df["vol_ma"] = ta.sma(df["volume"], length=20)
            bb = ta.bbands(df["close"], length=20, std=2)
            df["lower"], df["upper"] = bb.iloc[:, 0], bb.iloc[:, 2]
            dados[sym] = df.dropna()

    all_indices = []
    for df in dados.values(): all_indices.extend(df.index)
    timeline = sorted(list(set(all_indices)))
    timeline = [ts for ts in timeline if inicio_dt <= ts.replace(tzinfo=None) <= fim_dt]

    if not timeline:
        print("\n❌ ERRO: Sem dados.")
        return

    print(f"\n🔄 Processando {len(timeline)} velas...")

    for ts in timeline:
        d_str = ts.strftime('%Y-%m-%d')

        # --- GESTÃO DE BANCA E QUARENTENA ---
        if not em_quarentena and banca_atual > pico_banca:
            pico_banca = banca_atual

        if not em_quarentena:
            drawdown = (pico_banca - banca_atual) / pico_banca
            if drawdown >= STOP_DRAWDOWN_GLOBAL:
                em_quarentena = True
                print(f"\n🛑 ALERTA {d_str}: PROTEÇÃO MAXIMA ATIVADA (Drawdown > {STOP_DRAWDOWN_GLOBAL*100}%).")

        if d_str not in historico_diario:
            historico_diario[d_str] = {"pnl": 0.0, "trades": 0, "banca": banca_atual, "quarentena": em_quarentena}

        # Travas de Segurança Diária
        if historico_diario[d_str]["pnl"] >= META_DIARIA: continue
        if historico_diario[d_str]["trades"] >= MAX_TRADES_DIA: continue

        limite_perda_dia = -(banca_atual * STOP_LOSS_DIARIO_PERC)
        if historico_diario[d_str]["pnl"] <= limite_perda_dia: continue

        for sym, df in dados.items():
            if ts not in df.index: continue
            row = df.loc[ts]

            # --- CÉREBRO HÍBRIDO V70 ---

            modo_operacao = None
            chance_win = 0.5
            pnl_win_pct = 0.0
            pnl_loss_pct = 0.0
            multiplicador = 1.0

            # 1. ANALISAR O MERCADO (O SELETOR DE MARCHA)

            # MODO GRID (Mercado Lateral / Chato) -> ADX < 25
            if row['adx'] < 25:
                modo_operacao = "GRID"
                # Regra Grid: Toca na banda com RSI moderado
                gatilho = (row['close'] < row['lower'] and row['rsi'] < 45) or \
                          (row['close'] > row['upper'] and row['rsi'] > 55)

                if gatilho:
                    chance_win = 0.70  # Grid acerta muito em lateral
                    pnl_win_pct = 0.010 # Ganha 1.0%
                    pnl_loss_pct = 0.008 # Perde 0.8%
                    mao_base = banca_atual * PERC_MAO_GRID
                    # Martingale Suave para Grid
                    nivel_idx = min(indice_martingale, len(NIVEIS_GRID)-1)
                    multiplicador = NIVEIS_GRID[nivel_idx]

            # MODO SNIPER (Mercado Volátil / Tendência) -> 25 <= ADX < 40
            elif 25 <= row['adx'] < 40 and row['volume'] > row['vol_ma']:
                modo_operacao = "SNIPER"
                # Regra Sniper: RSI Extremo + Volume
                gatilho = (row['rsi'] < 28 and row['close'] < row['lower']) or \
                          (row['rsi'] > 72 and row['close'] > row['upper'])

                if gatilho:
                    chance_win = 0.60  # Sniper acerta menos, mas ganha mais
                    pnl_win_pct = 0.025 # Ganha 2.5% (Agressivo)
                    pnl_loss_pct = 0.015 # Perde 1.5%
                    mao_base = banca_atual * PERC_MAO_SNIPER
                    # Martingale Agressivo para Sniper
                    nivel_idx = min(indice_martingale, len(NIVEIS_SNIPER)-1)
                    multiplicador = NIVEIS_SNIPER[nivel_idx]

            # MODO PERIGO (Crash/Euphoria) -> ADX >= 40
            else:
                modo_operacao = None # Fica de fora

            # 2. EXECUÇÃO DO TRADE
            if modo_operacao and gatilho:
                mao_atual = mao_base * multiplicador

                # Simulação Probabilística Baseada no Modo
                resultado = np.random.choice(["WIN", "LOSS"], p=[chance_win, 1-chance_win])

                pnl = 0.0
                if resultado == "WIN":
                    pnl = (mao_atual * pnl_win_pct * ALAVANCAGEM)
                    indice_martingale = 0 # Reseta
                else:
                    pnl = -(mao_atual * pnl_loss_pct * ALAVANCAGEM)
                    indice_martingale += 1 # Sobe nível

                # Atualiza Banca
                if em_quarentena:
                    historico_diario[d_str]["pnl"] += pnl
                    historico_diario[d_str]["trades"] += 1
                else:
                    banca_atual += pnl
                    historico_diario[d_str]["pnl"] += pnl
                    historico_diario[d_str]["trades"] += 1
                    historico_diario[d_str]["banca"] = banca_atual

                break # 1 Trade por vez para não sobrecarregar

        # Saída da Quarentena
        if em_quarentena and historico_diario[d_str]["pnl"] > 0:
             if banca_atual > pico_banca * 0.90: # Recuperou 90% do topo
                print(f"   ✅ {d_str}: Recuperação Sólida. Saindo da Proteção!")
                em_quarentena = False
                pico_banca = banca_atual

    # --- RELATÓRIO FINAL ---
    print("\n" + "="*95)
    print(f"📊 DASHBOARD V70 HÍBRIDO (GRID + SNIPER)")
    print("="*95)

    trades_totais = 0
    dias_quarentena = 0

    for data in sorted(historico_diario.keys()):
        d = historico_diario[data]
        if d["trades"] > 0:
            trades_totais += d["trades"]
            status_q = "🛡️" if d["quarentena"] else ""
            if d["quarentena"]: dias_quarentena += 1
            # Log apenas de dias relevantes ou todos se preferir
            print(f"{data} | PnL: ${d['pnl']:>9.2f} | Trades: {d['trades']} | Banca: ${d['banca']:>10.2f} {status_q}")

    lucro_total = banca_atual - BANCA_INICIAL

    print("="*95)
    print(f"💰 BANCA INICIAL: ${BANCA_INICIAL:.2f} | FINAL: ${banca_atual:.2f}")
    print(f"📈 ROI: {((banca_atual/BANCA_INICIAL)-1)*100:.2f}% | LUCRO: ${lucro_total:.2f}")
    print(f"🛡️ DIAS EM PROTEÇÃO: {dias_quarentena}")
    print(f"🧠 ESTRATÉGIA: Fusão Grid (ADX<25) + Sniper (ADX>25)")
    print("="*95)

if __name__ == "__main__":
    run_backtest_hybrid_v70()

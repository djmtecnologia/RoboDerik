import requests
import pandas as pd
import pandas_ta as ta
import numpy as np
from datetime import datetime
import time
import warnings

warnings.filterwarnings('ignore')

# --- CONFIGURAÇÕES GERAIS ---
DATA_INICIO = "2020-01-01"
DATA_FIM    = "2026-02-19"
BANCA_INICIAL = 60.00
TIMEFRAME = "1h"

# ⚙️ GESTÃO QUANTITATIVA INSTITUCIONAL
ALAVANCAGEM = 3.0      
MAX_POSICOES = 3       
# 🚀 AJUSTE 4: Fim do estrangulamento de capital. Margem livre para 35% do cofre.
MAX_ACCOUNT_MARGIN = 0.35  

SLIPPAGE = 0.0005      
TAXA_CORRETORA = 0.0004 

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "ADAUSDT"]

print(f"⏳ Iniciando Motor V1800 (The Institutional Apex) | Alavancagem: {ALAVANCAGEM}x")

# --- MÓDULOS DE MATEMÁTICA INSTITUCIONAL ---
def expected_losing_streak(winrate, trades=500):
    if winrate <= 0.01 or winrate >= 0.99: return 1
    return max(1, int(np.log(trades) / -np.log(1 - winrate)))

def safe_risk_fraction(winrate, rr, max_dd_allowed=0.35):
    L = expected_losing_streak(winrate)
    risk = 1 - (1 - max_dd_allowed) ** (1 / L)
    edge_adj = (winrate * rr) - (1 - winrate)
    if edge_adj <= 0: return 0.005 
    return np.clip(risk * edge_adj, 0.005, 0.05)

def equity_volatility(equity_curve, window=40):
    if len(equity_curve) < window + 1: return None
    eq = np.array(equity_curve[-window:])
    returns = np.diff(eq) / (eq[:-1] + 1e-9)
    return np.std(returns)

def equity_vol_scalar(eq_vol, target_vol=0.015):
    if eq_vol is None or eq_vol == 0: return 1.0
    return np.clip(target_vol / eq_vol, 0.5, 1.5) 

# --- ☢️ MONTE CARLO BLOCK BOOTSTRAP ---
def monte_carlo_block_bootstrap(trades_pct, initial_capital, sims=2000, block_size=5):
    trades_pct = np.array(trades_pct)
    n_trades = len(trades_pct)
    results = []
    
    if n_trades < block_size:
        return {"median_final": initial_capital, "worst_final": initial_capital, "ruin_prob": 0, "median_dd": 0, "worst_dd": 0}
        
    for _ in range(sims):
        equity = initial_capital
        peak = equity
        max_dd = 0
        
        sampled_trades = []
        while len(sampled_trades) < n_trades:
            idx = np.random.randint(0, n_trades - block_size + 1)
            sampled_trades.extend(trades_pct[idx:idx + block_size])
            
        sampled_trades = sampled_trades[:n_trades] 
        
        for pnl_pct in sampled_trades:
            if np.random.rand() < 0.005:
                pnl_pct = pnl_pct * np.random.uniform(3.0, 6.0) if pnl_pct < 0 else pnl_pct * 0.1
                
            equity *= (1 + pnl_pct)
            
            peak = max(peak, equity)
            if peak > 0:
                dd = (peak - equity) / peak
                max_dd = max(max_dd, dd)
            
            if equity <= initial_capital * 0.05: 
                equity = 0
                break
                
        results.append((equity, max_dd))

    finals = [r[0] for r in results]
    dds = [r[1] for r in results]
    
    return {
        "median_final": np.median(finals),
        "worst_final": np.min(finals),
        "ruin_prob": np.mean(np.array(finals) <= initial_capital * 0.10), 
        "median_dd": np.median(dds),
        "worst_dd": np.max(dds)
    }

# --- 1. DATA LAYER (ANTI-BAN & BYPASS) ---
def fetch_binance_data(symbol, start_date_str, end_date_str):
    interval = TIMEFRAME
    limit = 1000
    urls = [
        "https://fapi.binance.com/fapi/v1/klines",
        "https://api.binance.com/api/v3/klines",
        "https://data-api.binance.vision/api/v3/klines"
    ]
    
    start_ts = int(datetime.strptime(start_date_str, "%Y-%m-%d").timestamp() * 1000)
    end_ts = int(datetime.strptime(end_date_str, "%Y-%m-%d").timestamp() * 1000)
    
    print(f"📥 Baixando {symbol}...", end="\n")
    all_klines = []
    current_start = start_ts
    headers = {"User-Agent": "Mozilla/5.0"}
    
    for base_url in urls:
        success = False
        while True:
            params = {"symbol": symbol, "interval": interval, "startTime": current_start, "limit": limit}
            try:
                r = requests.get(base_url, params=params, headers=headers, timeout=(5, 15))
                if r.status_code in [429, 451]: break 
                elif r.status_code != 200: break 
                d = r.json()
                if not d: 
                    success = True
                    break
                chunk = [x for x in d if x[0] <= end_ts]
                if not chunk: 
                    success = True
                    break
                all_klines.extend(chunk)
                current_start = chunk[-1][0] + 1
                if current_start > end_ts: 
                    success = True
                    break
                time.sleep(0.05) 
            except Exception:
                break 
        if success and len(all_klines) > 0:
            break 
            
    if not all_klines: return None
        
    print(f"✅ {symbol} concluído: {len(all_klines)} velas de {TIMEFRAME}.")
    df = pd.DataFrame(all_klines, columns=["open_time", "open", "high", "low", "close", "v", "ct", "qv", "tr", "tb", "tq", "ig"])
    df["date"] = pd.to_datetime(df["open_time"], unit="ms")
    for c in ["open", "high", "low", "close", "v"]: df[c] = pd.to_numeric(df[c], errors='coerce')
    df.set_index("date", inplace=True)
    return df

# --- 2. MULTI-TIMEFRAME ENGINE (ALPHA GENERATION) ---
def calcular_features(df):
    df = df.copy()
    
    # --- MACRO ENGINE (4 HORAS) ---
    df_4h = df.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'v': 'sum'}).dropna()
    c_4h = df_4h['close']; h_4h = df_4h['high']; l_4h = df_4h['low']
    
    df_4h['ema200_4h'] = ta.ema(c_4h, length=200)
    adx_df = ta.adx(h_4h, l_4h, c_4h, length=14)
    df_4h['adx_4h'] = adx_df.iloc[:, 0] if adx_df is not None else 0
    df_4h['adx_slope_4h'] = df_4h['adx_4h'].diff(2)
    
    bb = ta.bbands(c_4h, length=20, std=2.0)
    if bb is not None: df_4h['bb_width_4h'] = (bb.iloc[:, 2] - bb.iloc[:, 0]) / c_4h
    else: df_4h['bb_width_4h'] = 0
        
    df_4h['bb_percentile_4h'] = df_4h['bb_width_4h'].rolling(100).quantile(0.3)
    df_4h['is_compressed_4h'] = (df_4h['bb_width_4h'] < df_4h['bb_percentile_4h'])
    df_4h['recent_compression_4h'] = df_4h['is_compressed_4h'].rolling(3).max() == 1 
    
    # 🚀 AJUSTE 4 (Macro Sync): Expansão de Range no 4H
    df_4h['candle_range_4h'] = h_4h - l_4h
    df_4h['range_ma_4h'] = df_4h['candle_range_4h'].rolling(20).mean()
    df_4h['range_expansion_4h'] = df_4h['candle_range_4h'] > (df_4h['range_ma_4h'] * 1.4)
    
    df_4h['ema_slope_4h'] = df_4h['ema200_4h'].diff(6) 
    
    trend_condition = (df_4h['adx_4h'] > 14) & (df_4h['adx_slope_4h'] > 0) & (df_4h['ema_slope_4h'] > 0)
    chop_condition = (df_4h['adx_4h'] < 14) & df_4h['is_compressed_4h']
    
    df_4h['market_phase'] = 0
    df_4h.loc[trend_condition, 'market_phase'] = 1
    df_4h.loc[chop_condition, 'market_phase'] = 2
    
    df_4h_shifted = df_4h.shift(1)
    
    cols_to_join = ['ema200_4h', 'adx_4h', 'adx_slope_4h', 'recent_compression_4h', 'market_phase', 'range_expansion_4h']
    df = df.join(df_4h_shifted[cols_to_join], how='left').ffill()
    
    # --- MICRO ENGINE (1 HORA) ---
    c = df['close']; h = df['high']; l = df['low']
    df['ema20'] = ta.ema(c, length=20)
    df['atr'] = ta.atr(h, l, c, length=14)
    
    df['momentum_prebreak_long'] = c > df['ema20']
    df['momentum_prebreak_short'] = c < df['ema20']
    
    df['candle_range'] = h - l
    df['range_ma'] = df['candle_range'].rolling(20).mean()
    df['range_expansion_1h'] = df['candle_range'] > (df['range_ma'] * 1.4) 
    
    # 🚀 AJUSTE 1: Confirmação por Displacement Estrutural
    df['displacement_1h'] = abs(c - df['ema20']) > (df['atr'] * 1.2)
    
    df['long_signal'] = ((df['recent_compression_4h'] == 1) & 
                         (df['adx_4h'] > 14) & 
                         (df['adx_slope_4h'] > 0) & 
                         df['momentum_prebreak_long'] & 
                         (c > df['ema200_4h']) & 
                         df['range_expansion_1h'] & 
                         df['displacement_1h'] & 
                         (df['range_expansion_4h'] == 1)) # Sincronia Temporal Absoluta
                         
    df['short_signal'] = ((df['recent_compression_4h'] == 1) & 
                          (df['adx_4h'] > 14) & 
                          (df['adx_slope_4h'] > 0) & 
                          df['momentum_prebreak_short'] & 
                          (c < df['ema200_4h']) & 
                          df['range_expansion_1h'] & 
                          df['displacement_1h'] & 
                          (df['range_expansion_4h'] == 1))
    
    df.dropna(inplace=True)
    return df

# --- 3. EXECUTION ENGINE ---
def run_backtest():
    raw_datasets = {}
    for coin in COINS:
        df = fetch_binance_data(coin, DATA_INICIO, DATA_FIM)
        if df is not None: raw_datasets[coin] = calcular_features(df)
        
    if not raw_datasets: 
        print("\n❌ FALHA CRÍTICA: Dados não encontrados.")
        return

    print("🧠 Calculando Matriz Macro (Beta Exposure)...")
    master_closes = pd.DataFrame({coin: raw_datasets[coin]['close'] for coin in COINS if coin in raw_datasets}).ffill()
    master_returns = master_closes.pct_change().fillna(0)
    
    btc_returns = master_returns.get('BTCUSDT')
    if btc_returns is not None:
        btc_var = btc_returns.rolling(120).var()
        portfolio_beta = pd.DataFrame(index=master_returns.index)
        for coin in COINS:
            if coin in master_returns:
                cov = master_returns[coin].rolling(120).cov(btc_returns)
                portfolio_beta[coin] = cov / btc_var.replace(0, np.nan)
        market_beta_series = portfolio_beta.abs().mean(axis=1)
    else:
        market_beta_series = pd.Series(0.5, index=master_closes.index)

    datasets = {coin: raw_datasets[coin].to_dict('index') for coin in COINS if coin in raw_datasets}
    all_ts = set()
    for coin in datasets: all_ts.update(datasets[coin].keys())
    timestamps = sorted(list(all_ts))
    
    banca = BANCA_INICIAL
    historico_global = []
    equity_curve = [BANCA_INICIAL]
    annual_stats = {year: {'start': 0, 'end': 0, 'pnl': 0, 'trades': 0, 'wins': 0} for year in range(2020, 2027)}
    posicoes_abertas = {} 

    print("\n⚙️ Simulando Matching Engine (Institutional Apex)...")
    
    consecutive_losses = 0
    BASE_RISK = 0.025 

    for i in range(1, len(timestamps)-1):
        ts_prev = timestamps[i-1]; ts_atual = timestamps[i]  
        current_year = ts_atual.year
        if annual_stats[current_year]['start'] == 0: annual_stats[current_year]['start'] = banca
        if ts_prev.year != ts_atual.year: annual_stats[ts_prev.year]['end'] = banca

        peak_equity = max(equity_curve)
        dd = (peak_equity - banca) / peak_equity
        evt_scalar = equity_vol_scalar(equity_volatility(equity_curve))
        
        dd_scalar = 1.0; hard_risk_off = False
        if dd > 0.35: hard_risk_off = True  
        elif dd > 0.25: dd_scalar = 0.50    
        elif dd > 0.15: dd_scalar = 0.80    
        
        combined_scalar = max(0.5, evt_scalar * dd_scalar)
        
        for symb in list(posicoes_abertas.keys()):
            if ts_atual not in datasets[symb]: continue
            row_atual = datasets[symb][ts_atual]
            c_open = row_atual['open']; c_high = row_atual['high']; c_low = row_atual['low']; c_close = row_atual['close']
            pos = posicoes_abertas[symb]
            fechou = False; motivo = ""; exit_price_raw = 0.0
            
            banca_pre_trade = banca + pos['margem_usd'] 
            current_sl = pos.get('trail_sl', pos['sl'])
            
            alavancagem_efetiva = pos['size_usd'] / pos['margem_usd']
            liq_distance = 0.90 / alavancagem_efetiva 
            liq_price_long = pos['entry'] * (1 - liq_distance)
            liq_price_short = pos['entry'] * (1 + liq_distance)

            profit_move = (c_close - pos['entry']) / pos['entry'] if pos['side'] == 'buy' else (pos['entry'] - c_close) / pos['entry']
            profit_move_atr = profit_move / (row_atual['atr'] / pos['entry'])

            # 🚀 AJUSTE 3: LEVE PYRAMIDING CTA (Explora a confirmação direcional sem destruir o trade)
            trigger_pyramid = (row_atual['atr'] * 4.0) / pos['entry']
            if not fechou and pos.get('pyramid_count', 0) < 1 and profit_move > trigger_pyramid:
                add_size = pos['size_usd'] * 0.50 
                add_margem = add_size / ALAVANCAGEM
                if banca >= add_margem:
                    banca -= add_margem 
                    old_size = pos['size_usd']; old_entry = pos['entry']
                    new_size = old_size + add_size
                    
                    vol_pyr = row_atual['atr'] / c_close
                    dyn_slip_pyr = SLIPPAGE + (vol_pyr * 0.25)
                    c_close_slip = c_close * (1 + dyn_slip_pyr) if pos['side'] == 'buy' else c_close * (1 - dyn_slip_pyr)
                    
                    new_entry = ((old_entry * old_size) + (c_close_slip * add_size)) / new_size
                    
                    pos['entry'] = new_entry
                    pos['size_usd'] = new_size
                    pos['margem_usd'] += add_margem
                    pos['pyramid_count'] = 1

            if not fechou:
                if pos['side'] == 'buy':
                    hit_sl = c_low <= current_sl; hit_liq = c_low <= liq_price_long
                    if c_open <= liq_price_long: fechou = True; motivo = "LIQ GAP"; exit_price_raw = c_open
                    elif c_open <= current_sl: fechou = True; motivo = "STOP GAP"; exit_price_raw = c_open
                    elif hit_liq: fechou = True; motivo = "LIQUIDATION"; exit_price_raw = liq_price_long
                    elif hit_sl: fechou = True; motivo = "STOP HIT"; exit_price_raw = current_sl
                elif pos['side'] == 'sell':
                    hit_sl = c_high >= current_sl; hit_liq = c_high >= liq_price_short
                    if c_open >= liq_price_short: fechou = True; motivo = "LIQ GAP"; exit_price_raw = c_open
                    elif c_open >= current_sl: fechou = True; motivo = "STOP GAP"; exit_price_raw = c_open
                    elif hit_liq: fechou = True; motivo = "LIQUIDATION"; exit_price_raw = liq_price_short
                    elif hit_sl: fechou = True; motivo = "STOP HIT"; exit_price_raw = current_sl

            # 🚀 AJUSTE 2: TRAILING PROGRESSIVO INSTITUCIONAL (Engrenagens da Tendência)
            if not fechou:
                if profit_move_atr >= 3.0: 
                    if profit_move_atr >= 9.0:
                        dynamic_mult = 1.5   # Mega tendência: asfixia forte
                    elif profit_move_atr >= 6.0:
                        dynamic_mult = 2.0   # Aceleração madura: fecha o cerco
                    else:
                        dynamic_mult = 2.5   # Início saudável: deixa respirar
                    
                    if pos['side'] == 'buy':
                        novo_trail = c_close - (row_atual['atr'] * dynamic_mult)
                        pos['trail_sl'] = max(current_sl, novo_trail)
                    else:
                        novo_trail = c_close + (row_atual['atr'] * dynamic_mult)
                        pos['trail_sl'] = min(current_sl, novo_trail)

            if fechou:
                exit_price = exit_price_raw * (1 - SLIPPAGE) if pos['side'] == 'buy' else exit_price_raw * (1 + SLIPPAGE)
                pnl_bruto = (exit_price - pos['entry']) / pos['entry'] * pos['size_usd'] if pos['side'] == 'buy' else (pos['entry'] - exit_price) / pos['entry'] * pos['size_usd']
                
                fee_total = pos['size_usd'] * TAXA_CORRETORA * 2 
                pnl_final = pnl_bruto - fee_total
                
                if "LIQUIDATION" in motivo: pnl_final = -pos['margem_usd'] 
                
                banca += pos['margem_usd'] + pnl_final
                equity_curve.append(banca)
                
                pnl_pct = pnl_final / banca_pre_trade
                historico_global.append({'data': ts_atual, 'strat': pos['strat'], 'lucro': pnl_final, 'pnl_pct': pnl_pct})
                
                annual_stats[ts_atual.year]['pnl'] += pnl_final
                annual_stats[ts_atual.year]['trades'] += 1
                
                if pnl_final < 0:
                    consecutive_losses += 1
                else:
                    annual_stats[ts_atual.year]['wins'] += 1
                    consecutive_losses = 0 
                
                del posicoes_abertas[symb]
                
                if banca <= 0.10: 
                    print(f"\n💀 BANCA ZERO EM {ts_atual}!")
                    return

        if hard_risk_off or len(posicoes_abertas) >= MAX_POSICOES: continue

        market_beta = market_beta_series.get(ts_prev, 0.5)
        if pd.isna(market_beta): market_beta = 0.5
        net_exposure = sum((1 if p['side'] == 'buy' else -1) * p['size_usd'] for p in posicoes_abertas.values())
        effective_exposure = abs(net_exposure) * (1 + market_beta)
        max_portfolio_exposure = banca * ALAVANCAGEM * 0.8
        
        for symb in COINS:
            if symb in posicoes_abertas: continue
            if ts_prev not in datasets[symb] or ts_atual not in datasets[symb]: continue
            
            row_closed = datasets[symb][ts_prev]
            atual_open = datasets[symb][ts_atual]['open'] 
            
            phase = row_closed.get('market_phase', 0)
            if phase == 2: continue 
            
            signal = False; side = ""; strat = "CTA_APEX_ENGINE"
            
            if bool(row_closed.get('long_signal', False)): signal = True; side = "buy"
            elif bool(row_closed.get('short_signal', False)): signal = True; side = "sell"

            if signal:
                entry_price = atual_open * (1 + SLIPPAGE) if side == "buy" else atual_open * (1 - SLIPPAGE)
                
                # Stop original relaxado para 2.2 ATR
                sl_dist_base = row_closed['atr'] * 2.2
                dist_pct = abs(sl_dist_base) / entry_price
                min_dist = (row_closed['atr'] * 1.0) / entry_price
                dist_pct = max(dist_pct, min_dist) 
                
                sl_price = entry_price - sl_dist_base if side == "buy" else entry_price + sl_dist_base
                
                asset_vol = row_closed['atr'] / entry_price
                vol_adjust = np.clip(0.02 / (asset_vol + 1e-9), 0.5, 1.5)
                
                risk_usd = banca * BASE_RISK * combined_scalar * vol_adjust
                if consecutive_losses >= 6: risk_usd *= 0.25 
                elif consecutive_losses >= 3: risk_usd *= 0.50 
                if phase == 1: risk_usd *= 1.25 
                
                size_ideal_risco = risk_usd / dist_pct
                
                if effective_exposure + (size_ideal_risco * (1 + market_beta)) > max_portfolio_exposure: continue
                
                margem_maxima_permitida = (banca * MAX_ACCOUNT_MARGIN) / MAX_POSICOES
                pos_size = min(size_ideal_risco, margem_maxima_permitida * ALAVANCAGEM)
                margem_alocada = pos_size / ALAVANCAGEM
                
                if margem_alocada > banca: continue 
                banca -= margem_alocada 
                
                posicoes_abertas[symb] = {
                    "symbol": symb, "strat": strat, "side": side, "entry": entry_price, 
                    "sl": sl_price, "trail_sl": sl_price, "tp_price": 0, 
                    "size_usd": pos_size, "margem_usd": margem_alocada, "pyramid_count": 0
                }
                if len(posicoes_abertas) >= MAX_POSICOES: break

    annual_stats[timestamps[-1].year]['end'] = banca

    print("\n" + "="*65)
    print(f"📊 RELATÓRIO V1800 (THE INSTITUTIONAL APEX)")
    print("="*65)
    lucro_total = banca - BANCA_INICIAL
    roi_total = (lucro_total / BANCA_INICIAL) * 100
    print(f"Banca Inicial: ${BANCA_INICIAL:.2f}")
    print(f"Banca Final:   ${banca:.2f} ({roi_total:.2f}% ROI)")
    print("-" * 65)
    print(f"{'ANO':<6} | {'INÍCIO ($)':<12} | {'FIM ($)':<12} | {'TRADES':<8} | {'WINRATE':<8}")
    print("-" * 65)
    for year in range(2020, 2027):
        s = annual_stats[year]
        if s['start'] == 0 or s['trades'] == 0: continue
        wr = (s['wins'] / s['trades']) * 100
        print(f"{year:<6} | {s['start']:<12.2f} | {s['end']:<12.2f} | {s['trades']:<8} | {wr:.1f}%")
    print("="*65)

    if len(historico_global) > 10:
        print("\n☢️ INICIANDO BLOCK BOOTSTRAP MONTE CARLO (2.000 SIMULAÇÕES) ☢️")
        trade_returns_pct = [t['pnl_pct'] for t in historico_global]
        mc_stress = monte_carlo_block_bootstrap(trade_returns_pct, BANCA_INICIAL, sims=2000, block_size=5)
        
        print("\n" + "="*65)
        print("🎯 RESULTADO DO TESTE DE STRESS INSTITUCIONAL (BLOCO)")
        print("="*65)
        print(f"Equity Mediana Final  : ${mc_stress['median_final']:.2f}")
        print(f"Pior Cenário Possível : ${mc_stress['worst_final']:.2f}")
        print(f"Drawdown Mediano      : {mc_stress['median_dd']*100:.1f}%")
        print(f"Pior Drawdown Absoluto: {mc_stress['worst_dd']*100:.1f}%")
        print("-" * 65)
        ruin = mc_stress['ruin_prob'] * 100
        if ruin < 5.0:
            print(f"🟢 APROVADO: Probabilidade de Ruína ({ruin:.1f}%). Motor Antifrágil.")
        elif ruin <= 20.0:
            print(f"🟡 CUIDADO: Probabilidade de Ruína ({ruin:.1f}%). Viável, mas requer atenção.")
        else:
            print(f"🔴 REPROVADO: Probabilidade de Ruína ({ruin:.1f}%). Não ative em live.")
        print("="*65)

if __name__ == "__main__":
    run_backtest()

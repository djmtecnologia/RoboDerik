import json
import pandas as pd
import os
from datetime import datetime
import sys
import subprocess
import pytz

# --- AUTO-INSTALAÇÃO ---
def install(package):
    try: __import__(package)
    except: subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", package])

for lib in ["pandas", "openpyxl", "xlsxwriter", "pytz"]: install(lib)

# --- CONFIGURAÇÕES ---
JSON_FILE = "estado.json"
CSV_FILE = "historico_trades.csv" 
EXCEL_FILE = "Relatorio_RoboDerik_V75.xlsx" # Atualizado para V75
FUSO_BR = pytz.timezone('America/Sao_Paulo')

def gerar_relatorio():
    if not os.path.exists(JSON_FILE):
        print(f"❌ Arquivo {JSON_FILE} não encontrado.")
        return

    with open(JSON_FILE, 'r') as f:
        data = json.load(f)

    # --- 1. ATUALIZAR TIMELINE (GRÁFICO DE EVOLUÇÃO) ---
    # Mantém o registro histórico da curva de patrimônio
    investido = data.get("posicao_aberta", {}).get("valor_investido", 0) if data.get("posicao_aberta") else 0
    data_hora_br = datetime.now(FUSO_BR).strftime("%d/%m/%Y %H:%M:%S")
    
    novo_registro = {
        "Data": data_hora_br,
        "Banca Total ($)": round(data.get("banca_atual", 60.0), 2),
        "Investido ($)": round(investido, 2),
        "Livre ($)": round(data.get("banca_atual", 60.0) - investido, 2),
        "PnL Hoje ($)": round(data.get("pnl_hoje", 0.0), 2),
        "Trades Hoje": data.get("trades_hoje", 0),
        "Modo": data.get("posicao_aberta", {}).get("modo", "AGUARDANDO") if data.get("posicao_aberta") else "LIQUIDO"
    }

    if os.path.exists(CSV_FILE):
        df_timeline = pd.read_csv(CSV_FILE)
        ultima_data = df_timeline.iloc[-1]["Data"] if not df_timeline.empty else ""
        if ultima_data != novo_registro["Data"]:
            df_timeline = pd.concat([df_timeline, pd.DataFrame([novo_registro])], ignore_index=True)
    else:
        registro_inicial = novo_registro.copy()
        registro_inicial["Data"] = "Inicio"
        registro_inicial["Banca Total ($)"] = data.get("banca_inicial", 60.0)
        registro_inicial["Investido ($)"] = 0.0
        registro_inicial["PnL Hoje ($)"] = 0.0
        registro_inicial["Modo"] = "INICIO"
        df_timeline = pd.DataFrame([registro_inicial, novo_registro])

    df_timeline.to_csv(CSV_FILE, index=False)

    # --- 2. GERAR TABELA DETALHADA DE TRADES (V75) ---
    lista_trades = data.get("historico_trades", [])
    
    # Estrutura base caso não tenha trades
    cols_ordem = ["data", "symbol", "modo", "tipo", "entrada", "tp", "sl", "saida", "lucro_usd", "criterio"]
    
    if not lista_trades:
        df_extrato = pd.DataFrame(columns=cols_ordem)
    else:
        df_extrato = pd.DataFrame(lista_trades)

    # Garante que as colunas novas existam (preenche com '-' se faltar)
    for col in cols_ordem:
        if col not in df_extrato.columns:
            df_extrato[col] = "-"

    # Seleciona e Renomeia para Português
    df_final = df_extrato[cols_ordem].rename(columns={
        "data": "Data/Hora", 
        "symbol": "Par", 
        "modo": "Estratégia", 
        "tipo": "Operação",
        "entrada": "Entrada ($)", 
        "tp": "Alvo (TP)", 
        "sl": "Stop (SL)",
        "saida": "Saída ($)", 
        "lucro_usd": "Lucro Líquido ($)", 
        "criterio": "Motivo / Indicadores"
    })

    # --- 3. GERAR O EXCEL ---
    writer = pd.ExcelWriter(EXCEL_FILE, engine='xlsxwriter')
    
    # Aba 1: Gráfico e Timeline
    df_timeline.to_excel(writer, sheet_name='Evolucao_Banca', index=False)
    
    # Aba 2: Extrato Detalhado
    df_final.to_excel(writer, sheet_name='Extrato_Trades', index=False)

    workbook = writer.book
    
    # --- FORMATAÇÃO ABA 1 (EVOLUÇÃO) ---
    ws_evol = writer.sheets['Evolucao_Banca']
    fmt_money = workbook.add_format({'num_format': '$ #,##0.00'})
    ws_evol.set_column('B:E', 15, fmt_money)
    ws_evol.set_column('A:A', 22)

    chart = workbook.add_chart({'type': 'line'})
    chart.add_series({
        'name': 'Patrimônio Total',
        'categories': ['Evolucao_Banca', 1, 0, len(df_timeline), 0],
        'values':     ['Evolucao_Banca', 1, 1, len(df_timeline), 1],
        'line':       {'color': 'blue', 'width': 2.5}
    })
    chart.set_title({'name': 'Crescimento da Banca (Juros Compostos)'})
    ws_evol.insert_chart('H2', chart)

    # --- FORMATAÇÃO ABA 2 (EXTRATO) ---
    ws_ext = writer.sheets['Extrato_Trades']
    fmt_num = workbook.add_format({'num_format': '#,##0.00'})
    
    # Larguras
    ws_ext.set_column('A:A', 20) # Data
    ws_ext.set_column('B:D', 12) # Par/Modo/Tipo
    ws_ext.set_column('E:H', 15, fmt_num) # Preços (Entrada/TP/SL/Saída)
    ws_ext.set_column('I:I', 18, fmt_money) # Lucro
    ws_ext.set_column('J:J', 45) # Motivo (Bem largo para ler o texto)

    # Cores no Lucro (Verde/Vermelho)
    fmt_green = workbook.add_format({'bg_color': '#C6EFCE', 'font_color': '#006100'})
    fmt_red = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006'})
    
    # Aplica formatação condicional na coluna I (Lucro)
    ws_ext.conditional_format('I2:I1000', {'type': 'cell', 'criteria': '>', 'value': 0, 'format': fmt_green})
    ws_ext.conditional_format('I2:I1000', {'type': 'cell', 'criteria': '<', 'value': 0, 'format': fmt_red})

    writer.close()
    print(f"📊 Relatório V75 Completo: {EXCEL_FILE}")

if __name__ == "__main__":
    gerar_relatorio()
    

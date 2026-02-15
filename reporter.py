import json
import pandas as pd
import os
from datetime import datetime
import sys
import subprocess
import pytz

# --- CONFIGURAÇÕES ---
JSON_FILE = "estado.json"
CSV_FILE = "historico_trades.csv" # Mantemos para o gráfico de evolução
EXCEL_FILE = "Relatorio_RoboDerik_V74.xlsx"
FUSO_BR = pytz.timezone('America/Sao_Paulo')

def gerar_relatorio():
    if not os.path.exists(JSON_FILE):
        print(f"❌ Arquivo {JSON_FILE} não encontrado.")
        return

    with open(JSON_FILE, 'r') as f:
        data = json.load(f)

    # --- 1. ATUALIZAR TIMELINE (GRÁFICO DE EVOLUÇÃO) ---
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
        # Só adiciona se passou pelo menos 1 minuto para evitar spam
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

    # --- 2. GERAR TABELA DE TRADES REAIS (EXTRATO) ---
    lista_trades = data.get("historico_trades", [])
    df_extrato = pd.DataFrame(lista_trades) if lista_trades else pd.DataFrame(columns=["Sem trades ainda"])

    # --- 3. GERAR EXCEL COM DUAS ABAS ---
    writer = pd.ExcelWriter(EXCEL_FILE, engine='xlsxwriter')
    
    # Aba 1: Evolução (Gráfico)
    df_timeline.to_excel(writer, sheet_name='Evolucao_Banca', index=False)
    
    # Aba 2: Extrato (Lista de Trades Únicos)
    df_extrato.to_excel(writer, sheet_name='Extrato_Trades', index=False)

    workbook = writer.book
    
    # --- FORMATAÇÃO ABA EVOLUÇÃO ---
    ws_evolucao = writer.sheets['Evolucao_Banca']
    formato_money = workbook.add_format({'num_format': '$ #,##0.00'})
    ws_evolucao.set_column('B:E', 15, formato_money)
    ws_evolucao.set_column('A:A', 22)

    # Gráfico de Linha
    chart = workbook.add_chart({'type': 'line'})
    chart.add_series({
        'name': 'Banca',
        'categories': ['Evolucao_Banca', 1, 0, len(df_timeline), 0],
        'values':     ['Evolucao_Banca', 1, 1, len(df_timeline), 1],
        'line':       {'color': 'blue', 'width': 2}
    })
    ws_evolucao.insert_chart('H2', chart)

    # --- FORMATAÇÃO ABA EXTRATO ---
    ws_extrato = writer.sheets['Extrato_Trades']
    ws_extrato.set_column('A:Z', 18) # Ajusta largura
    
    # Formatação Condicional (Verde/Vermelho) no Lucro
    if not df_extrato.empty and "lucro_usd" in df_extrato.columns:
        col_idx = df_extrato.columns.get_loc("lucro_usd")
        letra_col = chr(65 + col_idx) # Converte índice 0->A, 1->B...
        formato_verde = workbook.add_format({'bg_color': '#C6EFCE', 'font_color': '#006100'})
        formato_vermelho = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006'})
        
        ws_extrato.conditional_format(f'{letra_col}2:{letra_col}1000', {'type': 'cell', 'criteria': '>', 'value': 0, 'format': formato_verde})
        ws_extrato.conditional_format(f'{letra_col}2:{letra_col}1000', {'type': 'cell', 'criteria': '<', 'value': 0, 'format': formato_vermelho})

    writer.close()
    print(f"📊 Relatório V74 Gerado: {EXCEL_FILE}")
    print("👉 Aba 1: Gráfico de Crescimento")
    print("👉 Aba 2: Lista Real de Trades (Sem duplicatas)")

if __name__ == "__main__":
    gerar_relatorio()
    

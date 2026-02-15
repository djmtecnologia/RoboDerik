import json
import pandas as pd
import os
import sys
import subprocess
import pytz
from datetime import datetime

# --- AUTO-INSTALAÇÃO ---
def install(package):
    try: __import__(package)
    except: subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", package])

for lib in ["pandas", "openpyxl", "xlsxwriter", "pytz"]: install(lib)

# --- CONFIGURAÇÕES ---
JSON_FILE = "estado.json"
EXCEL_FILE = "Relatorio_Oficial_Trades.xlsx"
FUSO_BR = pytz.timezone('America/Sao_Paulo')

def gerar_relatorio():
    if not os.path.exists(JSON_FILE):
        print(f"❌ Arquivo {JSON_FILE} não encontrado.")
        return

    with open(JSON_FILE, 'r') as f:
        data = json.load(f)

    raw_trades = data.get("historico_trades", [])
    
    if not raw_trades:
        print("⚠️ Nenhum trade fechado para relatar.")
        return

    # --- 1. NORMALIZAÇÃO DOS DADOS (O SEGREDO) ---
    # Transforma trades antigos e novos num formato único
    trades_processados = []
    
    for t in raw_trades:
        # Detecta se é chave antiga (lucro) ou nova (lucro_usd)
        lucro_real = t.get("lucro_usd") if "lucro_usd" in t else t.get("lucro", 0.0)
        saldo_real = t.get("saldo_pos_trade") if "saldo_pos_trade" in t else t.get("saldo_final", 0.0)
        
        item = {
            "Data": t.get("data"),
            "Par": t.get("symbol"),
            "Modo": t.get("modo"),
            "Tipo": t.get("tipo", "N/A").upper(), # Garante maiúsculo
            "Entrada": t.get("entrada", 0.0),
            "Saida": t.get("saida", 0.0),
            "TP": t.get("tp", 0.0),
            "SL": t.get("sl", 0.0),
            "Criterio": t.get("criterio", "Trade Antigo (Sem registro)"),
            "Resultado": t.get("resultado", ""),
            "Lucro ($)": float(lucro_real),
            "Saldo Acumulado": float(saldo_real)
        }
        trades_processados.append(item)

    df = pd.DataFrame(trades_processados)

    # --- 2. GERAR EXCEL ---
    writer = pd.ExcelWriter(EXCEL_FILE, engine='xlsxwriter')
    df.to_excel(writer, sheet_name='Extrato_Detalhado', index=False)

    workbook = writer.book
    worksheet = writer.sheets['Extrato_Detalhado']

    # --- 3. FORMATAÇÃO VISUAL ---
    # Formatos
    fmt_money = workbook.add_format({'num_format': '$ #,##0.00'})
    fmt_num = workbook.add_format({'num_format': '#,##0.00'})
    fmt_center = workbook.add_format({'align': 'center'})
    
    # Cores Condicionais para Lucro
    fmt_green = workbook.add_format({'bg_color': '#C6EFCE', 'font_color': '#006100'})
    fmt_red = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006'})

    # Aplicação de Larguras e Formatos
    worksheet.set_column('A:A', 20, fmt_center) # Data
    worksheet.set_column('B:D', 10, fmt_center) # Par/Modo/Tipo
    worksheet.set_column('E:H', 14, fmt_num)    # Preços (Entrada/Saída/TP/SL)
    worksheet.set_column('I:I', 30)             # Critério (Largo)
    worksheet.set_column('J:J', 15, fmt_center) # Resultado
    worksheet.set_column('K:L', 18, fmt_money)  # Lucro e Saldo

    # Regras de Cor (Coluna K - Lucro)
    worksheet.conditional_format('K2:K1000', {'type': 'cell', 'criteria': '>', 'value': 0, 'format': fmt_green})
    worksheet.conditional_format('K2:K1000', {'type': 'cell', 'criteria': '<', 'value': 0, 'format': fmt_red})

    # --- 4. GRÁFICO DE LINHA (EVOLUÇÃO REAL) ---
    chart = workbook.add_chart({'type': 'line'})
    
    # Série: Saldo Acumulado
    chart.add_series({
        'name':       'Evolução da Banca',
        'categories': ['Extrato_Detalhado', 1, 0, len(df), 0], # Coluna A (Data)
        'values':     ['Extrato_Detalhado', 1, 11, len(df), 11], # Coluna L (Saldo Acumulado)
        'line':       {'color': '#2080D0', 'width': 2.5},
        'marker':     {'type': 'circle', 'size': 5, 'border': {'color': '#2080D0'}, 'fill': {'color': 'white'}}
    })

    chart.set_title({'name': 'Performance: Trades Fechados'})
    chart.set_y_axis({'name': 'Saldo da Banca ($)'})
    chart.set_size({'width': 800, 'height': 400})
    
    # Insere o gráfico ao lado da tabela
    worksheet.insert_chart('N2', chart)

    writer.close()
    print(f"📊 Relatório Gerado com Sucesso: {EXCEL_FILE}")
    print(f"✅ Processados {len(df)} trades do histórico.")

if __name__ == "__main__":
    gerar_relatorio()
    

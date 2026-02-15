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
EXCEL_FILE = "Relatorio_Oficial.xlsx" # NOME FINAL DO ARQUIVO
FUSO_BR = pytz.timezone('America/Sao_Paulo')

def gerar_relatorio():
    print("🔄 Gerando relatório...")
    
    if not os.path.exists(JSON_FILE):
        print(f"❌ Arquivo {JSON_FILE} não encontrado.")
        return

    with open(JSON_FILE, 'r') as f:
        data = json.load(f)

    # 1. LER DADOS DO HISTÓRICO (JSON)
    raw_trades = data.get("historico_trades", [])
    
    if not raw_trades:
        print("⚠️ Nenhum trade fechado para relatar.")
        return

    # 2. NORMALIZAR DADOS (Converter legado para novo)
    trades_processados = []
    
    # Adiciona saldo inicial (Linha 0 para o gráfico ficar bonito)
    banca_inicial = data.get("banca_inicial", 60.0)
    trades_processados.append({
        "Data": "Inicio",
        "Par": "-", "Modo": "Depósito", "Tipo": "-",
        "Entrada": 0, "Saida": 0, "TP": 0, "SL": 0,
        "Criterio": "-", "Resultado": "-",
        "Lucro ($)": 0.0,
        "Saldo Acumulado": banca_inicial
    })

    for t in raw_trades:
        # Lógica inteligente para pegar chaves novas OU antigas
        lucro_real = t.get("lucro_usd") if "lucro_usd" in t else t.get("lucro", 0.0)
        
        # Se tiver 'saldo_pos_trade', usa. Se não, calcula somando.
        if "saldo_pos_trade" in t:
            saldo_real = t.get("saldo_pos_trade")
        elif "saldo_final" in t:
            saldo_real = t.get("saldo_final")
        else:
            saldo_real = 0.0 # Fallback

        item = {
            "Data": t.get("data"),
            "Par": t.get("symbol"),
            "Modo": t.get("modo"),
            "Tipo": t.get("tipo", "N/A").upper(),
            "Entrada": t.get("entrada", 0.0),
            "Saida": t.get("saida", 0.0),
            "TP": t.get("tp", 0.0),
            "SL": t.get("sl", 0.0),
            "Criterio": t.get("criterio", "Trade Antigo"),
            "Resultado": t.get("resultado", ""),
            "Lucro ($)": float(lucro_real),
            "Saldo Acumulado": float(saldo_real)
        }
        trades_processados.append(item)

    df = pd.DataFrame(trades_processados)

    # 3. GERAR EXCEL
    writer = pd.ExcelWriter(EXCEL_FILE, engine='xlsxwriter')
    df.to_excel(writer, sheet_name='Relatorio_Trades', index=False)

    workbook = writer.book
    worksheet = writer.sheets['Relatorio_Trades']

    # 4. FORMATAÇÃO VISUAL
    fmt_money = workbook.add_format({'num_format': '$ #,##0.00'})
    fmt_num = workbook.add_format({'num_format': '#,##0.00'})
    fmt_center = workbook.add_format({'align': 'center'})
    fmt_header = workbook.add_format({'bold': True, 'bg_color': '#D3D3D3', 'border': 1})

    # Larguras
    worksheet.set_column('A:A', 20, fmt_center) # Data
    worksheet.set_column('B:D', 10, fmt_center) # Par/Modo/Tipo
    worksheet.set_column('E:H', 14, fmt_num)    # Preços
    worksheet.set_column('I:I', 35)             # Criterio (Largo)
    worksheet.set_column('J:J', 15, fmt_center) # Resultado
    worksheet.set_column('K:L', 18, fmt_money)  # Lucro e Saldo

    # Cores no Lucro (Verde/Vermelho)
    green = workbook.add_format({'bg_color': '#C6EFCE', 'font_color': '#006100'})
    red = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006'})
    worksheet.conditional_format('K2:K1000', {'type': 'cell', 'criteria': '>', 'value': 0, 'format': green})
    worksheet.conditional_format('K2:K1000', {'type': 'cell', 'criteria': '<', 'value': 0, 'format': red})

    # 5. GRÁFICO DE EVOLUÇÃO
    chart = workbook.add_chart({'type': 'line'})
    chart.add_series({
        'name':       'Evolução da Banca',
        'categories': ['Relatorio_Trades', 1, 0, len(df), 0], # Coluna A (Data)
        'values':     ['Relatorio_Trades', 1, 11, len(df), 11], # Coluna L (Saldo)
        'line':       {'color': '#2980B9', 'width': 2.5},
        'marker':     {'type': 'circle', 'size': 6}
    })
    chart.set_title({'name': 'Performance: Trades Realizados'})
    chart.set_y_axis({'name': 'Saldo ($)'})
    chart.set_size({'width': 800, 'height': 400})
    
    # Posiciona o gráfico ao lado da tabela (Coluna N)
    worksheet.insert_chart('N2', chart)

    writer.close()
    print(f"✅ SUCESSO! Relatório gerado: {EXCEL_FILE}")
    print(f"📊 Total de Trades Processados: {len(df)-1}")

if __name__ == "__main__":
    gerar_relatorio()
    

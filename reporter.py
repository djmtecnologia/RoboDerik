import json
import pandas as pd
import os
import sys
import subprocess
import pytz

# Auto-install dependencies
def install(package):
    try: __import__(package)
    except: subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", package])
for lib in ["pandas", "openpyxl", "xlsxwriter", "pytz"]: install(lib)

# CONFIGURAÇÃO
JSON_FILE = "estado_v164.json"
EXCEL_FILE = "Relatorio_Oficial.xlsx"

def gerar_relatorio():
    print("💎 Gerando Relatório V164 (Asymmetric Compounder)...")
    
    if not os.path.exists(JSON_FILE):
        print(f"❌ Arquivo {JSON_FILE} não encontrado. Rode o bot.py primeiro.")
        return

    try:
        with open(JSON_FILE, 'r') as f: data = json.load(f)
    except Exception as e:
        print(f"❌ Erro ao ler JSON: {e}")
        return

    raw_trades = data.get("historico_trades", [])
    trades_processados = []

    # Saldo Inicial (Linha 0)
    banca_atual = data.get("banca_atual", 60.0)
    # Tenta estimar o saldo inicial subtraindo os lucros, ou usa 60.0 fixo
    saldo_acumulado = 60.0 
    
    trades_processados.append({
        "Data": "INICIO", 
        "Par": "-", 
        "Estratégia": "Depósito", 
        "Lado": "-",
        "Macro": "-", 
        "Adds": 0, 
        "Motivo": "Saldo Inicial", 
        "Lucro ($)": 0.0,
        "Saldo ($)": saldo_acumulado
    })

    # Processa cada trade
    for t in raw_trades:
        lucro = t.get("lucro", 0.0)
        saldo_acumulado += lucro
        
        item = {
            "Data": t.get("data"),
            "Par": t.get("symbol"),
            "Estratégia": t.get("strat", "N/A"),  # TREND ou TRAP
            "Lado": t.get("side", "N/A").upper(), # BUY ou SELL
            "Macro": t.get("macro", "-"),         # SUMMER ou WINTER (Se disponível no histórico)
            "Adds": t.get("adds", 0),             # Quantas vezes piramidou
            "Motivo": t.get("motivo", ""),        # TP Deep Trend, TP Fast, SL, etc.
            "Lucro ($)": float(lucro),
            "Saldo ($)": float(saldo_acumulado)
        }
        trades_processados.append(item)

    # Cria DataFrame
    df = pd.DataFrame(trades_processados)
    
    # GERAR EXCEL COM FORMATAÇÃO
    writer = pd.ExcelWriter(EXCEL_FILE, engine='xlsxwriter')
    df.to_excel(writer, sheet_name='Trades_V164', index=False)
    
    workbook = writer.book
    worksheet = writer.sheets['Trades_V164']
    
    # Formatos
    fmt_money = workbook.add_format({'num_format': '$ #,##0.00'})
    fmt_center = workbook.add_format({'align': 'center'})
    fmt_header = workbook.add_format({'bold': True, 'align': 'center', 'bg_color': '#D7E4BC'})
    
    # Cores Condicionais (Verde/Vermelho)
    fmt_green = workbook.add_format({'bg_color': '#C6EFCE', 'font_color': '#006100'})
    fmt_red = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006'})

    # Aplicar Formatação
    worksheet.set_column('A:A', 20, fmt_center) # Data
    worksheet.set_column('B:D', 12, fmt_center) # Par/Estrat/Lado
    worksheet.set_column('E:F', 10, fmt_center) # Macro/Adds
    worksheet.set_column('G:G', 30)             # Motivo
    worksheet.set_column('H:I', 15, fmt_money)  # Lucro e Saldo

    # Condicional no Lucro (Coluna H)
    worksheet.conditional_format('H2:H1000', {'type': 'cell', 'criteria': '>', 'value': 0, 'format': fmt_green})
    worksheet.conditional_format('H2:H1000', {'type': 'cell', 'criteria': '<', 'value': 0, 'format': fmt_red})

    # GRÁFICO DE EVOLUÇÃO
    chart = workbook.add_chart({'type': 'line'})
    chart.add_series({
        'name':       'Evolução da Banca',
        'categories': ['Trades_V164', 1, 0, len(df), 0], # Datas
        'values':     ['Trades_V164', 1, 8, len(df), 8], # Saldo (Coluna I = índice 8)
        'line':       {'color': '#2980B9', 'width': 2.5}
    })
    chart.set_title({'name': 'Performance V164 - Asymmetric Compounder'})
    chart.set_size({'width': 800, 'height': 400})
    worksheet.insert_chart('K2', chart)
    
    writer.close()
    print(f"✅ Relatório Oficial Gerado: {EXCEL_FILE}")

if __name__ == "__main__":
    gerar_relatorio()
    

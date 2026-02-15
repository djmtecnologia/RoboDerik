import json
import pandas as pd
import os
import sys
import subprocess
import pytz

def install(package):
    try: __import__(package)
    except: subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", package])
for lib in ["pandas", "openpyxl", "xlsxwriter", "pytz"]: install(lib)

JSON_FILE = "estado.json"
EXCEL_FILE = "Relatorio_Oficial.xlsx"

def gerar_relatorio():
    print("🔄 Gerando relatório V80...")
    
    if not os.path.exists(JSON_FILE):
        print(f"❌ Arquivo {JSON_FILE} não encontrado.")
        return

    with open(JSON_FILE, 'r') as f: data = json.load(f)

    raw_trades = data.get("historico_trades", [])
    trades_processados = []

    # Saldo Inicial
    trades_processados.append({
        "Data": "Inicio", "Par": "-", "Modo": "Depósito", "Tipo": "-",
        "Nível": "-", "Fator": "-", "% Banca": "-", # <--- Colunas Novas
        "Investido ($)": 0, "Entrada": 0, "Saida": 0, "TP": 0, "SL": 0,
        "Criterio": "-", "Resultado": "-", "Lucro ($)": 0.0,
        "Saldo Acumulado": data.get("banca_inicial", 60.0)
    })

    for t in raw_trades:
        lucro_real = t.get("lucro_usd") if "lucro_usd" in t else t.get("lucro", 0.0)
        saldo_real = t.get("saldo_pos_trade") if "saldo_pos_trade" in t else t.get("saldo_final", 0.0)
        
        # Recupera dados novos
        nivel_mg = t.get("nivel_mg", 0)
        fator_mg = t.get("fator_mg", 1.0) # <--- RECUPERA FATOR
        perc_banca = t.get("perc_banca", 0.0)
        
        item = {
            "Data": t.get("data"),
            "Par": t.get("symbol"),
            "Modo": t.get("modo"),
            "Tipo": t.get("tipo", "N/A").upper(),
            "Nível": nivel_mg,                # Coluna Nova
            "Fator": f"{fator_mg}x",          # Coluna Nova (ex: 1.5x)
            "% Banca": f"{perc_banca}%",      # Coluna Nova
            "Investido ($)": t.get("investido", 0.0),
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
    
    # GERAR EXCEL
    writer = pd.ExcelWriter(EXCEL_FILE, engine='xlsxwriter')
    df.to_excel(writer, sheet_name='Relatorio_Trades', index=False)
    
    workbook = writer.book
    worksheet = writer.sheets['Relatorio_Trades']
    
    # FORMATAÇÃO
    fmt_money = workbook.add_format({'num_format': '$ #,##0.00'})
    fmt_center = workbook.add_format({'align': 'center'})
    
    # Ajuste de Larguras
    worksheet.set_column('A:A', 20, fmt_center) # Data
    worksheet.set_column('B:D', 10, fmt_center) # Par/Modo/Tipo
    worksheet.set_column('E:G', 8, fmt_center)  # Nivel, Fator, % (Estreitos)
    worksheet.set_column('H:H', 14, fmt_money)  # Investido
    worksheet.set_column('I:L', 14, fmt_center) # Preços
    worksheet.set_column('M:M', 35)             # Criterio
    worksheet.set_column('N:O', 16, fmt_money)  # Lucro e Saldo

    # Cores no Lucro
    green = workbook.add_format({'bg_color': '#C6EFCE', 'font_color': '#006100'})
    red = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006'})
    worksheet.conditional_format('N2:N1000', {'type': 'cell', 'criteria': '>', 'value': 0, 'format': green})
    worksheet.conditional_format('N2:N1000', {'type': 'cell', 'criteria': '<', 'value': 0, 'format': red})

    # GRÁFICO
    chart = workbook.add_chart({'type': 'line'})
    chart.add_series({
        'name': 'Evolução da Banca',
        'categories': ['Relatorio_Trades', 1, 0, len(df), 0],
        'values':     ['Relatorio_Trades', 1, 15, len(df), 15], # Coluna P (Saldo)
        'line':       {'color': '#2980B9', 'width': 2.5}
    })
    worksheet.insert_chart('Q2', chart)
    
    writer.close()
    print(f"✅ Relatório V80 Gerado: {EXCEL_FILE}")

if __name__ == "__main__":
    gerar_relatorio()
    

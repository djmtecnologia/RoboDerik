import json
import pandas as pd
import os
from datetime import datetime
import sys
import subprocess

# --- AUTO-INSTALAÇÃO DAS LIBS DE RELATÓRIO ---
def install(package):
    try:
        __import__(package)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", package])

for lib in ["pandas", "openpyxl", "xlsxwriter"]:
    install(lib)

# --- CONFIGURAÇÕES ---
JSON_FILE = "estado.json"
CSV_FILE = "historico_trades.csv"
EXCEL_FILE = "Relatorio_RoboDerik_V70.xlsx"

def gerar_relatorio():
    # 1. Ler o Estado Atual
    if not os.path.exists(JSON_FILE):
        print(f"❌ Arquivo {JSON_FILE} não encontrado. Rode o bot primeiro.")
        return

    with open(JSON_FILE, 'r') as f:
        data = json.load(f)

    # 2. Preparar os Dados para o Histórico
    # Se houver posição aberta, calculamos o valor investido, senão é 0
    investido = data.get("posicao_aberta", {}).get("valor_investido", 0) if data.get("posicao_aberta") else 0
    
    novo_registro = {
        "Data": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "Banca Total ($)": round(data.get("banca_atual", 60.0), 2),
        "Investido ($)": round(investido, 2),
        "Livre ($)": round(data.get("banca_atual", 60.0) - investido, 2),
        "PnL Hoje ($)": round(data.get("pnl_hoje", 0.0), 2),
        "Trades Hoje": data.get("trades_hoje", 0),
        "Modo": data.get("posicao_aberta", {}).get("modo", "AGUARDANDO") if data.get("posicao_aberta") else "LIQUIDO"
    }

    # 3. Atualizar o CSV (Banco de Dados)
    if os.path.exists(CSV_FILE):
        df = pd.read_csv(CSV_FILE)
        # Evita duplicatas exatas no mesmo minuto
        ultima_data = df.iloc[-1]["Data"] if not df.empty else ""
        if ultima_data != novo_registro["Data"]:
            df = pd.concat([df, pd.DataFrame([novo_registro])], ignore_index=True)
    else:
        # Se é a primeira vez, cria o arquivo e adiciona o saldo inicial para o gráfico ficar bonito
        registro_inicial = novo_registro.copy()
        registro_inicial["Data"] = "Inicio"
        registro_inicial["Banca Total ($)"] = data.get("banca_inicial", 60.0)
        registro_inicial["PnL Hoje ($)"] = 0.0
        registro_inicial["Modo"] = "INICIO"
        
        df = pd.DataFrame([registro_inicial, novo_registro])

    df.to_csv(CSV_FILE, index=False)
    print(f"✅ Histórico atualizado em {CSV_FILE}")

    # 4. Gerar o Excel com Gráficos (A Mágica)
    writer = pd.ExcelWriter(EXCEL_FILE, engine='xlsxwriter')
    df.to_excel(writer, sheet_name='Performance', index=False)

    workbook = writer.book
    worksheet = writer.sheets['Performance']

    # Formatação Bonita
    formato_dinheiro = workbook.add_format({'num_format': '$ #,##0.00'})
    formato_verde = workbook.add_format({'bg_color': '#C6EFCE', 'font_color': '#006100'})
    formato_vermelho = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006'})

    # Aplica formato de dinheiro nas colunas B, C, D, E
    worksheet.set_column('B:E', 15, formato_dinheiro)
    worksheet.set_column('A:A', 20) # Coluna Data mais larga

    # Regra Condicional para o PnL (Verde se positivo, Vermelho se negativo)
    worksheet.conditional_format('E2:E1000', {'type': 'cell', 'criteria': '>', 'value': 0, 'format': formato_verde})
    worksheet.conditional_format('E2:E1000', {'type': 'cell', 'criteria': '<', 'value': 0, 'format': formato_vermelho})

    # --- GRÁFICO 1: EVOLUÇÃO DA BANCA (LINHA) ---
    chart_banca = workbook.add_chart({'type': 'line'})
    chart_banca.add_series({
        'name':       'Evolução da Banca',
        'categories': ['Performance', 1, 0, len(df), 0], # Coluna Data
        'values':     ['Performance', 1, 1, len(df), 1], # Coluna Banca Total
        'line':       {'color': 'blue', 'width': 2.5},
        'marker':     {'type': 'circle', 'size': 5}
    })
    chart_banca.set_title({'name': 'Crescimento do Patrimônio (Juros Compostos)'})
    chart_banca.set_y_axis({'name': 'Valor em USD'})
    chart_banca.set_style(10)
    worksheet.insert_chart('H2', chart_banca)

    # --- GRÁFICO 2: LUCRO DIÁRIO (COLUNAS) ---
    chart_pnl = workbook.add_chart({'type': 'column'})
    chart_pnl.add_series({
        'name':       'Lucro/Prejuízo Diário',
        'categories': ['Performance', 1, 0, len(df), 0],
        'values':     ['Performance', 1, 4, len(df), 4], # Coluna PnL
        'fill':       {'color': '#50C878'},
        'border':     {'color': 'black'}
    })
    chart_pnl.set_title({'name': 'Performance Diária'})
    chart_pnl.set_y_axis({'name': 'Lucro em USD'})
    worksheet.insert_chart('H18', chart_pnl)

    writer.close()
    print(f"📊 Relatório Gráfico gerado com sucesso: {EXCEL_FILE}")
    print("👉 Abra o arquivo Excel para mostrar aos seus amigos!")

if __name__ == "__main__":
    gerar_relatorio()


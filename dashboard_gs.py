import streamlit as st
from streamlit_autorefresh import st_autorefresh
import pandas as pd
from datetime import datetime, time as dtime
from ta.momentum import RSIIndicator
import time
from st_aggrid import AgGrid, GridOptionsBuilder
import requests
import json
import os
from apscheduler.schedulers.background import BackgroundScheduler
import logging
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from gspread.exceptions import SpreadsheetNotFound, WorksheetNotFound
import json
from io import BytesIO
from PIL import Image
import pytz
import stat
import shutil


# 🚀 Configuração da Página
st.set_page_config(page_title="Dashboard", layout="wide")

# 🔐 Pega a chave privada do secrets
private_key = st.secrets["ssh"]["private_key"]

# 📂 Cria o diretório SSH se não existir
os.makedirs(os.path.expanduser('~/.ssh'), exist_ok=True)

# 💾 Salva a chave privada no arquivo correto
private_key_path = os.path.expanduser('~/.ssh/id_rsa')
with open(private_key_path, 'w') as file:
    file.write(private_key)

# 🔒 Define permissões corretas
os.system('chmod 600 ~/.ssh/id_rsa')
os.system('chmod 700 ~/.ssh')
os.system('ssh-keyscan github.com >> ~/.ssh/known_hosts')

# 🔄 Adicionar fingerprint do GitHub aos hosts conhecidos
os.system('ssh-keyscan -H github.com >> ~/.ssh/known_hosts')

# 🚀 Verificação da criação da chave
if not os.path.exists(os.path.expanduser('~/.ssh/id_rsa')):
    st.error("❌ A chave SSH não foi criada corretamente no diretório ~/.ssh/")
else:
    st.success("✅ Chave SSH criada com sucesso.")

# 🔄 Inicia o agente SSH explicitamente
start_agent = os.popen("ssh-agent -s").read()
st.write(f"🔄 Agente SSH iniciado:\n{start_agent}")

# 🗝️ Extraímos o PID e o socket manualmente:
agent_lines = start_agent.split("\n")
for line in agent_lines:
    if "SSH_AUTH_SOCK" in line:
        sock = line.split(";")[0].replace("SSH_AUTH_SOCK=", "")
        os.environ["SSH_AUTH_SOCK"] = sock
        st.write(f"🔗 SSH_AUTH_SOCK definido: {sock}")
    elif "SSH_AGENT_PID" in line:
        pid = line.split(";")[0].replace("SSH_AGENT_PID=", "")
        os.environ["SSH_AGENT_PID"] = pid
        st.write(f"🔗 SSH_AGENT_PID definido: {pid}")

# 🔓 Adiciona a chave ao agente
response = os.system(f'ssh-add ~/.ssh/id_rsa')
if response == 0:
    st.success("✅ Chave SSH carregada no agente com sucesso!")
else:
    st.error("❌ Erro ao carregar a chave SSH no agente.")

# 🔄 Testando conexão SSH com GitHub...
st.write("🔄 Testando conexão SSH com GitHub...")
response = os.system(f'ssh -o StrictHostKeyChecking=no -T git@github.com')
if response == 0:
    st.success("✅ Conexão SSH com GitHub está funcionando.")
else:
    st.error("❌ Erro na conexão SSH com GitHub. Verifique permissões e Deploy Key.")
    st.write("🔍 **Log Detalhado:**")
    st.write(os.popen("ssh -vT git@github.com").read())

# 🔍 Chaves carregadas no agente:
st.write("🔍 Chaves carregadas no agente:")
st.write(os.popen("ssh-add -l").read())

# 🔍 Verificando socket do SSH_AGENT:
st.write("🔍 Verificando socket do SSH_AGENT:")
st.write(os.popen('ls -l $SSH_AUTH_SOCK').read())

# 🔄 Adicionar configuração no SSH para garantir o IdentityFile correto
config_path = os.path.expanduser('~/.ssh/config')
with open(config_path, 'w') as file:
    file.write("""
Host github.com
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_rsa
    StrictHostKeyChecking no
""")

os.system('chmod 600 ~/.ssh/config')

def remove_readonly(func, path, _):
    """ Tenta remover a permissão de somente leitura e apaga o arquivo. """
    os.chmod(path, stat.S_IWRITE)
    func(path)

# 🚀 Verifica se o diretório existe
if os.path.exists("gpanel"):
    st.info("📁 Removendo repositório antigo para forçar um clone novo.")
    try:
        shutil.rmtree("gpanel", onerror=remove_readonly)
        st.success("✅ Repositório removido com sucesso.")
    except Exception as e:
        st.error(f"❌ Falha ao remover o repositório: {e}")

# 🔄 Clona novamente
st.write("🔄 Clonando repositório privado do GitHub...")
response = os.system('git clone --progress --verbose git@github.com:eduardohem/gpanel.git gpanel')
if response == 0:
    st.success("✅ Repositório clonado com sucesso!")
else:
    st.error("❌ Falha ao clonar o repositório. Verifique permissões.")

# ✅ Teste de escrita
if os.path.exists("gpanel"):
    try:
        with open("gpanel/test_write.txt", "w") as f:
            f.write("Teste de escrita bem-sucedido.")
        st.success("✅ Permissão de escrita confirmada!")
    except Exception as e:
        st.error(f"❌ Sem permissão de escrita: {e}")




# Recarrega a cada n minutos (300.000 ms)
n = 10
st_autorefresh(interval=n * 60 * 1000, key="auto-refresh")

fuso_sp = pytz.timezone("America/Sao_Paulo")

# Autenticação
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["google"], scope)
client = gspread.authorize(creds)

@st.cache_data(ttl=60)
def get_btc_data_from_sheet():
    try:
        # Tenta abrir a planilha
        sh = client.open("streamlit2")
    except SpreadsheetNotFound:
        st.error("❗Planilha 'streamlit2' não encontrada.")
        return pd.DataFrame()

    try:
        # Tenta abrir a aba "Cripto"
        sheet = sh.worksheet("Cripto")
    except WorksheetNotFound:
        st.error("❗Aba 'Cripto' não encontrada na planilha.")
        return pd.DataFrame()

    dados = sheet.get_all_values()

    if not dados or len(dados) < 2:
        st.error("❗Aba 'Cripto' vazia ou mal formatada.")
        return pd.DataFrame()

    # Converter para DataFrame
    df = pd.DataFrame(dados[1:], columns=dados[0])

    # Converter colunas
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")

    # Definir timestamp como índice
    df.set_index("timestamp", inplace=True)

    return df

@st.cache_data(ttl=60)
def carregar_dados_da_planilha():
    """
    Lê dados dos títulos e metadados da planilha 'streamlit2'.
    Retorna um dicionário com os dados no formato original do JSON.
    """

    try:
        # Verifica se a planilha existe
        planilha = client.open("streamlit2")
    except SpreadsheetNotFound:
        st.error("❗Planilha 'streamlit2' não encontrada.")
        return None

    try:
        # Tenta carregar os dados da aba "Tesouro"
        sheet = planilha.worksheet("Tesouro")
        df = pd.DataFrame(sheet.get_all_records())
    except WorksheetNotFound:
        st.error("❗Aba 'Tesouro' não encontrada na planilha.")
        return None

    # Tenta carregar os metadados
    try:
        meta = planilha.worksheet("Metadados")
        ultima_atualizacao = meta.acell("B1").value
        estado_mercado = meta.acell("B2").value
        fear_val = meta.acell("B3").value
        fear_cls = meta.acell("B4").value
        ultima_atualizacao_cripto = meta.acell("B5").value
    except WorksheetNotFound:
        ultima_atualizacao = "desconhecida"
        estado_mercado = "indisponível"
        fear_val = "?"
        fear_cls = "?"
        ultima_atualizacao_cripto = "desconhecida"

    return {
        "dados": df.to_dict(orient="records"),
        "ultima_atualizacao": ultima_atualizacao,
        "estado_mercado": estado_mercado,
        "fear_val": fear_val,
        "fear_cls": fear_cls,
        "ultima_atualizacao_cripto": ultima_atualizacao_cripto
    }

st.markdown("<h1 style='font-size:25px; font-weight:bold;'>📊 Brasil</h1>", unsafe_allow_html=True)

# Código do widget watch
widget_html = """
<!-- TradingView Widget BEGIN -->
<div class="tradingview-widget-container">
  <div class="tradingview-widget-container__widget"></div>
  <div class="tradingview-widget-copyright">
    <a href="https://br.tradingview.com/" rel="noopener nofollow" target="_blank">
      <span class="blue-text">Monitore todos os mercados no TradingView</span>
    </a>
  </div>
  <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-market-quotes.js" async>
  {
    "width": "100%",
    "height": 300,
    "symbolsGroups": [
      {
        "name": "Indices",
        "originalName": "Indices",
        "symbols": [
          { "name": "FX_IDC:USDBRL", "displayName": "USD / BRL" },
          { "name": "BMFBOVESPA:PETR4", "displayName": "Petrobras" },
          { "name": "BMFBOVESPA:BBAS3", "displayName": "Banco do Brasil" },
          { "name": "BMFBOVESPA:VALE3", "displayName": "Vale" },
          { "name": "BMFBOVESPA:IBOV", "displayName": "IBOVESPA" }
        ]
      }
    ],
    "showSymbolLogo": true,
    "isTransparent": false,
    "colorTheme": "light",
    "locale": "br",
    "backgroundColor": "#ffffff"
  }
  </script>
</div>
<!-- TradingView Widget END -->
"""
st.components.v1.html(widget_html, height=300)

# divisória horizontal
st.markdown("""
<hr style="border: 1px solid #ccc; margin-top: 20px; margin-bottom: 20px;">
""", unsafe_allow_html=True)

st.markdown("<h1 style='font-size:25px; font-weight:bold;'>📊 Exterior e commodities</h1>", unsafe_allow_html=True)

# Código do widget watch
widget_html = """
<!-- TradingView Widget BEGIN -->
<div class="tradingview-widget-container">
  <div class="tradingview-widget-container__widget"></div>
  <div class="tradingview-widget-copyright">
    <a href="https://br.tradingview.com/" rel="noopener nofollow" target="_blank">
      <span class="blue-text">Monitore todos os mercados no TradingView</span>
    </a>
  </div>
  <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-market-quotes.js" async>
  {
    "width": "100%",
    "height": 400,
    "symbolsGroups": [
      {
        "name": "Indices",
        "originalName": "Indices",
        "symbols": [
          { "name": "BINANCE:BTCUSD", "displayName": "BTC / USD" },
          { "name": "AMEX:SCHD", "displayName": "Schwab US Dividend" }, 
          { "name": "NASDAQ:TLT", "displayName": "Ishares 20+ Year Treasury" },
          { "name": "TVC:GOLD", "displayName": "Ouro (OZ/USD)" },
          { "name": "BLACKBULL:BRENT", "displayName": "Petróleo (Brent)" },
          { "name": "TVC:SILVER", "displayName": "Prata (OZ/USD)" },
          { "name": "CMCMARKETS:EURUSD", "displayName": "EUR / USD" },
          { "name": "CAPITALCOM:DXY", "displayName": "USD / DXY" }
        ]
      }
    ],
    "showSymbolLogo": true,
    "isTransparent": false,
    "colorTheme": "light",
    "locale": "br",
    "backgroundColor": "#ffffff"
  }
  </script>
</div>
<!-- TradingView Widget END -->
"""
st.components.v1.html(widget_html, height=400)

# divisória horizontal
st.markdown("""
<hr style="border: 1px solid #ccc; margin-top: 20px; margin-bottom: 20px;">
""", unsafe_allow_html=True)

# Função para configurar e exibir AgGrid com altura dinâmica e cabeçalho centralizado
def configurar_aggrid(df):

    df.columns = ['📜 TÍTULO', '📈 RENTABILIDADE (%)', '💰 PREÇO UNITÁRIO (R$)', '📅 VENCIMENTO']

    gb = GridOptionsBuilder.from_dataframe(df)

    for col in df.columns:
        gb.configure_column(
            col,
            headerClass='grid-header-center',
            cellStyle={'justifyContent': 'center', 'display': 'flex', 'font-size': '17px'},
            headerStyle={'justifyContent': 'center', 'display': 'flex'},
            flex=1
        )

    grid_options = gb.build()

    st.markdown("""
        <style>
        .ag-header-cell.grid-header-center { /* Adicionando .ag-header-cell para mais especificidade */
            display: flex !important;
            justify-content: center !important;
            align-items: center !important;
        }
        /* Mantenha os outros estilos abaixo */
        .ag-root-wrapper {
            width: 100% !important;
        }
        .ag-cell, .ag-header-cell {
            border-width: 1px !important;
            border-color: #ccc !important;
            border-style: solid !important;
        }
        .ag-theme-streamlit {
            border: none !important;
        }
        .ag-cell {
            display: flex;
            justify-content: center !important;
            align-items: center !important;
        }
        </style>
    """, unsafe_allow_html=True)

    linhas = len(df)
    altura = linhas * 45 - linhas ** 2  # altura ideal para caber todas as linhas sem scroll

    AgGrid(
        df,
        gridOptions=grid_options,
        height=altura,
        fit_columns_on_grid_load=True,
        use_container_width=True)

df_btc = get_btc_data_from_sheet()

if df_btc.empty or "close" not in df_btc.columns:
    st.warning("⚠️ Dados de BTC indisponíveis ou mal formatados.")
    price = 0
    rsi_val = 0
    rsi = pd.Series(dtype=float)
else:
    rsi = RSIIndicator(close=df_btc["close"], window=14).rsi()
    price = df_btc["close"].iloc[-1]
    rsi_val = rsi.iloc[-1]

# — Alertas de venda —
st.markdown("<div style='margin-top:2px'></div>", unsafe_allow_html=True)

dados_cache = carregar_dados_da_planilha()
if dados_cache:
    df_tesouro = pd.DataFrame(dados_cache["dados"])
    estado_mercado = dados_cache["estado_mercado"]
    ts_titulos = datetime.strptime(dados_cache["ultima_atualizacao"], "%d/%m/%Y %H:%M")
    fear_val = dados_cache["fear_val"],
    fear_cls = dados_cache["fear_cls"],
    ultima_atualizacao_cripto = datetime.strptime(dados_cache["ultima_atualizacao_cripto"], "%d/%m/%Y %H:%M")
else:
    df_tesouro = pd.DataFrame()
    estado_mercado = "Indefinido"
    ts_titulos = datetime.now(fuso_sp).strftime("%d/%m/%Y %H:%M")
    fear_val = 0
    fear_cls = 'Indefinido'
    ultima_atualizacao_cripto = datetime.now(fuso_sp).strftime("%d/%m/%Y %H:%M")

n1, n2, n3 = 62, 70, 75  # níveis de RSI para venda
fg_threshold = 75  # nível de F&G para reforçar o sinal mais forte

if rsi_val > n3 and fear_val[0] >= fg_threshold:
    st.error(f"🚨 RSI > {n3} → Venda 15% da posição  |  F&G: {fear_val[0]} ({fear_cls[0]})")
elif rsi_val > n2:
    st.warning(f"⚠️ RSI > {n2} → Venda 10% da posição  |  F&G: {fear_val[0]} ({fear_cls[0]})")
elif rsi_val > n1:
    st.info(f"ℹ️ RSI > {n1} → Venda 5% da posição  |  F&G: {fear_val[0]} ({fear_cls[0]})")
else:
    st.success(f"✅ Mercado em equilíbrio&nbsp;&nbsp;|&nbsp;&nbsp;RSI: {rsi_val:.2f}&nbsp;&nbsp;|&nbsp;&nbsp;F&G: {fear_val[0]} ({fear_cls[0]})")

# agora, criamos 3 colunas:
spacer0, col1, spacer1, col2, spacer2, col3, spacer3 = st.columns([0.3, 3.8, 0.1, 3.8, 0.1, 2.2, 0.1])
height = 180

if not df_btc.empty:
    with col1:
        # st.markdown("<div style='margin-top:10px'></div>", unsafe_allow_html=True)
        st.markdown(f"<h1 style='font-size:23px; font-weight:bold;'>Preço BTC/USDT: ${price:,.2f}</h1>", unsafe_allow_html=True)
        st.line_chart(df_btc["close"], height=height, use_container_width=True)

    with col2:
        if isinstance(rsi, pd.Series) and not rsi.empty:
            st.markdown(f"<h1 style='font-size:23px; font-weight:bold;'>RSI (14d): {rsi_val:.2f}</h1>", unsafe_allow_html=True)
            st.line_chart(rsi, height=height, use_container_width=True)

    with col3:
        # st.markdown("<div style='margin-top:5px'></div>", unsafe_allow_html=True)
        st.image(
            "https://alternative.me/crypto/fear-and-greed-index.png",
            # use_container_width=True,
            width=220,
            caption="Fear & Greed Index (Alternative.me)")

widget_html = """
<!-- TradingView Widget BEGIN -->
<div class="tradingview-widget-container" style="width: 100%; height: 600px;">
  <div class="tradingview-widget-container__widget" style="width: 100%; height: 100%;"></div>
  <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js" async>
  {
    "width": "100%",
    "height": 600,
    "symbol": "BINANCE:BTCUSD",
    "interval": "D",
    "timezone": "Etc/UTC",
    "theme": "light",
    "style": "1",
    "locale": "br",
    "allow_symbol_change": true,
    "support_host": "https://www.tradingview.com"
  }
  </script>
</div>
<!-- TradingView Widget END -->
"""

# Expander com altura compatível (mesmo valor!)
with st.expander("Ver Gráfico"):
    st.components.v1.html(widget_html, height=620)  # altura externa um pouco maior


# Mostra a hora da última atualização no canto superior direito
now = datetime.now(fuso_sp).strftime("%d/%m/%Y %H:%M")
if isinstance(ultima_atualizacao_cripto, datetime):
    ts_str = ultima_atualizacao_cripto.strftime("%d/%m/%Y %H:%M")
else:
    ts_str = str(ultima_atualizacao_cripto)

st.markdown(f"""*Fonte: [Binance](https://www.binance.com/pt-BR/markets/overview) em {ts_str}*""")


# divisória horizontal
st.markdown("""<hr style="border: 1px solid #ccc; margin-top: 20px; margin-bottom: 20px;">""", unsafe_allow_html=True)


# Verifica se a coluna Vencimento existe e é válida antes de converter datas
if not df_tesouro.empty and 'Vencimento' in df_tesouro.columns:
    df_tesouro['Vencimento'] = pd.to_datetime(df_tesouro['Vencimento'], dayfirst=True, errors='coerce')
    df_tesouro['Vencimento'] = df_tesouro['Vencimento'].dt.strftime('%d/%m/%Y')

st.markdown(f"""
    <div style="display: flex; align-items: center;">
        <h1 style="margin: 0; font-size: 29px;">Tesouro Direto</h1>
        <span style="font-size: 15px; display: flex;">{estado_mercado}
        </span>
    </div>
""", unsafe_allow_html=True)

if not df_tesouro.empty and 'Título' in df_tesouro.columns:

    # Converte a coluna 'Título' para minúsculas para facilitar a filtragem
    df_tesouro["Título"] = df_tesouro["Título"].astype(str)

    # Categorias e condições para filtragem
    categorias = {
        "PREFIXADO": lambda t: "prefixado" in t,
        "SELIC": lambda t: "selic" in t,
        "IPCA+": lambda t: "ipca" in t and "juros" not in t,
        "IPCA+ Juros": lambda t: "ipca" in t and "juros" in t,
        "APOSENTADORIA": lambda t: "aposentadoria" in t,
        "EDUCA": lambda t: "educa" in t,
    }

    # Definindo categorias que devem estar marcadas por padrão
    marcadas_por_padrao = {"PREFIXADO", "IPCA+"}  # "SELIC"

    # Interface para seleção de filtros
    filtros_ativos = []
    cols = st.columns(len(categorias))
    for i, (label, cond) in enumerate(categorias.items()):
        valor_inicial = label in marcadas_por_padrao
        if cols[i].checkbox(label, value=valor_inicial):
            filtros_ativos.append(cond)

    # Aplicar filtros aos títulos
    if filtros_ativos:
        df_tesouro = df_tesouro[
            df_tesouro["Título"].str.lower().apply(
                lambda titulo: any(cond(titulo) for cond in filtros_ativos)
            )
        ]
    else:
        st.warning("Nenhum filtro selecionado. Nenhum título será exibido.")
        df_tesouro = pd.DataFrame()

if not df_tesouro.empty:
    configurar_aggrid(df_tesouro)
else:
    st.warning("Nenhum dado encontrado.")
    st.warning("Aguarde a primeira coleta pelo agendador ou verifique se o Selenium está configurado corretamente.")

if isinstance(ts_titulos, datetime):
    ts_tesouro_str = ts_titulos.strftime('%d/%m/%Y %H:%M')
else:
    ts_tesouro_str = str(ts_titulos)
st.markdown(f"""*Fonte: [Tesouro Direto](https://www.tesourodireto.com.br/titulos/precos-e-taxas.htm) em {ts_tesouro_str}*""")

# divisória horizontal
st.markdown("""
<hr style="border: 1px solid #ccc; margin-top: 20px; margin-bottom: 20px;">
""", unsafe_allow_html=True)

widget_html = """
<!-- TradingView Widget BEGIN -->
<div class="tradingview-widget-container">
  <div class="tradingview-widget-container__widget"></div>
  <div class="tradingview-widget-copyright"><a href="https://br.tradingview.com/" rel="noopener nofollow" target="_blank"><span class="blue-text">Monitore todos os mercados no TradingView</span></a></div>
  <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-stock-heatmap.js" async>
  {
  "exchanges": [],
  "dataSource": "SPX500",
  "grouping": "sector",
  "blockSize": "market_cap_basic",
  "blockColor": "change",
  "locale": "br",
  "symbolUrl": "",
  "colorTheme": "light",
  "hasTopBar": false,
  "isDataSetEnabled": false,
  "isZoomEnabled": false,
  "hasSymbolTooltip": true,
  "isMonoSize": false,
  "width": "100%",
  "height": 650
}
  </script>
</div>
<!-- TradingView Widget END -->
"""
st.components.v1.html(widget_html, height=650)

# Botão para limpar todos os caches do Streamlit
if st.button("🧹 Limpar cache Streamlit"):
    st.cache_data.clear()       # limpa @st.cache_data
    st.cache_resource.clear()   # limpa @st.cache_resource
    st.success("Cache limpo com sucesso!")



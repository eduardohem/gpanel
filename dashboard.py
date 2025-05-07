import streamlit as st
from streamlit_autorefresh import st_autorefresh
import pandas as pd
from datetime import datetime, time as dtime
from ta.momentum import RSIIndicator
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.common.exceptions import WebDriverException
import time
from st_aggrid import AgGrid, GridOptionsBuilder
import requests
import json
import os
from apscheduler.schedulers.background import BackgroundScheduler
from threading import Lock
import logging

logger = logging.getLogger(__name__)
if not logger.hasHandlers():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s")
logger.info("Script carregado")


st.set_page_config(page_title="Dashboard", layout="wide")

# Recarrega a cada 5 minutos (300.000 ms)
st_autorefresh(interval=300 * 1000, key="auto-refresh")

lock = Lock()

# Dados globais usados pelo scheduler
DADOS_TESOURO = {
    "dados": [],
    "ultima_atualizacao": None,
    "estado_mercado": "Desconhecido"
}

def get_btc_data(symbol="BTCUSDT", interval="1d", limit=100):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    data = requests.get(url, params=params).json()
    df = pd.DataFrame(data, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "trades",
        "taker_base_vol", "taker_quote_vol", "ignore"
    ])
    df["close"] = df["close"].astype(float)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    return df

def get_fear_and_greed():
    resp = requests.get("https://api.alternative.me/fng/").json()
    val = int(resp["data"][0]["value"])
    cls = resp["data"][0]["value_classification"]
    return val, cls

@st.cache_data(ttl=1140)
def obter_tesouro_titulos():
    options = FirefoxOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')

    try:
        logger.info("Iniciando o driver Firefox...")

        if os.name == 'nt':
            options.binary_location = r"C:\Program Files\Mozilla Firefox\firefox.exe"
            driver_path = os.path.join(os.path.dirname(__file__), "geckodriver.exe")
        else:
            driver_path = "/usr/local/bin/geckodriver"

        service = FirefoxService(executable_path=driver_path)
        driver = webdriver.Firefox(service=service, options=options)
        logger.info("Firefox iniciado com sucesso")

    except WebDriverException as e:
        logger.exception(f"Erro ao iniciar o Firefox WebDriver {e}")
        return pd.DataFrame(), datetime.now()
    except Exception as e:
        logger.exception(f"Erro inesperado ao iniciar o Firefox {e}")
        return pd.DataFrame(), datetime.now()

    try:
        driver.get("https://www.tesourodireto.com.br/titulos/precos-e-taxas.htm")
        time.sleep(3)

        xpath_linhas = '//*[@id="td-precos_taxas-tab_1"]/div/div[11]/table/tbody'
        rows = driver.find_elements(By.XPATH, xpath_linhas)
        dados = []

        for i, row in enumerate(rows, start=1):
            try:
                elemento = row.find_element(By.CSS_SELECTOR, "span.td-invest-table__name__text")
                titulo = elemento.get_attribute("aria-label")

                elementos = row.find_elements(By.CSS_SELECTOR, "span.td-invest-table__col__text")

                taxa_splitted = elementos[0].text.strip().split('+')
                if len(taxa_splitted) == 1:
                    taxa = taxa_splitted[0]
                else:
                    taxa = taxa_splitted[1]

                rentabilidade = taxa.replace('%', ' %').replace(',', '.')
                preco = elementos[2].text.strip().replace('.', '').replace(',', '.')
                vencimento = elementos[3].text.strip()

                # abreviar nomes dos titulos
                titulo = titulo.replace('Tesouro', '').replace('Renda+ Aposentadoria Extra', '').replace('com juros', 'juros')

                if not any(palavra in titulo.lower() for palavra in ["prefixado juros_", "semestrais_", "educa_"]):
                    dados.append({
                                'Título': titulo,
                                'Rentabilidade': rentabilidade,
                                'PU': preco,
                                'Vencimento': vencimento,
                    })
            except Exception:
                continue

        driver.quit()

        ts = datetime.now()  # marca quando rodou de fato

        return pd.DataFrame(dados), ts

    except Exception as e:
        logger.exception(f"Erro ao acessar a página com Selenium: {e}")
        driver.quit()
        return pd.DataFrame(), datetime.now()

@st.cache_data(ttl=1140)
def obter_tesouro_estado():

    options = FirefoxOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')

    try:
        logger.info("Iniciando o driver Firefox...")

        if os.name == 'nt':
            options.binary_location = r"C:\Program Files\Mozilla Firefox\firefox.exe"
            driver_path = os.path.join(os.path.dirname(__file__), "geckodriver.exe")
        else:
            driver_path = "/usr/local/bin/geckodriver"

        service = FirefoxService(executable_path=driver_path)
        driver = webdriver.Firefox(service=service, options=options)
        logger.info("Firefox iniciado com sucesso")

    except WebDriverException as e:
        logger.exception(f"Erro ao iniciar o Firefox WebDriver {e}")
        return pd.DataFrame(), datetime.now()
    except Exception as e:
        logger.exception(f"Erro inesperado ao iniciar o Firefox {e}")
        return pd.DataFrame(), datetime.now()

    try:
        driver.get("https://www.tesourodireto.com.br/titulos/precos-e-taxas.htm")
        time.sleep(3)

        estado_mercado = driver.find_element(By.XPATH, "/html/body/main/div[1]/div[1]/div/div[1]/div").text.replace("\n", " ").strip()

        if 'aberto' in estado_mercado.lower():
            driver.quit()
            return '✅ mercado aberto'
        elif 'fechado' in estado_mercado.lower():
            driver.quit()
            return '❌ mercado fechado'
        elif 'manutenção' in estado_mercado.lower():
            driver.quit()
            return '🔧 mercado em manutenção'

    except Exception as e:
        driver.quit()
        return f"Erro ao acessar página: {e}"

def atualizar_tesouro_em_background():
    try:
        # define horários de funcionamento
        hora_inicio = dtime(9, 33)
        hora_fim = dtime(18, 00)  # 1830
        agora = datetime.now().time()

        if datetime.now().weekday() >= 5:
            logging.info(f"[AGENDADOR] Função fora do dia")
            return

        forca_update1 = dtime(9, 43)
        forca_update2 = dtime(18, 10)

        logging.info(f"[AGENDADOR] Função chamada às {agora}")

        if hora_inicio <= agora <= hora_fim:
            logging.info(f"[AGENDADOR] Função no horário")

            if agora < forca_update1 or forca_update2 < agora:  # ex. 18:10 < agora < 18:30, força update pra virar noite atualizado
                logging.info(f"[AGENDADOR] Limpeza forçada do cache")
                obter_tesouro_titulos.clear()
                obter_tesouro_estado()

            df, ts = obter_tesouro_titulos()
            estado = obter_tesouro_estado()

            if not df.empty:
                with lock:
                    logging.info(f"[AGENDADOR] dataFrame OK.")
                    DADOS_TESOURO["dados"] = df.to_dict(orient="records")
                    DADOS_TESOURO["ultima_atualizacao"] = ts.strftime('%d/%m/%Y %H:%M')
                    DADOS_TESOURO["estado_mercado"] = estado
                salvar_dados_em_arquivo()
            else:
                logging.info(f"[AGENDADOR] dataFrame vazio após scrapping")
        else:
            logging.info(f"[AGENDADOR] Função fora do horário")

    except Exception as e:
        logger.exception(f"Erro no update background: {e}")

def salvar_dados_em_arquivo():
    with lock:
        try:
            with open("tesouro.json", "w", encoding="utf-8") as f:
                json.dump(DADOS_TESOURO, f, ensure_ascii=False, indent=2)
                logger.info("Arquivo tesouro.json salvo com sucesso.")
        except Exception as e:
            logger.error(f"[ERRO] Falha ao salvar arquivo: {e}")

def carregar_dados_do_arquivo():
    caminho = "tesouro.json"

    if not os.path.exists(caminho):
        logger.info("[INFO] Arquivo tesouro.json ainda não existe.")
        return None

    try:
        with open(caminho, "r", encoding="utf-8") as f:
            conteudo = f.read()
            # logger.info(f"[DEBUG] Conteúdo bruto lido: {conteudo[:200]}...")  # Só os primeiros 200 caracteres
            return json.loads(conteudo)
    except Exception as e:
        logger.info(f"[ERRO] Falha ao carregar tesouro.json: {e}")
        return None

# Inicializa agendador apenas uma vez
if not getattr(st, "_scheduler_registrado", False):
    scheduler = BackgroundScheduler()
    scheduler.add_job(atualizar_tesouro_em_background, 'interval', minutes=5)
    scheduler.start()
    st._scheduler_registrado = True

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
          { "name": "BMFBOVESPA:BBAS3", "displayName": "Banco de Brasil" },
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
    altura = linhas * 44 - linhas ** 2  # altura ideal para caber todas as linhas sem scroll


    AgGrid(
        df,
        gridOptions=grid_options,
        height=altura,
        fit_columns_on_grid_load=True,
        use_container_width=True)

df_btc = get_btc_data()
rsi = RSIIndicator(close=df_btc["close"], window=14).rsi()
fear_val, fear_cls = get_fear_and_greed()

# Últimos valores
price = df_btc["close"].iloc[-1]
rsi_val = rsi.iloc[-1]

# — Alertas de venda —
st.markdown("<div style='margin-top:2px'></div>", unsafe_allow_html=True)

n1, n2, n3 = 62, 70, 75  # níveis de RSI para venda
fg_threshold = 75  # nível de F&G para reforçar o sinal mais forte

if rsi_val > n3 and fear_val >= fg_threshold:
    st.error(f"🚨 RSI > {n3} → Venda 15% da posição  |  F&G: {fear_val} ({fear_cls})")
elif rsi_val > n2:
    st.warning(f"⚠️ RSI > {n2} → Venda 10% da posição  |  F&G: {fear_val} ({fear_cls})")
elif rsi_val > n1:
    st.info(f"ℹ️ RSI > {n1} → Venda 5% da posição  |  F&G: {fear_val} ({fear_cls})")
else:
    st.success(f"✅ Mercado em equilíbrio&nbsp;&nbsp;|&nbsp;&nbsp;RSI: {rsi_val:.2f}&nbsp;&nbsp;|&nbsp;&nbsp;F&G: {fear_val} ({fear_cls})")

# agora, criamos 3 colunas:
spacer0, col1, spacer1, col2, spacer2, col3, spacer3 = st.columns([0.3, 3.8, 0.1, 3.8, 0.1, 2.2, 0.1])
height = 180
with col1:
    # st.markdown("<div style='margin-top:10px'></div>", unsafe_allow_html=True)
    st.markdown(f"<h1 style='font-size:23px; font-weight:bold;'>Preço BTC/USDT: ${price:,.2f}</h1>", unsafe_allow_html=True)
    st.line_chart(df_btc["close"], height=height, use_container_width=True)

with col2:
    # st.subheader(f"RSI (14d): {rsi_val:.2f}")
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
now = datetime.now().strftime("%d/%m/%Y %H:%M")
# st.markdown(f"<div style='text-align: left; color: gray;'>🕒 Atualizado em: {now}</div>", unsafe_allow_html=True)
st.markdown(f"""*Fonte: [Binance](https://www.binance.com/pt-BR/markets/overview) em {now}*""")

# divisória horizontal
st.markdown("""
<hr style="border: 1px solid #ccc; margin-top: 20px; margin-bottom: 20px;">
""", unsafe_allow_html=True)


dados_cache = carregar_dados_do_arquivo()
if dados_cache:
    df_tesouro = pd.DataFrame(dados_cache["dados"])
    estado_mercado = dados_cache["estado_mercado"]
    ts_titulos = datetime.strptime(dados_cache["ultima_atualizacao"], "%d/%m/%Y %H:%M")
else:
    df_tesouro = pd.DataFrame()
    estado_mercado = "Indefinido"
    ts_titulos = datetime.now()

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

# Rodapé
st.markdown(f"""*Fonte: [Tesouro Direto](https://www.tesourodireto.com.br/titulos/precos-e-taxas.htm) em {ts_titulos.strftime('%d/%m/%Y %H:%M')}*""")

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


if st.button("🔁 Forçar atualização do Tesouro Direto"):
    atualizar_tesouro_em_background()
    st.success("Atualização forçada executada.")

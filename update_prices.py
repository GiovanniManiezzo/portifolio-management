import gspread
from oauth2client.service_account import ServiceAccountCredentials
import yfinance as yf
import ccxt
import pandas as pd
import time
from datetime import datetime
import requests
from bs4 import BeautifulSoup

# --- CONFIG ---
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
SHEET_NAME = "portifolio-management-sheet"
TAB_WALLET = "wallet"
TAB_PRICES = "prices"

# --- CONEXÃO ---
def connect_sheets():
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', SCOPE)
        client = gspread.authorize(creds)
        return client.open(SHEET_NAME)
    except Exception as e:
        print(f"[FATAL] Erro de conexão: {e}")
        exit()

# --- MOTORES DE BUSCA ---
def get_crypto_price(ticker):
    try:
        exchange = ccxt.binance()
        # Tratamento para tickers comuns (ex: BTC vira BTC/USDT)
        if '/' not in ticker: ticker = f"{ticker}/USDT"
        ticker_data = exchange.fetch_ticker(ticker)
        return float(ticker_data['last'])
    except:
        return 0.0

def get_b3_price(ticker, classe):
    # Sufixo .SA para ativos brasileiros listados na B3 (exceto Opções que as vezes variam)
    t = ticker if ticker.endswith('.SA') else f"{ticker}.SA"
    
    try:
        asset = yf.Ticker(t)
        # Prioridade: Preço regular -> Fechamento anterior -> Histórico recente
        price = asset.info.get('regularMarketPrice') or asset.info.get('previousClose')
        
        if price is None:
            hist = asset.history(period="1d")
            if not hist.empty:
                price = hist['Close'].iloc[-1]
            else:
                price = 0.0
        return float(price)
    except:
        return 0.0

import requests
from bs4 import BeautifulSoup

import requests
from bs4 import BeautifulSoup

def get_price_opcoes_net(ticker):
    clean_ticker = ticker.replace('.SA', '').upper()
    url = f"https://opcoes.net.br/{clean_ticker}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return 0.0

        soup = BeautifulSoup(response.content, 'html.parser')
        
        # 1. Localiza a tabela específica pela classe única "top-buffer-20"
        # Isso evita pegar tabelas de resumo ou outras irrelevantes
        table = soup.find('table', {'class': 'top-buffer-20'})
        
        if not table:
            print(f"[WARN] Tabela principal não encontrada para {clean_ticker}")
            return 0.0

        # 2. Mapeamento do Cabeçalho
        # A tabela tem 2 linhas de header. A segunda linha contém "Min, Pri, Med, Ult..."
        thead = table.find('thead')
        header_rows = thead.find_all('tr')
        
        # Pegamos a última linha do cabeçalho (onde estão os nomes das colunas)
        col_names_row = header_rows[-1] 
        cols = col_names_row.find_all(['td', 'th']) # O site usa td dentro do thead as vezes
        
        ult_index = -1
        
        # Procuramos o índice da coluna "Ult"
        for i, col in enumerate(cols):
            if "Ult" in col.get_text():
                ult_index = i
                break # IMPORTANTE: Parar no primeiro "Ult" (que é o da cotação, não volatilidade)
        
        if ult_index == -1:
            print(f"[WARN] Coluna 'Ult' não encontrada no cabeçalho.")
            return 0.0

        # 3. Extração do Dado
        tbody = table.find('tbody')
        if not tbody: return 0.0
        
        first_row = tbody.find('tr')
        if not first_row: return 0.0
        
        cells = first_row.find_all('td')
        
        # O TRUQUE DO OFFSET:
        # A linha de dados tem uma célula a mais no início (a Data) que não existe 
        # na segunda linha do cabeçalho (por causa do rowspan).
        # Portanto, o índice do dado é ult_index + 1.
        target_index = ult_index + 1
        
        if len(cells) > target_index:
            raw_value = cells[target_index].get_text().strip() # Ex: "0,8000"
            
            # Tratamento Brasil -> Python
            clean_value = raw_value.replace('.', '').replace(',', '.')
            
            # Validação para evitar erros de conversão com "-" ou vazio
            if not clean_value or clean_value == '-':
                return 0.0
                
            return float(clean_value)
            
        return 0.0

    except Exception as e:
        print(f"[ERRO SCRAPING] {clean_ticker}: {e}")
        return 0.0

def get_usd_brl_rate():
    try:
        return float(yf.Ticker("BRL=X").info.get('regularMarketPrice', 5.0))
    except:
        return 5.0 # Fallback de segurança
    
# --- CACHE DA TAXA CDI ---
# Variável global para não chamar a API do Banco Central 50 vezes
CURRENT_CDI_RATE = None

def get_current_cdi():
    """Busca a Taxa Selic/CDI Anualizada atual no Banco Central."""
    global CURRENT_CDI_RATE
    if CURRENT_CDI_RATE is not None:
        return CURRENT_CDI_RATE
        
    try:
        # API do BCB para a série 1178 (Selic anualizada)
        url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.1178/dados/ultimos/1?formato=json"
        response = requests.get(url, timeout=5)
        data = response.json()
        rate = float(data[0]['valor']) / 100 # Vem 11.25, vira 0.1125
        CURRENT_CDI_RATE = rate
        print(f"   [INFO] Taxa CDI/Selic Atual: {rate*100:.2f}% a.a.")
        return rate
    except Exception as e:
        print(f"   [WARN] Falha ao buscar CDI: {e}. Usando fallback 14.9%.")
        return 0.149

def calculate_fixed_income(valor_inicial, data_inicio, indexador):
    """
    Calcula o Valor Presente estimado baseada em Juros Compostos.
    Suporta: '105% CDI', '12% PRE'.
    """
    if not data_inicio or not indexador:
        return valor_inicial

    # 1. Calcular o Tempo (em Anos)
    try:
        dt_start = datetime.strptime(str(data_inicio), "%Y-%m-%d")
        print(dt_start)
        dt_now = datetime.now()
        print(dt_now)
        days_diff = (dt_now - dt_start).days
        print("diff: ", days_diff)
        years = days_diff / 365.25 # Aproximação calendário
    except ValueError:
        print(f"   [ERRO] Formato de data inválido: {data_inicio}")
        return valor_inicial

    if days_diff < 0: return valor_inicial

    # 2. Decodificar o Indexador
    indexador = str(indexador).upper().replace(' ', '').replace(',', '.')
    
    annual_rate = 0.0
    
    # Lógica para Pós-Fixado (CDI)
    if 'CDI' in indexador:
        # Ex: "105%CDI" -> pega 105, divide por 100, multiplica pela taxa Selic atual
        percentage_str = indexador.split('%CDI')[0]
        print("percentage_str:", percentage_str)
        try:
            percent_cdi = float(percentage_str) / 100
            market_rate = get_current_cdi()
            print("market_rate:", market_rate)
            annual_rate = market_rate * percent_cdi
        except:
            annual_rate = 0.10 # Fallback 10%

    # Lógica para Pré-Fixado (PRE)
    elif 'PRE' in indexador:
        # Ex: "12.5%PRE"
        percentage_str = indexador.split('%PRE')[0]
        try:
            annual_rate = float(percentage_str) / 100
        except:
            annual_rate = 0.10

    elif 'IPCA+' in indexador:
        # Assumimos IPCA constante de 0.3% a.m. e spread real informado no indexador
        ipca_monthly_rate = 0.003
        ipca_annual_rate = (1 + ipca_monthly_rate) ** 12 - 1
        try:
            spread_part = indexador.split('IPCA+')[1].replace('%', '')
            spread_rate = float(spread_part) / 100
        except:
            spread_rate = 0.0
        annual_rate = ((1 + ipca_annual_rate) * (1 + spread_rate)) - 1

    # 3. Fórmula dos Juros Compostos: M = C * (1 + i)^t
    # Onde t está em anos
    valor_atual = valor_inicial * ((1 + annual_rate) ** years)
    
    return valor_atual

# --- ORQUESTRAÇÃO ---
def main():
    print("--- Iniciando Orquestracao ---")
    sh = connect_sheets()
    
    # Leitura da Carteira
    ws_wallet = sh.worksheet(TAB_WALLET)
    df = pd.DataFrame(ws_wallet.get_all_records())
    
    # Validar se colunas existem
    required_cols = ['Ticker', 'Classe', 'Quantidade', 'Moeda', 'Preço Médio', 'Manual Price', 'Direção', 'Data Início', 'Indexador']
    if not all(col in df.columns for col in required_cols):
        print(f"[ERRO] Colunas faltando. Necessario: {required_cols}")
        return

    usd_rate = get_usd_brl_rate()
    print(f"Dolar Base: R$ {usd_rate:.2f}")

    results = []

    for idx, row in df.iterrows():
        ticker = str(row['Ticker']).strip()
        classe = str(row['Classe']).strip() # Acao, FII, Cripto, RendaFixa
        qty = float(row['Quantidade'] or 0)
        avg_price = float(row['Preço Médio'] or 0)
        currency = str(row['Moeda']).strip().upper()
        manual_price = float(row['Manual Price'] or 0)
        direction = str(row.get('Direção', 'C')).strip().upper() or 'C'
        direction = direction if direction in ['C', 'V'] else 'C'
        start_date = row.get('Data Início', '')
        indexer = row.get('Indexador', '')
        
        current_price = 0.0
        
        print(f"[{idx+1}] Processando {classe}: {ticker}...")

        # LÓGICA DE ROTEAMENTO (SWITCH)
        if classe in ['Acao', 'FII', 'ETF']:
            current_price = get_b3_price(ticker, classe)
            print(current_price)
        
        elif classe == 'Opcao':
            # Opções podem ter tickers variados, tentar direto
            current_price = get_price_opcoes_net(ticker)

        
        elif classe == 'Cripto':
            current_price = get_crypto_price(ticker)
        
        elif classe == 'RendaFixa':
            # O "Preço Atual" na Renda Fixa não é o valor de mercado unitário,
            # mas sim o Valor Total Atualizado dividido pela quantidade.
            # Se Qty = 1, Preço Atual = Valor Total.
            
            # 1. Calcula o Valor Total investido inicialmente neste aporte
            investimento_inicial = qty * avg_price
            
            # 2. Calcula quanto esse dinheiro vale hoje
            valor_atualizado_total = calculate_fixed_income(investimento_inicial, start_date, indexer)
            
            # 3. Reconverte para "Preço Unitário" para manter a lógica da planilha
            current_price = valor_atualizado_total / qty if qty > 0 else 0.0
            
            print(f"   -> RF Calculada: R$ {investimento_inicial:.2f} virou R$ {valor_atualizado_total:.2f}")
        
        else:
            current_price = 0.0 # Classe desconhecida
        
        # CÁLCULOS FINANCEIROS
        # Se falhou tudo, usa manual ou médio
        final_price = current_price if current_price > 0 else (manual_price if manual_price > 0 else avg_price)
        
        # Total na moeda do ativo
        total_native = qty * final_price 
        
        # Conversão BRL (Se for USD)
        rate_cambio = usd_rate if currency == 'USD' else 1.0
        total_brl = total_native * rate_cambio
        
        # Lucro/Prejuízo e Rentabilidade
        cost_basis = qty * avg_price * rate_cambio # Quanto gastei
        pnl_reais = total_brl - cost_basis
        
        if cost_basis > 0:
            rentabilidade_pct = (pnl_reais / cost_basis) * 100 # Em porcentagem (ex: 15.5)
        else:
            rentabilidade_pct = 0.0

        if classe == 'Opcao' and direction == 'V':
            pnl_reais *= -1
            rentabilidade_pct *= -1

        results.append([
            ticker, classe, currency, qty, avg_price, 
            final_price, total_native, total_brl, 
            pnl_reais, rentabilidade_pct, # <--- Essas são as colunas que faltavam
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ])
        
        time.sleep(0.5) # Proteção de Rate Limit

    # ESCRITA NO SHEETS
    try:
        ws_prices = sh.worksheet(TAB_PRICES)
        ws_prices.clear()
        # Headers ricos para o Power BI
        ws_prices.append_row([
            "Ticker", "Classe", "Moeda", "Quantidade", "Preço Médio", 
            "Preço Atual", "Total (Moeda Origem)", "Total (BRL)", 
            "Lucro/Prej (R$)", "Rentabilidade (%)", "Atualização"
        ])
        ws_prices.append_rows(results)
        print("--- Sucesso! Dados exportados para aba 'prices' ---")
    except Exception as e:
        print(f"[ERRO CRÍTICO] Falha ao salvar: {e}")

if __name__ == "__main__":
    main()
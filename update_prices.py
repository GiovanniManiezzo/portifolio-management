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

# --- ORQUESTRAÇÃO ---
def main():
    print("--- Iniciando Orquestracao ---")
    sh = connect_sheets()
    
    # Leitura da Carteira
    ws_wallet = sh.worksheet(TAB_WALLET)
    df = pd.DataFrame(ws_wallet.get_all_records())
    
    # Validar se colunas existem
    required_cols = ['Ticker', 'Classe', 'Quantidade', 'Moeda', 'Preço Médio', 'Manual Price', 'Direção']
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
            # Renda Fixa é complexa para automatizar free. 
            # Estratégia: Usar valor manual inserido pelo usuário na coluna F.
            current_price = manual_price if manual_price > 0 else avg_price
        
        else:
            current_price = 0.0 # Classe desconhecida
        
        # CÁLCULOS FINANCEIROS
        # Se preço veio zerado da API, usa o manual ou o médio para não zerar patrimônio
        final_price = current_price if current_price > 0 else (manual_price if manual_price > 0 else avg_price)
        total_native = qty * final_price
        
        # Conversão para BRL
        rate = usd_rate if currency == 'USD' else 1.0
        total_brl = total_native * rate
        
        # Lucro/Prejuízo Estimado
        cost_basis = qty * avg_price * rate
        pnl = total_brl - cost_basis
        pnl_percent = (pnl / cost_basis) if cost_basis > 0 else 0

        if classe == 'Opcao' and direction == 'V':
            pnl *= -1
            pnl_percent *= -1

        results.append([
            ticker, classe, direction, currency, qty, avg_price, 
            final_price, total_native, total_brl, 
            pnl, pnl_percent, 
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ])
        
        time.sleep(0.5) # Proteção de Rate Limit

    # ESCRITA NO SHEETS
    try:
        ws_prices = sh.worksheet(TAB_PRICES)
        ws_prices.clear()
        # Headers ricos para o Power BI
        ws_prices.append_row([
            "Ticker", "Classe", "Direção", "Moeda", "Quantidade", "Preço Médio", 
            "Preço Atual", "Total (Moeda Origem)", "Total (BRL)", 
            "Lucro/Prej (R$)", "Rentabilidade (%)", "Atualização"
        ])
        ws_prices.append_rows(results)
        print("--- Sucesso! Dados exportados para aba 'prices' ---")
    except Exception as e:
        print(f"[ERRO CRÍTICO] Falha ao salvar: {e}")

if __name__ == "__main__":
    main()
import streamlit as st
import pandas as pd
import plotly.express as px
from google.oauth2 import service_account
import gspread

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Investimentos", layout="wide")

def connect_google_sheets():
    # Tenta conectar via Streamlit Secrets (Nuvem)
    if "gcp_service_account" in st.secrets:
        return gspread.service_account_from_dict(st.secrets["gcp_service_account"])
    
    # Se falhar, tenta conectar via arquivo local (Seu PC)
    try:
        return gspread.service_account(filename='credentials.json')
    except:
        st.error("Não foi possível encontrar as credenciais (Secrets ou JSON local).")
        return None


# --- FUNÇÃO DE CARGA (COM CACHE PARA NÃO LER TODA HORA) ---
def load_data():

    gc = connect_google_sheets()
    if not gc: return pd.DataFrame() # Retorna vazio se falhar

    sh = gc.open("portifolio-management-sheet") # Nome exato da planilha
    ws = sh.worksheet("prices")
    df = pd.DataFrame(ws.get_all_records())
    
    # Lê a aba de preços
    ws = sh.worksheet("prices")
    df = pd.DataFrame(ws.get_all_records())
    
    # Tratamento de tipos
    df['Total (BRL)'] = pd.to_numeric(df['Total (BRL)'])
    df['Rentabilidade (%)'] = pd.to_numeric(df['Rentabilidade (%)'])
    return df


df = load_data()

# --- CABEÇALHO (BIG NUMBERS) ---
st.title("💰 Painel de Controle Financeiro")

total_patrimonio = df['Total (BRL)'].sum()
lucro_medio = df['Rentabilidade (%)'].mean() * 100 # Simplificação

col1, col2, col3 = st.columns(3)
col1.metric("Patrimônio Total", f"R$ {total_patrimonio:,.2f}")
col2.metric("Rentabilidade Média", f"{lucro_medio:.2f}%")
col3.metric("Ativos na Carteira", len(df))

st.markdown("---")

# --- GRÁFICOS ---
col_chart1, col_chart2 = st.columns(2)

with col_chart1:
    st.subheader("Alocação por Classe")
    fig_pizza = px.pie(df, values='Total (BRL)', names='Classe', hole=0.4)
    st.plotly_chart(fig_pizza, use_container_width=True)
    
with col_chart2:
    st.subheader("Top Rentabilidade")
    # Filtra os top 10 e ordena
    top_winners = df.sort_values(by='Rentabilidade (%)', ascending=False).head(10)
    fig_bar = px.bar(top_winners, x='Rentabilidade (%)', y='Ticker', orientation='h', 
                        color='Rentabilidade (%)', color_continuous_scale='Bluered_r')
    st.plotly_chart(fig_bar, use_container_width=True)

# --- TABELA DETALHADA ---
st.subheader("Detalhamento")
st.dataframe(df)

if st.button('Atualizar Dados'):
    st.cache_data.clear()
    st.rerun()
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
    
    # Tratamento de tipos
    numeric_cols = ['Total (BRL)', 'Rentabilidade (%)', 'Lucro/Prej (R$)']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    return df


df = load_data()

if df.empty:
    st.warning("Sem dados para exibir. Verifique a planilha 'prices'.")
    st.stop()

class_summary = df.groupby('Classe').agg(
    total_brl=('Total (BRL)', 'sum'),
    total_pnl=('Lucro/Prej (R$)', 'sum')
).reset_index()
class_summary['Rentabilidade (%)'] = class_summary.apply(
    lambda row: (row['total_pnl'] / row['total_brl']) * 100 if row['total_brl'] else 0.0,
    axis=1
)

# --- CABEÇALHO (BIG NUMBERS) ---
st.title("💰 Painel de Controle Financeiro")

total_patrimonio = df['Total (BRL)'].sum()

col1, col2 = st.columns(2)
col1.metric("Patrimônio Total", f"R$ {total_patrimonio:,.2f}")
col2.metric("Ativos na Carteira", len(df))

st.subheader("Rentabilidade por Classe")
if class_summary.empty:
    st.info("Nenhuma classe de ativo encontrada.")
else:
    cols_per_row = 4
    for start in range(0, len(class_summary), cols_per_row):
        row_slice = class_summary.iloc[start:start + cols_per_row]
        cols = st.columns(len(row_slice))
        for col, (_, data_row) in zip(cols, row_slice.iterrows()):
            rent_value = data_row['Rentabilidade (%)']
            font_color = "#d13232" if rent_value < 0 else "#1a7f37"
            pnl_text = f"R$ {data_row['total_pnl']:,.2f}"
            rent_text = f"{rent_value:.2f}%"
            label = data_row['Classe']
            # Custom block to control text color based on performance
            col.markdown(
                f"""
                <div style='padding:12px 16px;border:1px solid #e0e0e0;border-radius:8px;'>
                    <div style='font-size:0.85rem;color:#666;'>{label}</div>
                    <div style='font-size:1.4rem;font-weight:600;color:{font_color};'>{rent_text}</div>
                    <div style='font-size:0.9rem;color:#999;'>P&L: {pnl_text}</div>
                </div>
                """,
                unsafe_allow_html=True
            )

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
import streamlit as st
import pandas as pd
import plotly.express as px
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

# --- FUNÇÃO DE CARGA (MANTIDA ORIGINAL) ---
def load_data():
    gc = connect_google_sheets()
    if not gc: return pd.DataFrame() # Retorna vazio se falhar

    sh = gc.open("portifolio-management-sheet") 
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

# --- NOVA LÓGICA: SEPARAÇÃO DE RESERVA VS INVESTIMENTOS ---
# Garante que a coluna Vencimento existe para não quebrar
if 'Vencimento' not in df.columns:
    df['Vencimento'] = ''

# Filtra o que é Reserva (Case insensitive para "Liquido", "liquido", "LIQUIDO")
filtro_reserva = df['Vencimento'].astype(str).str.strip().str.lower() == 'liquido'

# Totais calculados
total_patrimonio = df['Total (BRL)'].sum()
total_reserva = df.loc[filtro_reserva, 'Total (BRL)'].sum()
total_investimentos = df.loc[~filtro_reserva, 'Total (BRL)'].sum()

# Lógica de Resumo por Classe (MANTIDA ORIGINAL)
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

# ATUALIZADO: Agora com 3 colunas para mostrar a Reserva separada
col1, col2, col3 = st.columns(3)
col1.metric("Patrimônio Total", f"R$ {total_patrimonio:,.2f}")
col2.metric("🚨 Reserva/Caixa", f"R$ {total_reserva:,.2f}", help="Ativos marcados como 'Liquido'")
col3.metric("Investimentos (Longo Prazo)", f"R$ {total_investimentos:,.2f}")

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

# --- GRÁFICOS (MANTIDOS ORIGINAIS) ---
col_chart1, col_chart2 = st.columns(2)

with col_chart1:
    st.subheader("Alocação por Classe")
    fig_pizza = px.pie(df, values='Total (BRL)', names='Classe', hole=0.4)
    st.plotly_chart(fig_pizza, use_container_width=True)
    
with col_chart2:
    st.subheader("Top Rentabilidade")
    top_winners = df.sort_values(by='Rentabilidade (%)', ascending=False).head(10)
    fig_bar = px.bar(top_winners, x='Rentabilidade (%)', y='Ticker', orientation='h', 
                        color='Rentabilidade (%)', color_continuous_scale='Bluered_r')
    st.plotly_chart(fig_bar, use_container_width=True)

# --- NOVA SEÇÃO: CRONOGRAMA DE LIQUIDEZ CORRIGIDO ---
st.markdown("---")
st.subheader("📅 Cronograma de Liquidez (Vencimentos)")

# Verifica se existe a coluna Vencimento para não quebrar
if 'Vencimento' in df.columns:
    df_timeline = df.copy()
    
    # Define HOJE para usar nos casos "Liquido"
    hoje = pd.Timestamp.now().normalize()
    
    # Função para converter "Liquido" em DATA DE HOJE, e texto normal em Data
    def converter_data_vencimento(val):
        s = str(val).strip().lower()
        if s == 'liquido':
            return hoje
        return pd.to_datetime(val, errors='coerce')

    # Cria coluna auxiliar de data
    df_timeline['Vencimento_Dt'] = df_timeline['Vencimento'].apply(converter_data_vencimento)
    
    # Remove linhas onde não conseguimos determinar uma data (ex: ações vazias)
    df_timeline = df_timeline.dropna(subset=['Vencimento_Dt'])
    
    if not df_timeline.empty:
        df_timeline = df_timeline.sort_values(by='Vencimento_Dt')

        # Cria categoria visual para pintar a Reserva de vermelho e o resto pela Classe
        df_timeline['Categoria_Visual'] = df_timeline.apply(
            lambda x: '🚨 RESERVA' if str(x['Vencimento']).strip().lower() == 'liquido' else x['Classe'], 
            axis=1
        )

        fig_timeline = px.bar(
            df_timeline, 
            x='Vencimento_Dt', 
            y='Total (BRL)', 
            color='Categoria_Visual', # Usa a nova categoria
            text='Total (BRL)',
            title="Fluxo de Caixa (Reserva vs Vencimentos Futuros)",
            labels={'Vencimento_Dt': 'Data de Disponibilidade', 'Total (BRL)': 'Valor Líquido'}
        )
        
        # Ajustes visuais
        fig_timeline.update_traces(texttemplate='R$ %{text:.2s}', textposition='outside')
        fig_timeline.update_layout(xaxis_title="Linha do Tempo", yaxis_title="Valor (R$)")
        
        # Adiciona linha tracejada no dia de hoje
        fig_timeline.add_vline(x=hoje.timestamp() * 1000, line_width=1, line_dash="dash", line_color="green")
        
        st.plotly_chart(fig_timeline, use_container_width=True)
        
        # Tabela auxiliar abaixo do gráfico
        st.caption("Próximos Resgates:")
        cols_show = ['Vencimento', 'Ticker', 'Classe', 'Total (BRL)']
        st.dataframe(
            df_timeline[cols_show].sort_values(by='Vencimento_Dt').head(5),
            hide_index=True
        )
    else:
        st.info("Nenhum dado de vencimento encontrado para gerar o gráfico.")
else:
    st.warning("A coluna 'Vencimento' não foi encontrada na planilha.")

st.markdown("---")

# --- TABELA DETALHADA ---
st.subheader("Detalhamento Completo")
st.dataframe(df)

if st.button('Atualizar Dados'):
    st.cache_data.clear()
    st.rerun()
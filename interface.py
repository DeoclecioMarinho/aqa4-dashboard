from pathlib import Path

import streamlit as st

DESCRIPTIONS = {
    "Visão geral": "Resumo executivo da recolha nos quatro instrumentos. Acompanha as submissões do dia, as escolas alcançadas e os alunos com registos nos três instrumentos individuais.",
    "Cobertura da amostra": "Acompanha as 20 escolas selecionadas por unidade e instrumento. A tabela ajuda a identificar onde já há recolha e onde ainda faltam submissões.",
    "Prática": "Verifica a completude dos exercícios, a distribuição das pontuações e os itens com mais erros ou omissões.",
    "Avaliação principal": "Consulta os resultados globais, por escola, por secção e por item. Usa a região e a escola para examinar padrões dentro da amostra.",
    "Questionários": "Explora o perfil dos alunos e dos professores com base nas respostas recebidas.",
    "Qualidade": "Identifica códigos em falta, submissões repetidas e registos que precisam de ser reconciliados com a amostra.",
}

ICONS = {"Visão geral": "▦", "Cobertura da amostra": "◎", "Prática": "✎",
         "Avaliação principal": "▥", "Questionários": "☷", "Qualidade": "✓"}

STYLE = """
<style>
[data-testid="stSidebar"] {border-right:1px solid #dbe8f2;}
[data-testid="stSidebar"] [data-testid="stImage"] img {
  background:#fff; padding:.35rem; border-radius:.65rem; box-sizing:border-box;
}
[data-testid="stSidebar"] [role="radiogroup"] {gap:.28rem;}
[data-testid="stSidebar"] [role="radiogroup"] label {
  border-radius:.65rem; padding:.55rem .68rem; margin:0; min-height:2.75rem;
}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
  background:#086ba3;
}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {
  color:#fff; font-weight:650;
}
[data-testid="stMetric"] {
  position:relative; min-height:7.2rem; background:#fff; border:1px solid #dae8f2;
  border-radius:1rem; padding:1.05rem 1.1rem .9rem; box-shadow:0 3px 12px #082e5110;
}
[data-testid="stMetric"]::before {
  content:""; position:absolute; top:0; left:1.1rem; width:2.3rem; height:4px;
  border-radius:0 0 4px 4px; background:#0879b7;
}
[data-testid="stMetricLabel"] p {font-weight:600; color:#3c5c76;}
[data-testid="stMetricValue"] {font-size:clamp(1.35rem, 2.1vw, 2rem); color:#092e51; font-weight:700;}
.aqa-objective {
  border:1px solid #dcecf8; border-left:4px solid #0879b7;
  background:#edf6fb; color:#143b59; border-radius:.75rem; padding:.9rem 1rem; margin-bottom:1.4rem;
}
.aqa-objective strong {display:block; margin-bottom:.2rem;}
@media(max-width:700px) {
  [data-testid="stMetric"] {min-height:5.8rem;}
}
</style>
"""


def navigation(root: Path):
    st.markdown(STYLE, unsafe_allow_html=True)
    with st.sidebar:
        st.image(str(root / "logo.png"), use_container_width=True)
        st.markdown("**AQA4 · PCH**")
        st.caption("Painel de acompanhamento")
        st.divider()
        page = st.radio("Módulos", list(DESCRIPTIONS), format_func=lambda name: f"{ICONS[name]}  {name}",
                        label_visibility="collapsed")
        st.divider()
        update = st.button("Atualizar do Kobo", type="primary")
    st.title("Seguimento do piloto AQA4" if page == "Visão geral" else page)
    return page, update


def objective(page):
    st.markdown(f'<div class="aqa-objective"><strong>Objetivo da análise</strong>{DESCRIPTIONS[page]}</div>',
                unsafe_allow_html=True)


def filter_analysis(data, plan, page):
    if page == "Visão geral":
        return data, plan
    st.divider()
    with st.expander("Filtrar esta análise", expanded=False):
        region_col, school_col, date_col = st.columns(3)
        regions = region_col.multiselect("Região / unidade", sorted(set(plan["regiao"]) | set(data["Região"])), key=f"r_{page}")
        if regions:
            data = data[data["Região"].isin(regions)]
            plan = plan[plan["regiao"].isin(regions)]
        schools = school_col.multiselect("Escola", sorted(set(plan["escola"]) | set(data["Escola exibida"])), key=f"e_{page}")
        if schools:
            data = data[data["Escola exibida"].isin(schools)]
            plan = plan[plan["escola"].isin(schools)]
        days = sorted(data["Dia"].dropna().unique())
        if days:
            period = date_col.date_input("Período de envio", (days[0], days[-1]), min_value=days[0], max_value=days[-1], key=f"d_{page}")
            if len(period) == 2 and tuple(period) != (days[0], days[-1]):
                data = data[data["Dia"].between(*period)]
        st.caption("Os filtros aplicam-se apenas a este módulo.")
    return data, plan

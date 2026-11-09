from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from datetime import datetime, timezone
import json
import os
import re
import unicodedata
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import pandas as pd
import streamlit as st


DESCRIPTIONS = {
    "Visão geral": "Resumo executivo da recolha nos quatro instrumentos. Acompanha as submissões do dia, as escolas alcançadas e os alunos com registos nos três instrumentos individuais.",
    "Cobertura da amostra": "Acompanha as 20 escolas selecionadas por unidade e instrumento. A tabela ajuda a identificar onde já há recolha e onde ainda faltam submissões.",
    "Prática": "Verifica a completude dos exercícios, a distribuição das pontuações e os itens com mais erros ou omissões.",
    "Avaliação principal": "Consulta os resultados globais, por escola, por secção e por item. Usa a região e a escola para examinar padrões dentro da amostra.",
    "Questionários": "Explora o perfil dos alunos e dos professores com base nas respostas recebidas.",
    "Qualidade": "Identifica códigos em falta, submissões repetidas e registos que precisam de ser reconciliados com a amostra.",
}

ICONS = {"Visão geral": "dashboard", "Cobertura da amostra": "location_on",
         "Prática": "edit_note", "Avaliação principal": "bar_chart",
         "Questionários": "assignment", "Qualidade": "fact_check"}

STYLE = """
<style>
[data-testid="stSidebar"] {border-right:1px solid #dbe8f2;}
[data-testid="stSidebar"] [data-testid="stImage"] img {
  background:#fff; padding:.35rem; border-radius:.65rem; box-sizing:border-box;
}
[data-testid="stSidebar"] .st-key-aqa_nav [data-testid="stVerticalBlock"] {gap:.25rem;}
[data-testid="stSidebar"] .st-key-aqa_nav button {
  justify-content:flex-start; border-radius:.65rem; padding:.65rem .8rem;
  min-height:2.75rem; text-align:left;
}
[data-testid="stSidebar"] .st-key-aqa_nav button[kind="tertiary"] {color:#16486b;}
[data-testid="stSidebar"] .st-key-aqa_nav button[kind="primary"] {
  background:#086ba3; border-color:#086ba3; color:white;
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
    if "aqa_page" not in st.session_state:
        st.session_state.aqa_page = "Visão geral"
    page = st.session_state.aqa_page
    with st.sidebar:
        st.image(str(root / "logo.png"), width="stretch")
        st.markdown("**AQA4 · PCH**")
        st.caption("Painel de acompanhamento")
        st.divider()
        with st.container(key="aqa_nav"):
            for name, icon in ICONS.items():
                st.button(name, icon=f":material/{icon}:", width="stretch",
                          type="primary" if page == name else "tertiary",
                          key=f"nav_{icon}", on_click=st.session_state.__setitem__,
                          args=("aqa_page", name))
        st.divider()
        update = st.button("Atualizar do Kobo", icon=":material/refresh:", width="stretch")
    st.title("Seguimento do piloto AQA4" if page == "Visão geral" else page)
    return page, update


def objective(page):
    st.markdown(f'<div class="aqa-objective"><strong>Objetivo da análise</strong>{DESCRIPTIONS[page]}</div>',
                unsafe_allow_html=True)


def filter_analysis(data, plan, page):
    if page == "Visão geral":
        return data, plan
    st.subheader("Dados do módulo")
    with st.expander("Filtrar por região, escola ou data", expanded=False):
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


PRACTICE = "Prática"
TEST = "Avaliação principal"
PROFILES = {
    "Alunos": {"idade": "Idade", "sexo": "Sexo", "linguas_casa": "Línguas em casa",
               "portugues_casa": "Português em casa", "livros": "Livros em casa"},
    "Professores": {"anos_docencia": "Anos de docência", "qualificacao": "Qualificação",
                   "lingua_ensino": "Língua de ensino", "formacao_recente": "Formação recente",
                   "conhece_aplicativo": "Conhece o aplicativo"},
}


def normalized_name(value):
    value = unicodedata.normalize("NFKD", value.casefold())
    return re.sub(r"[^a-z0-9]", "", value)


def roster(path, uploaded):
    plan = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    if uploaded:
        supplied = pd.read_csv(BytesIO(uploaded.getvalue()), dtype=str, keep_default_na=False,
                               encoding="utf-8-sig", sep=None, engine="python")
        keys = ["regiao", "escola"]
        if supplied.duplicated(keys).any() or set(map(tuple, supplied[keys].values)) != set(map(tuple, plan[keys].values)):
            raise ValueError("O ficheiro deve manter as 20 escolas e as respetivas unidades.")
        plan = plan.drop(columns="codigo_escola").merge(supplied[keys + ["codigo_escola"]], on=keys, validate="one_to_one")
    plan["codigo_escola"] = plan["codigo_escola"].str.strip()
    assigned = plan["codigo_escola"].ne("")
    if plan.loc[assigned, "codigo_escola"].duplicated().any():
        raise ValueError("O mesmo código foi atribuído a mais de uma escola.")
    plan["Amostra"] = range(1, len(plan) + 1)
    return plan


def associate(data, plan):
    data = data.copy()
    coded = plan[plan["codigo_escola"].ne("")].set_index("codigo_escola")["Amostra"]
    named = plan.assign(chave=plan["escola"].map(normalized_name))
    unique_names = named[~named["chave"].duplicated(keep=False)].set_index("chave")["Amostra"]
    data["Amostra"] = data["Escola"].map(coded).fillna(data["Escola"].map(normalized_name).map(unique_names))
    data["Região"] = data["Amostra"].map(plan.set_index("Amostra")["regiao"]).fillna("Por confirmar")
    data["Escola exibida"] = data["Amostra"].map(plan.set_index("Amostra")["escola"]).fillna(
        data["Escola"].replace("", "Sem código"))
    return data


def export_table(label, data, name):
    st.download_button(label, data.to_csv(index=False).encode("utf-8-sig"), name, "text/csv")


def coverage(data, plan, forms, errors):
    st.subheader("Cobertura das escolas selecionadas")
    matched = data.dropna(subset=["Amostra"])
    counts = matched.groupby(["Amostra", "Instrumento"]).size().unstack(fill_value=0)
    counts = counts.reindex(index=plan["Amostra"], columns=list(forms), fill_value=0).fillna(0).astype(int)
    covered = counts.gt(0).any(axis=1)
    a, b, c = st.columns(3)
    a.metric("Escolas na seleção", len(plan))
    b.metric("Com submissões identificadas", int(covered.sum()))
    c.metric("Registos sem escola associada", int(data["Amostra"].isna().sum()))
    table = plan.set_index("Amostra")[["regiao", "escola", "setor", "codigo_escola"]].join(counts)
    table["Situação"] = ["Com registos" if seen else "Código por confirmar" if not code else
                         "Consulta parcial" if errors else "Sem registos"
                         for seen, code in zip(covered, table["codigo_escola"])]
    for form in errors:
        table[form] = "Indisponível"
    table = table.rename(columns={"regiao": "Unidade", "escola": "Escola selecionada",
                                  "setor": "Setor", "codigo_escola": "Código"})
    st.dataframe(table.reset_index(drop=True), hide_index=True)
    export_table("Descarregar cobertura por escola", table.reset_index(drop=True), "aqa4_cobertura.csv")
    if not matched.empty:
        totals = matched.groupby(["Região", "Instrumento"]).size().unstack(fill_value=0)
        st.subheader("Submissões associadas por unidade")
        st.bar_chart(totals)
    st.caption("Uma escola com código por confirmar pode já ter recolha. As submissões sem correspondência ficam no módulo Qualidade.")


def latest_student_records(data):
    identified = data["Escola"].ne("") & data["Aluno"].ne("")
    ordered = data.loc[identified].sort_values(["Enviado", "ID Kobo"], kind="stable", na_position="first")
    return pd.concat([ordered.drop_duplicates(["Escola", "Aluno"], keep="last"), data.loc[~identified]])


def analysis(data, form, error):
    st.subheader("Resumo dos resultados")
    if error:
        st.warning(error)
        return
    received = data[data["Instrumento"].eq(form)]
    sample = latest_student_records(received)
    valid = sample[sample["Pontuação"].between(0, 100)]
    a, b, c, d = st.columns(4)
    a.metric("Registos analisados", len(sample))
    b.metric("Com pontuação", len(valid))
    c.metric("Média de acertos", f"{valid['Pontuação'].mean():.1f}%" if len(valid) else "—")
    d.metric("Mediana", f"{valid['Pontuação'].median():.1f}%" if len(valid) else "—")
    st.caption(f"{len(received)} submissões recebidas · {len(received) - len(sample)} repetições excluídas dos resultados.")
    st.caption("Por par escola–aluno, usa-se a última submissão no período selecionado. Registos sem os dois códigos são contados separadamente.")
    if sample.empty:
        st.info("Ainda não há submissões deste instrumento nos filtros selecionados.")
        return
    if form == PRACTICE:
        complete = sample["pratica_completa"].isin(["0", "1"])
        st.metric("Práticas completas", f"{sample['pratica_completa'].eq('1').sum()} / {complete.sum()}" if complete.any() else "—")
    if form == TEST:
        sections = []
        for section in "ABC":
            n = pd.to_numeric(sample[f"itens_chave_{section}"], errors="coerce")
            scores = pd.to_numeric(sample[f"percent_{section}"], errors="coerce")
            scores = scores[n.gt(0) & scores.between(0, 100)]
            sections.append({"Secção": section, "N": len(scores), "Média (%)": round(scores.mean(), 1)})
        st.subheader("Resultados por secção")
        section_table = pd.DataFrame(sections)
        st.dataframe(section_table, hide_index=True)
        if section_table["Média (%)"].notna().any():
            st.bar_chart(section_table.dropna(subset=["Média (%)"]), x="Secção", y="Média (%)", color="#006DB3")
    if not valid.empty:
        st.subheader("Distribuição das pontuações")
        bands = pd.cut(valid["Pontuação"], [-0.01, 25, 50, 75, 100], labels=["0–25", ">25–50", ">50–75", ">75–100"])
        st.bar_chart(bands.value_counts(sort=False).rename("Registos"))
        st.subheader("Resultados por escola")
        summary = (valid.groupby(["Região", "Escola exibida"])["Pontuação"]
                   .agg(N="size", Média="mean", Mediana="median").round(1).reset_index())
        st.dataframe(summary, hide_index=True)
        export_table("Descarregar resumo de resultados", summary, "aqa4_resultados.csv")
    st.subheader("Desempenho por item")
    items = []
    for i in range(1, 6 if form == PRACTICE else 41):
        code = f"P{i:02}" if form == TEST else f"p{i}"
        corrections = pd.to_numeric(sample[f"corr_{code}" if form == TEST else f"{code}_pontos"], errors="coerce")
        classified = corrections.isin([0, 1])
        answered = sample[f"respondido_{code}"].astype(bool)
        n = int(classified.sum())
        hits = int(corrections.eq(1).sum())
        items.append({"Item": code.upper(), "Classificáveis": n, "Acertos": hits,
                      "Erros": int((classified & answered & corrections.eq(0)).sum()),
                      "Omissões": int((classified & ~answered).sum()),
                      "Sem classificação": len(sample) - n,
                      "Acertos (%)": round(100 * hits / n, 1) if n else None})
    item_table = pd.DataFrame(items)
    st.caption(f"{item_table['Classificáveis'].sum()} respostas classificáveis de {len(sample) * len(item_table)} posições possíveis · {item_table['Sem classificação'].sum()} sem classificação.")
    item_valid = item_table[item_table["Classificáveis"].gt(0)]
    if not item_valid.empty:
        k1, k2, k3 = st.columns(3)
        k1.metric("Acertos classificados", int(item_valid["Acertos"].sum()))
        k2.metric("Erros classificados", int(item_valid["Erros"].sum()))
        k3.metric("Omissões classificáveis", int(item_valid["Omissões"].sum()))
        st.bar_chart(item_valid, x="Item", y="Acertos (%)", color="#087547")
    st.dataframe(item_table, hide_index=True)
    export_table("Descarregar análise por item", item_table, "aqa4_itens.csv")
    st.caption("O denominador por item inclui omissões classificáveis. Itens sem chave e registos sem correção ficam fora da taxa. As faixas do gráfico são descritivas.")


def profiles(data, labels):
    for form, fields in PROFILES.items():
        st.subheader(form)
        subset = data[data["Instrumento"].eq(form)]
        if form == "Alunos":
            subset = latest_student_records(subset)
        if subset.empty:
            st.info("Sem registos nos filtros selecionados.")
            continue
        selected = st.selectbox("Indicador", list(fields), format_func=fields.get, key=form)
        values = subset[selected].replace("", pd.NA).dropna()
        if selected == "linguas_casa":
            values = values.str.split().explode()
        display = values.map(lambda value: labels.get(form, {}).get(selected, {}).get(value, value))
        st.caption(f"{len(subset)} registos. {int(subset[selected].eq('').sum())} sem resposta. A pergunta de línguas aceita várias opções.")
        if not display.empty:
            st.bar_chart(display.value_counts().rename("Respostas"))


def quality(data, forms, errors, registry):
    rows = []
    for form, (_, student_field, _) in forms.items():
        if form in errors:
            continue
        subset = data[data["Instrumento"].eq(form)]
        keys = subset[subset["Escola"].ne("") & subset["Aluno"].ne("")]
        rows.append({"Instrumento": form, "Sem escola": int(subset["Escola"].eq("").sum()),
                     "Sem aluno": int(subset["Aluno"].eq("").sum()) if student_field else None,
                     "Sem associação à amostra": int(subset["Amostra"].isna().sum()),
                     "Repetições": int(keys.duplicated(["Escola", "Aluno"]).sum()) if student_field else None})
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    pending = data[data["Amostra"].isna() & data["Escola"].ne("")]
    if not pending.empty:
        st.subheader("Códigos por reconciliar")
        pending = pending.assign(Data=pending["Dia"].astype(str).replace("NaT", "Sem data"))
        review = pending.groupby(["Data", "Escola", "Instrumento"]).size().rename("Submissões").reset_index()
        review["Escola na base"] = review["Escola"].map(lambda code: registry.get(code, {}).get("Escola na base", "—"))
        review["Motivo"] = review["Escola"].map(lambda code: "Referência indisponível" if not registry else
                                                "Código fora da base" if code not in registry else
                                                "Código da amostra por reconciliar" if registry[code]["Selecionada"] else
                                                "Escola fora da seleção")
        st.dataframe(review.rename(columns={"Escola": "Código no Kobo"}), hide_index=True)
        st.caption("Os códigos são comparados como texto. Zeros à esquerda podem indicar um código diferente.")


SERVER = "https://kf.kobo.ucp-pch.org"
FORMS = {
    "Avaliação principal": ("am5akLzG7uLVbt5S4JGhbS", "aluno_id", "percentagem"),
    "Professores": ("aNRMWeskhSMjaUCArcCKhZ", None, None),
    "Alunos": ("aEYz6NxA5aVhmSg4kX6Fv7", "codigo_aluno", None),
    "Prática": ("aSxyCqJKffUeCinPkHdefE", "codigo_aluno", "percentagem_acertos"),
}
STUDENT_FORMS = ["Prática", "Alunos", "Avaliação principal"]
COLUMNS = ["Instrumento", "Escola", "Aluno", "Região declarada", "Enviado", "Pontuação"]
ITEM_FIELDS = ([f"corr_P{i:02}" for i in range(1, 41)] + [f"p{i}_pontos" for i in range(1, 6)] +
               ["pratica_completa"] + [f"{field}_{s}" for s in "ABC" for field in ("percent", "itens_chave")])
ANSWER_FIELDS = [f"P{i:02}" for i in range(1, 41)] + [f"p{i}" for i in range(1, 6)]
PROFILE_FIELDS = list(dict.fromkeys(field for fields in PROFILES.values() for field in fields))
COLUMNS += ["ID Kobo"] + ITEM_FIELDS + ["respondido_" + field for field in ANSWER_FIELDS] + PROFILE_FIELDS
ROOT = Path(__file__).resolve().parent


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def field(row, name):
    if not name:
        return ""
    if name in row:
        value = row[name]
    else:
        matches = [value for key, value in row.items() if key.rsplit("/", 1)[-1] == name]
        value = matches[0] if len(matches) == 1 else None
    return str(value).strip() if value is not None else ""


def fetch(token, form, specification):
    uid, student_field, score_field = specification
    endpoint = f"{SERVER}/api/v2/assets/{uid}/data/"
    path = urlsplit(endpoint).path
    url = endpoint + "?limit=500"
    seen = set()
    result = []
    opener = build_opener(NoRedirect)
    while url:
        parsed = urlsplit(url)
        if (parsed.scheme, parsed.netloc, parsed.path) != ("https", urlsplit(SERVER).netloc, path) or url in seen:
            raise ValueError("Paginação inválida")
        seen.add(url)
        request = Request(url, headers={"Authorization": f"Token {token}", "Accept": "application/json"})
        with opener.open(request, timeout=25) as response:
            page = json.load(response)
        for row in page["results"]:
            score = field(row, score_field)
            if score_field == "percentagem" and field(row, "itens_com_chave") == "0":
                score = ""
            result.append((form, field(row, "codigo_escola"), field(row, student_field),
                           field(row, "regiao"), field(row, "_submission_time"), score, field(row, "_id"),
                           *(field(row, key) for key in ITEM_FIELDS),
                           *(bool(field(row, key)) for key in ANSWER_FIELDS),
                           *(field(row, key) for key in PROFILE_FIELDS)))
        url = urljoin(url, page["next"]) if page.get("next") else None
    return result


def load_form(token, form, specification):
    try:
        return form, fetch(token, form, specification), None
    except HTTPError as error:
        return form, [], f"Kobo respondeu com HTTP {error.code}"
    except (URLError, TimeoutError, OSError):
        return form, [], "Servidor Kobo indisponível ou ligação interrompida"
    except (ValueError, KeyError, TypeError):
        return form, [], "Resposta inesperada da API do Kobo"


def refresh(token):
    records, errors = [], {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(load_form, token, name, spec) for name, spec in FORMS.items()]
        for future in futures:
            form, rows, error = future.result()
            records.extend(rows)
            if error:
                errors[form] = error
    return pd.DataFrame(records, columns=COLUMNS), errors, datetime.now(timezone.utc)


def prepare(records):
    data = records.copy()
    data["Enviado"] = pd.to_datetime(data["Enviado"], utc=True, errors="coerce", format="mixed")
    data["Dia"] = data["Enviado"].dt.date
    data["ID Kobo"] = pd.to_numeric(data["ID Kobo"], errors="coerce")
    data["Pontuação"] = pd.to_numeric(data["Pontuação"], errors="coerce")
    return data


def load_school_reference(path):
    try:
        reference = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return {}
    if not isinstance(reference, dict):
        return {}
    return {key: value for key, value in reference.items()
            if isinstance(value, dict) and isinstance(value.get("Selecionada"), bool)}


def main():
    st.set_page_config(page_title="AQA4 | Seguimento do piloto", page_icon=str(ROOT / "logo.png"), layout="wide")
    page, update = navigation(ROOT)
    token = os.environ.get("KOBO_API_TOKEN")
    if not token:
        try:
            token = st.secrets["KOBO_API_TOKEN"]
        except (FileNotFoundError, KeyError):
            st.error("Configura KOBO_API_TOKEN para ligar ao Kobo.")
            st.stop()
    snapshot = st.session_state.get("snapshot_painel")
    if update or snapshot is None or not set(COLUMNS).issubset(snapshot[0].columns):
        with st.spinner("A consultar os quatro projetos…"):
            snapshot = refresh(token)
            st.session_state.snapshot_painel = snapshot
    records, errors, timestamp = snapshot
    st.caption(f"KoboToolbox · Início do piloto em 09/11/2026 · Última consulta em Bissau {timestamp:%d/%m/%Y às %H:%M}")
    for form, error in errors.items():
        st.warning(f"{form} · {error}")
    objective(page)
    uploaded = st.session_state.get("aqa4_codigo_csv")
    if page == "Qualidade":
        with st.expander("Reconciliar códigos da amostra"):
            st.download_button("Descarregar lista de escolas", (ROOT / "escolas_aqa4.csv").read_bytes(),
                               "escolas_aqa4.csv", "text/csv")
            candidate = st.file_uploader("Carregar lista com códigos Kobo", type="csv")
            if candidate and st.button("Aplicar códigos"):
                try:
                    roster(ROOT / "escolas_aqa4.csv", candidate)
                except (ValueError, KeyError, UnicodeError) as error:
                    st.error(str(error))
                else:
                    uploaded = candidate
                    st.session_state.aqa4_codigo_csv = candidate
                    st.success("Códigos atualizados nesta sessão.")
            if uploaded and st.button("Restaurar IDs da base consolidada"):
                st.session_state.pop("aqa4_codigo_csv", None)
                uploaded = None
    try:
        plan = roster(ROOT / "escolas_aqa4.csv", uploaded)
    except (ValueError, KeyError, UnicodeError) as error:
        st.error(f"Não foi possível aplicar a lista de códigos. {error}")
        st.stop()
    data = associate(prepare(records), plan)
    data, plan = filter_analysis(data, plan, page)
    if page == "Visão geral":
        st.subheader("Submissões por instrumento")
        for form, col in zip(FORMS, st.columns(4)):
            col.metric(form, "Indisponível" if form in errors else int(data["Instrumento"].eq(form).sum()))
        total = len(data)
        schools_seen = data["Amostra"].nunique()
        today_count = int(data["Dia"].eq(datetime.now(timezone.utc).date()).sum())
        a, b, c = st.columns(3)
        a.metric("Submissões recebidas", total, help="Total dos quatro instrumentos nos filtros selecionados.")
        b.metric("Recebidas hoje", today_count)
        c.metric("Escolas da amostra com recolha", f"{schools_seen} / {len(plan)}")
        st.divider()
        trend = data.dropna(subset=["Dia"]).groupby(["Dia", "Instrumento"]).size().unstack(fill_value=0)
        if not trend.empty:
            st.subheader("Submissões por dia")
            st.line_chart(trend)
        st.subheader("Seguimento por aluno")
        if any(form in errors for form in STUDENT_FORMS):
            st.info("O cruzamento depende da leitura dos três instrumentos dos alunos.")
        else:
            identified = data[data["Instrumento"].isin(STUDENT_FORMS) & data["Escola"].ne("") & data["Aluno"].ne("")]
            matched = (identified.groupby(["Escola exibida", "Escola", "Aluno", "Instrumento"]).size()
                       .unstack(fill_value=0).reindex(columns=STUDENT_FORMS, fill_value=0).gt(0))
            matched["Com os três"] = matched.all(axis=1)
            st.metric("Alunos com os três instrumentos", int(matched["Com os três"].sum()))
            if not matched.empty:
                st.dataframe(matched.groupby(level="Escola exibida").sum().reset_index(), hide_index=True)
    elif page == "Cobertura da amostra":
        coverage(data, plan, FORMS, errors)
    elif page in (PRACTICE, TEST):
        analysis(data, page, errors.get(page))
    elif page == "Questionários":
        profiles(data, json.loads((ROOT / "rotulos.json").read_text(encoding="utf-8")))
    else:
        registry = load_school_reference(ROOT / "referencia_escolas.json")
        if not registry:
            st.warning("A referência das escolas está indisponível. Os códigos a reconciliar continuam visíveis.")
        quality(data, FORMS, errors, registry)
    with st.expander("Critérios de leitura"):
        st.caption("A vista inicial inclui todas as submissões disponíveis, incluindo testes. Nos módulos de análise, o período pode ser alterado no filtro local.")
        st.write("Painel descritivo do piloto. Os resultados da prática e do teste têm escalas e finalidades diferentes. A amostra corresponde às 20 escolas da lista recebida. O cruzamento usa códigos com zeros à esquerda preservados. Os resultados representam os registos recebidos no período.")


if __name__ == "__main__":
    main()

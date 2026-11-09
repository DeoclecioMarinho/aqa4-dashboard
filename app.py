from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import pandas as pd
import streamlit as st

SERVER = "https://kf.kobo.ucp-pch.org"
FORMS = {
    "Avaliação principal": ("am5akLzG7uLVbt5S4JGhbS", "aluno_id", "percentagem"),
    "Professores": ("aNRMWeskhSMjaUCArcCKhZ", None, None),
    "Alunos": ("aEYz6NxA5aVhmSg4kX6Fv7", "codigo_aluno", None),
    "Prática": ("aSxyCqJKffUeCinPkHdefE", "codigo_aluno", "percentagem_acertos"),
}
STUDENT_FORMS = ["Prática", "Alunos", "Avaliação principal"]
COLUMNS = ["Instrumento", "Escola", "Aluno", "Região declarada", "Enviado", "Pontuação"]
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
                           field(row, "regiao"), field(row, "_submission_time"), score))
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
    regions = defaultdict(set)
    for school, region in zip(data["Escola"], data["Região declarada"]):
        if school and region:
            regions[school].add(region)
    region_map = {
        school: next(iter(values)).replace("_", " ").capitalize() if len(values) == 1 else "Por confirmar"
        for school, values in regions.items()
    }
    data["Região"] = data["Escola"].map(region_map).fillna("Por confirmar")
    data["Dia"] = pd.to_datetime(data["Enviado"], utc=True, errors="coerce").dt.date
    data["Pontuação"] = pd.to_numeric(data["Pontuação"], errors="coerce")
    return data


def main():
    st.set_page_config(page_title="Seguimento AQA4", layout="wide")
    st.image(str(ROOT / "logo.png"), width=420)
    st.title("Seguimento do piloto AQA4")
    st.caption("Quatro instrumentos • Submissões recebidas pelo Kobo")
    token = os.environ.get("KOBO_API_TOKEN")
    if not token:
        try:
            token = st.secrets["KOBO_API_TOKEN"]
        except (FileNotFoundError, KeyError):
            st.error("Configura KOBO_API_TOKEN para ligar ao Kobo.")
            st.stop()
    update = st.button("Atualizar do Kobo", type="primary")
    if update or "snapshot" not in st.session_state:
        with st.spinner("A consultar os quatro projetos…"):
            st.session_state.snapshot = refresh(token)
    records, errors, timestamp = st.session_state.snapshot
    st.caption(f"Última consulta em Bissau · {timestamp:%d/%m/%Y %H:%M}")
    for form, error in errors.items():
        st.warning(f"{form} · {error}")
    data = prepare(records)
    with st.expander("Filtros", expanded=True):
        regions = st.multiselect("Região", sorted(data["Região"].unique()))
        regional = data[data["Região"].isin(regions)] if regions else data
        schools = st.multiselect("Código da escola", sorted(set(regional["Escola"]) - {""}))
        days = sorted(data["Dia"].dropna().unique())
        period = st.date_input("Período", (days[0], days[-1]), min_value=days[0], max_value=days[-1]) if days else ()
    if regions:
        data = data[data["Região"].isin(regions)]
    if schools:
        data = data[data["Escola"].isin(schools)]
    if len(period) == 2:
        data = data[data["Dia"].isna() | data["Dia"].between(*period)]
    for form, column in zip(FORMS, st.columns(4)):
        column.metric(form, "Indisponível" if form in errors else int(data["Instrumento"].eq(form).sum()))
    coverage, results, quality = st.tabs(["Cobertura", "Resultados", "Qualidade"])
    with coverage:
        st.subheader("Submissões por escola")
        if data.empty:
            st.info("Sem submissões para os filtros selecionados.")
        else:
            by_school = (data.assign(Escola=data["Escola"].replace("", "Sem código"))
                         .groupby(["Região", "Escola", "Instrumento"]).size().unstack(fill_value=0)
                         .reindex(columns=list(FORMS), fill_value=0))
            for form in errors:
                by_school[form] = "Indisponível"
            st.dataframe(by_school.reset_index(), hide_index=True)
            trend = data.dropna(subset=["Dia"]).groupby(["Dia", "Instrumento"]).size().unstack(fill_value=0)
            if not trend.empty:
                st.subheader("Submissões por dia")
                st.line_chart(trend)
        st.subheader("Seguimento dos alunos")
        if any(form in errors for form in STUDENT_FORMS):
            st.info("O cruzamento requer os três instrumentos dos alunos disponíveis.")
        else:
            identifiable = data[data["Instrumento"].isin(STUDENT_FORMS) & data["Escola"].ne("") & data["Aluno"].ne("")]
            if identifiable.empty:
                st.info("Ainda não há registos com os dois códigos preenchidos.")
            else:
                matching = (identifiable.groupby(["Escola", "Aluno", "Instrumento"]).size()
                            .unstack(fill_value=0).reindex(columns=STUDENT_FORMS, fill_value=0).gt(0))
                complete = matching.all(axis=1)
                st.metric("Alunos com os três instrumentos", int(complete.sum()))
                matching["Alunos com os três"] = complete
                st.dataframe(matching.groupby(level="Escola").sum().reset_index(), hide_index=True)
        st.caption("A cobertura mostra escolas com submissões. As metas dependem da lista oficial de códigos e do plano de recolha.")
    with results:
        for form in ["Avaliação principal", "Prática"]:
            st.subheader(form)
            subset = data[data["Instrumento"].eq(form)]
            scores = subset["Pontuação"]
            scores = scores[scores.between(0, 100)]
            if form in errors:
                st.info("Dados indisponíveis.")
            elif scores.empty:
                st.info("Sem pontuações válidas disponíveis nesta seleção.")
            else:
                st.metric("Percentagem média de acertos", f"{scores.mean():.1f}%")
                st.caption(f"{len(scores)} de {len(subset)} submissões com pontuação válida.")
    with quality:
        rows = []
        for form, (_, student_field, _) in FORMS.items():
            if form in errors:
                continue
            subset = data[data["Instrumento"].eq(form)]
            identifiable = subset[subset["Escola"].ne("") & subset["Aluno"].ne("")]
            rows.append({"Instrumento": form, "Sem código de escola": int(subset["Escola"].eq("").sum()),
                         "Sem código de aluno": int(subset["Aluno"].eq("").sum()) if student_field else None,
                         "Submissões repetidas": int(identifiable.duplicated(["Escola", "Aluno"]).sum()) if student_field else None})
        st.dataframe(pd.DataFrame(rows), hide_index=True)
        st.caption("As repetições contam os registos adicionais com os mesmos códigos no mesmo instrumento.")


if __name__ == "__main__":
    main()

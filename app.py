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

from interface import navigation, objective, filter_analysis
from modulos import PRACTICE, TEST, PROFILES, analysis, associate, coverage, profiles, quality, roster

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


def main():
    st.set_page_config(page_title="AQA4 | Seguimento do piloto", page_icon="📊", layout="wide")
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
        quality(data, FORMS, errors, json.loads((ROOT / "referencia_escolas.json").read_text(encoding="utf-8")))
    with st.expander("Critérios de leitura"):
        st.caption("A vista inicial inclui todas as submissões disponíveis, incluindo testes. Nos módulos de análise, o período pode ser alterado no filtro local.")
        st.write("Painel descritivo do piloto. Os resultados da prática e do teste têm escalas e finalidades diferentes. A amostra corresponde às 20 escolas da lista recebida. O cruzamento usa códigos com zeros à esquerda preservados. Os resultados representam os registos recebidos no período.")


if __name__ == "__main__":
    main()

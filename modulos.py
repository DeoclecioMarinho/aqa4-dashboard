from io import BytesIO
import re
import unicodedata

import pandas as pd
import streamlit as st

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
    st.header(form)
    if error:
        st.warning(error)
        return
    sample = latest_student_records(data[data["Instrumento"].eq(form)])
    valid = sample[sample["Pontuação"].between(0, 100)]
    a, b, c, d = st.columns(4)
    a.metric("Registos analisados", len(sample))
    b.metric("Com pontuação", len(valid))
    c.metric("Média de acertos", f"{valid['Pontuação'].mean():.1f}%" if len(valid) else "—")
    d.metric("Mediana", f"{valid['Pontuação'].median():.1f}%" if len(valid) else "—")
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
        st.dataframe(pd.DataFrame(sections), hide_index=True)
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
    st.dataframe(pd.DataFrame(items), hide_index=True)
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


def quality(data, forms, errors):
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
        st.dataframe(pending.groupby(["Escola", "Instrumento"]).size().rename("Submissões").reset_index(), hide_index=True)

# Dashboard de seguimento AQA4

Painel em Streamlit com leitura direta dos quatro projetos do KoboToolbox do PCH.

## Módulos

- **Visão geral** — submissões recebidas por instrumento e dia, e seguimento dos alunos nos três instrumentos individuais.
- **Cobertura da amostra** — 20 escolas selecionadas em 10 unidades, com setor, ID, estado de recolha e descarga da tabela.
- **Prática** — pontuação, completude, distribuição dos resultados e acertos, erros e omissões por item.
- **Avaliação principal** — pontuação global, resultados por secção A, B e C, distribuição, resultados por escola e análise dos 40 itens.
- **Questionários** — indicadores de perfil de alunos e professores com as designações do XLSForm.
- **Qualidade** — códigos em falta, repetições e códigos Kobo sem associação à amostra.

## Abrir

Com Python 3.10 ou superior, executar:

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Configurar KOBO_API_TOKEN como variável de ambiente ou copiar .streamlit/secrets.example.toml para .streamlit/secrets.toml e preencher a chave. No Streamlit Cloud, usar app.py como ficheiro principal e configurar o token nos segredos do serviço. Restringir o acesso à equipa autorizada. O painel é consultável no navegador do PC e do Android onde o alojamento estiver acessível.

## Como interpretar

Os IDs em escolas_aqa4.csv vêm da coluna id da aba Base consolidada da lista oficial. O painel associa esse ID ao codigo_escola do Kobo, como texto. Quando o campo contém o nome completo da escola, é aceite uma correspondência por nome normalizado e único. O módulo Qualidade indica códigos ainda sem associação. Para reconciliar códigos diferentes dos IDs da lista, descarregar a lista no painel, ajustar os códigos confirmados e voltar a carregá-la. A lista carregada fica na sessão. Para torná-la a configuração padrão, substituir escolas_aqa4.csv.

As contagens de cobertura mostram todas as submissões recebidas. O cruzamento de alunos usa o par código da escola e código do aluno. Nos resultados de prática e teste, conta a última submissão de cada par no período. Registos sem os dois códigos ficam separados. O indicador de média usa apenas pontuações válidas. Os itens sem classificação ficam fora do denominador por item. As omissões de itens classificáveis entram no denominador. As médias de prática e avaliação principal são apresentadas em módulos distintos.

Os CSV descarregados são resumos agregados. O pacote não inclui credenciais ou submissões. A lista das escolas selecionadas faz parte do projeto. O ficheiro .streamlit/secrets.toml está excluído do Git.

## Período de consulta

O piloto começa em 09/11/2026. A vista inicial mostra todos os registos disponíveis no Kobo, incluindo testes. Usar o filtro de data para restringir o período.

## Navegação e filtros

O menu lateral contém os módulos e o botão de atualização do Kobo. Os filtros de região, escola e data ficam dentro de cada análise. Em Qualidade, a tabela distingue códigos fora da base de códigos de escolas conhecidas fora da seleção, a partir de referencia_escolas.json.

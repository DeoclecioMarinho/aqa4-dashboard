# Painel de seguimento AQA4

O painel lê os quatro projetos através da API v2 do Kobo do PCH. Usa o botão **Atualizar do Kobo** para consultar as submissões mais recentes.

## Abrir no PC

Com Python 3.10 ou superior, abrir o terminal nesta pasta. Copiar .streamlit/secrets.example.toml para .streamlit/secrets.toml e preencher o token localmente. Depois executar:

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py --server.address 127.0.0.1
```

Abrir http://localhost:8501 no navegador. O botão de atualização consulta os quatro projetos.

## Consultar no Android

Para acesso pela mesma rede Wi-Fi, iniciar com `--server.address 0.0.0.0` numa rede de confiança e abrir `http://IP_DO_PC:8501` no Android. O PC deve continuar ligado. Para acesso fora da rede, alojar o painel num servidor com HTTPS e autenticação.

## Configuração e critérios

O token é lido de `KOBO_API_TOKEN` ou de `.streamlit/secrets.toml`. Mantém esse ficheiro local e fora de partilhas e repositórios. A chave fornecida no chat deve ser substituída no Kobo e na configuração local.

O cruzamento usa o código da escola e do aluno tal como foram registados, removendo espaços nas extremidades e preservando zeros iniciais. A região resulta dos questionários de alunos e professores. Códigos sem associação ou com regiões divergentes ficam em «Por confirmar». As escolas sem submissões poderão entrar no painel quando houver uma lista oficial de códigos e metas. As médias são calculadas por submissão com pontuação válida, incluindo submissões repetidas. O painel apresenta totais e dados por escola. Os nomes dos docentes e códigos dos alunos ficam fora das tabelas apresentadas.

## Publicar o código no GitHub

Extrair o ZIP e enviar o conteúdo desta pasta para o repositório. Incluir .gitignore e a pasta .streamlit com o ficheiro de exemplo. Usar app.py como ficheiro de entrada. Se alojar o painel, configurar KOBO_API_TOKEN nos segredos do serviço de alojamento e limitar o acesso ao painel à equipa autorizada. Publicar o código no GitHub e alojar a aplicação são passos separados.

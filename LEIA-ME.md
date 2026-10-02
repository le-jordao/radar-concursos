# Radar de Concursos

Rastreia editais que vão abrir ou que ameaçam abrir perto de Cabo Frio, pontua cada um
pelo seu perfil (engenheiro civil, ex-SEME), mostra o conteúdo que os concursos têm em
comum e monta a ordem de estudo.

Não precisa instalar nada além do Python. Nenhuma biblioteca externa.

## Começar

Clique duas vezes em **`Abrir Radar.bat`**. O navegador abre sozinho em
`http://127.0.0.1:8777`. Para fechar, feche a janela preta.

Para o radar varrer as fontes sozinho todo dia útil às 07:00, clique uma vez em
**`Agendar seg-sex.bat`**. Sábado e domingo ele não roda — está travado no código,
não só no agendador. `Desagendar.bat` desliga.

## As quatro abas

**Decidir** — todos os concursos ordenados por nota de 0 a 100. A nota soma cinco
coisas: aderência ao seu perfil (35), proximidade de Cabo Frio (25), chance de passar
(20), salário (10) e quão perto está de abrir (10). O botão *Por que esta nota* abre a
conta item por item, para você discordar com argumento.

Marque **Vou fazer** nos que aceitar. As outras abas passam a considerar só esses.

**Conteúdo em comum** — a barra de cada matéria mostra em quantos dos seus concursos
ela cai. A matriz mostra, para cada dupla, quanto do conteúdo é o mesmo. Acima de 75%
dá para preparar as duas provas quase como uma só. Conteúdo local (Lei Orgânica,
história do município) fica fora da conta, porque não se aproveita de um município
para outro.

**Plano de estudo** — a ordem que rende mais: primeiro o que cobre mais provas e pesa
mais na nota. Clique numa matéria para ver o conteúdo programático completo e a dica
de abordagem. O que você marcar como feito fica salvo no navegador.

**Sinais** — as notícias que o rastreador capturou: autorização de concurso, comissão
formada, banca contratada, edital publicado. É aqui que aparece o concurso que ainda
não tem edital mas está se mexendo.

## Linha de comando

```
python app.py              abre a interface
python app.py rastrear     varre as fontes agora
python app.py listar       ranking no terminal
python app.py exportar     gera web/dados.json (versão estática, para hospedar)
```

`rastrear --forcar` ignora a trava de fim de semana.

## Como ele acha os editais

A varredura monta cerca de 50 buscas a partir do seu perfil — todo município dentro de
180 km, todo órgão já no radar, mais buscas abertas por "engenheiro civil" e "fiscal de
obras" — e lê o feed de notícias do Google para cada uma. Cada manchete é classificada
em uma fase (aberto, edital publicado, autorizado, previsto) e recebe uma nota de
relevância que leva em conta o cargo citado, a distância do município e a data. O que
fica abaixo do corte é descartado; notícia com mais de 150 dias também.

Foi assim que o radar achou, na primeira rodada, que Engenheiro Paulo de Frontin tinha
prorrogado as inscrições e que a Câmara de São Pedro da Aldeia já tinha banca definida.

## Ajustar ao seu gosto

Tudo que define o comportamento está em `dados/`, em arquivos de texto:

- **`perfil.json`** — seu raio de deslocamento, os cargos de cada trilha, o que excluir,
  salário mínimo aceitável. Mexer aqui muda as notas de todo mundo.
- **`concursos.json`** — a base de concursos. `confianca: "confirmado"` tem fonte
  pública citada; `"estimado"` é projeção pelo ciclo histórico do órgão, serve de alerta
  antecipado e não de fato.
- **`disciplinas.json`** — o conteúdo programático e quantas horas cada matéria pede.
  É o que alimenta a matriz e o plano.
- **`municipios.json`** — distâncias a partir de Cabo Frio.

`dados/radar.db` guarda os sinais capturados e as suas decisões. Apagar esse arquivo
zera o histórico, sem afetar o resto.

## Os limites, ditos claramente

O rastreador lê manchetes, não diários oficiais. Ele é bom para avisar cedo e ruim para
ser a sua única fonte: **antes de pagar qualquer taxa, abra o edital no site da banca.**

Os concursos marcados como `estimado` não têm edital nem data. Entraram porque o ciclo
do órgão sugere que vêm, não porque alguém anunciou.

As horas de cada matéria são uma estimativa de carga para quem já tem a base de
engenharia — não são uma medida de nada, só uma régua para comparar matérias entre si.

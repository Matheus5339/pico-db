# pico-db

[![CI](https://github.com/Matheus5339/pico-db/actions/workflows/ci.yml/badge.svg)](https://github.com/Matheus5339/pico-db/actions/workflows/ci.yml)

Um pequeno banco de dados relacional com **motor de SQL próprio**, escrito do zero
em Python — sem ORM, sem `sqlite3`, sem gerador de parser. Ele recebe texto SQL,
tokeniza, faz o parsing para uma AST e executa essa AST sobre uma camada de storage
plugável.

O objetivo não é substituir o Postgres. É mostrar que eu entendo o que um banco de
dados *faz internamente* — como uma consulta vai do texto até um conjunto de
resultados, por que índices deixam buscas rápidas, e quanto durabilidade
realmente custa.

```
pico-db> CREATE TABLE users (id INT, name TEXT, age INT);
Tabela 'users' criada
pico-db> INSERT INTO users VALUES (1, 'alice', 30);
1 linha afetada
pico-db> INSERT INTO users VALUES (2, 'bob', 25);
1 linha afetada
pico-db> SELECT name, age FROM users WHERE age > 26 ORDER BY age DESC;
name  | age
------+----
alice | 30
(1 linha)
```

## Motivação

Escrevi do zero — sem ORM, sem `sqlite3`, sem gerador de parser — para entender
como um banco relacional funciona por dentro: como uma consulta vai do texto até um
conjunto de resultados e por que índices deixam buscas rápidas. Usar uma biblioteca
pronta esconderia justamente a parte que eu queria aprender.

## Começando

Requer Python ≥ 3.10 e [uv](https://docs.astral.sh/uv/).

```bash
# Inicia um REPL em memória
uv run pico-db

# Ou persiste em um arquivo JSON
uv run pico-db meusdados.json

# Roda a suíte de testes
uv run --extra dev pytest

# Lint
uv run --extra dev ruff check .
```

Sem uv? `pip install -e ".[dev]"` e então `pico-db` / `pytest` funcionam igual.

## Uso

Além do REPL, o motor é usável como biblioteca Python. `Database.execute()` recebe
uma instrução SQL e devolve um `ResultSet` (para `SELECT`), a contagem de linhas
afetadas (para `INSERT` / `UPDATE` / `DELETE`) ou uma string de status (para
`CREATE TABLE`):

```python
from picodb import Database

db = Database()  # em memória; use Database.open("dados.json") para persistir em disco

db.execute("CREATE TABLE users (id INT, name TEXT, age INT)")
db.execute("INSERT INTO users VALUES (1, 'alice', 30)")
db.execute("INSERT INTO users VALUES (2, 'bob', 25)")

result = db.execute("SELECT name, age FROM users WHERE age > 26")
print(result.columns)      # ['name', 'age']
for row in result:         # ResultSet é iterável
    print(row)             # ['alice', 30]

# Índice hash: transforma WHERE col = valor de O(n) em O(1) em média
db.create_index("users", "name")
db.execute("SELECT id FROM users WHERE name = 'alice'")
```

## O que é suportado

| Categoria | Suportado |
|-----------|-----------|
| DDL       | `CREATE TABLE` com colunas `INT` / `TEXT` |
| DML       | `INSERT` (posicional e nomeado), `UPDATE`, `DELETE` |
| Consultas | `SELECT` com projeção ou `*` |
| Filtros   | `WHERE` com `= != < > <= >=`, `AND`, `OR`, parênteses |
| Ordenação | `ORDER BY ... ASC/DESC`, `LIMIT` |
| Agregações| `COUNT`, `SUM`, `AVG`, `MIN`, `MAX`, `GROUP BY` |
| Índices   | Índice hash em uma coluna para buscas por igualdade O(1) |

## Como funciona

O motor é um pipeline clássico de quatro estágios, um módulo por estágio:

```
texto SQL
  │  lexer.py      tokenizador escrito à mão → [Token]
  ▼
tokens
  │  parser.py     parser de descida recursiva → AST
  ▼
AST (ast_nodes.py)
  │  executor.py   avalia a AST sobre as tabelas
  ▼
ResultSet          ← storage.py persiste, index.py acelera
```

`database.py` é a fachada que costura tudo e é dona da persistência e da política
de índices, para que todos os outros módulos permaneçam puros e testáveis de forma
independente.

## Decisões de arquitetura (o *porquê*)

- **Lexer e parser de descida recursiva escritos à mão**, e não um gerador de
  parser. A gramática é pequena, e escrevê-la à mão mantém as mensagens de erro
  precisas (elas carregam a posição do caractere) e o SQL suportado legível direto
  nos métodos do parser. É também a parte que melhor demonstra o conceito.

- **A AST é dado puro** (dataclasses congeladas sem comportamento). Toda a
  semântica de runtime vive no executor. Isso torna o parser trivial de testar —
  você faz asserções sobre a árvore — e permite que executores alternativos
  reutilizem a mesma AST.

- **Storage é uma interface, não um formato de arquivo.** O executor depende de uma
  `Storage` abstrata; `JSONStorage` e `MemoryStorage` são implementações trocáveis.
  O JSON foi escolhido para o MVP porque é inspecionável e fácil de depurar. Um
  motor paginado append-only poderia entrar depois sem tocar em uma linha do
  executor.

- **Escritas atômicas.** O `JSONStorage` escreve em um arquivo temporário e faz
  `os.replace()` para o lugar, de modo que uma falha no meio da escrita nunca pode
  corromper o banco — você fica com o arquivo antigo ou com o novo, nunca com um
  escrito pela metade.

- **Índice hash mantido por reconstrução.** O índice guarda as linhas *por
  referência* e é reconstruído após cada mutação. A reconstrução é O(n), mas as
  escritas já pagam O(n) pela persistência JSON, então não há regressão
  assintótica — e o caminho quente (`SELECT WHERE col = x`) cai de O(n) para O(1)
  em média. O índice é uma otimização pura: o predicado é sempre reavaliado, então
  um índice desatualizado ou ausente nunca pode retornar uma resposta errada.

## Desempenho: o índice ajuda mesmo?

`benchmarks/index_benchmark.py` constrói uma tabela e cronometra a mesma consulta
`WHERE col = valor` com e sem um índice hash:

```bash
uv run python benchmarks/index_benchmark.py
```

Rodando com o padrão (50.000 linhas, 1.000 buscas por igualdade) nesta máquina:

| Cenário | Tempo (1.000 buscas) |
|---------|----------------------|
| Sem índice (varredura O(n)) | ~36 s |
| Com índice hash (O(1) em média) | ~1,2 s |
| **Ganho** | **~30x mais rápido** |

Os tempos absolutos variam conforme a máquina (medi de ~30x a ~35x em execuções
repetidas), mas a relação se mantém — e cresce com o tamanho da tabela: a varredura
é O(n) por busca, o índice O(1) em média. É um número concreto e defensável, a razão
exata pela qual um banco de dados real constrói índices, reproduzida a partir de
primeiros princípios.

## Trade-offs conhecidos / o que não foi implementado

Deliberadamente fora do escopo de um MVP focado — cada item é uma funcionalidade
real de banco que eu escolhi não fingir:

- **Sem `JOIN`.** Apenas consultas de uma tabela. Um join por laço aninhado é o
  próximo passo natural e a AST já isola a cláusula `FROM` para isso.
- **Reescrita do arquivo inteiro a cada escrita.** Toda mutação re-serializa o
  arquivo JSON inteiro. Ótimo para um demo, errado para escala — um formato
  paginado, append-only com write-ahead log é a solução de verdade (e o
  desdobramento mais interessante).
- **Índice hash = só igualdade.** Sem varreduras de intervalo; isso exige uma
  B-tree.
- **Índices via API Python, não SQL `CREATE INDEX`.** A lógica de manutenção é a
  parte difícil e ela está pronta; expor como SQL é mecânico.
- **Dois tipos (`INT`, `TEXT`), sem constraints.** Sem `NULL`/`NOT NULL`,
  `PRIMARY KEY` ou `FLOAT`. `NULL` existe como valor com semântica simplificada de
  lógica de três valores (qualquer comparação com `NULL` é falsa).
- **Uma instrução por vez; sem transações.**

## Estrutura do projeto

```
pico-db/
├── src/picodb/
│   ├── lexer.py        # texto SQL → tokens
│   ├── parser.py       # tokens → AST (descida recursiva)
│   ├── ast_nodes.py    # dataclasses dos nós da AST
│   ├── executor.py     # roda a AST, toda a semântica de runtime
│   ├── storage.py      # interface Storage + backends JSON / em memória
│   ├── index.py        # índice hash
│   ├── database.py     # fachada que costura tudo
│   └── cli.py          # REPL interativo
├── tests/              # pytest: um arquivo por camada + casos de borda
├── benchmarks/         # tempos de índice vs. varredura completa
└── pyproject.toml      # dependências e tooling (gerenciado com uv)
```

## Licença

MIT

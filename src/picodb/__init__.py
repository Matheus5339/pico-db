"""pico-db: um pequeno banco de dados relacional com motor de SQL próprio.

Pipeline: texto SQL -> lexer (tokens) -> parser (AST) -> executor (sobre o storage).
O ponto de entrada público é :class:`picodb.database.Database`.
"""

from picodb.database import Database
from picodb.errors import ExecutionError, ParseError, PicoDBError

__all__ = ["Database", "PicoDBError", "ParseError", "ExecutionError"]
__version__ = "0.1.0"

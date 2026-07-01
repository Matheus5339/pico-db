"""Hierarquia de erros do pico-db.

Uma única raiz (:class:`PicoDBError`) permite que a CLI capture tudo o que é
voltado ao usuário, mantendo tipos específicos para os testes e mensagens mais
claras.
"""


class PicoDBError(Exception):
    """Classe base para todo erro que o motor levanta em entrada inválida."""


class LexError(PicoDBError):
    """Levantado quando o lexer encontra um caractere que não sabe tokenizar."""


class ParseError(PicoDBError):
    """Levantado quando os tokens não formam uma instrução válida."""


class ExecutionError(PicoDBError):
    """Levantado em tempo de execução (tabela inexistente, tipo incompatível...)."""

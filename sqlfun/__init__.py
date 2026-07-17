from .core import SqlFun
from .naming import SqlFunError

# Backward-compatible alias for the pre-introspection error name.
SqlFunParseError = SqlFunError

__all__ = ['SqlFun', 'SqlFunError', 'SqlFunParseError']

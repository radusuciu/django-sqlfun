from __future__ import annotations

import re
from dataclasses import dataclass

import sqlparse

PARAM_MODES = ('in', 'out', 'inout', 'variadic')

CREATE_FUNCTION_RE = re.compile(
    r'CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+'
    r'(?P<name>(?:"[^"]+"|[\w$]+)(?:\s*\.\s*(?:"[^"]+"|[\w$]+))?)\s*\(',
    re.IGNORECASE,
)

RETURNS_RE = re.compile(r'\s*RETURNS\s+', re.IGNORECASE)

RETURNS_TABLE_RE = re.compile(r'TABLE\s*\(', re.IGNORECASE)

# Keywords that can follow the RETURNS type in a CREATE FUNCTION statement.
RETURNS_TERMINATORS = frozenset({
    'as', 'begin', 'called', 'cost', 'external', 'immutable', 'language',
    'leakproof', 'not', 'parallel', 'returns', 'rows', 'security', 'set',
    'stable', 'strict', 'support', 'transform', 'volatile', 'window',
})


class SqlFunParseError(ValueError):
    """Raised when a function signature cannot be parsed from a SQL definition."""


@dataclass(frozen=True)
class Parameter:
    definition: str
    mode: str = 'in'


@dataclass(frozen=True)
class FunctionSignature:
    name: str
    parameters: tuple[Parameter, ...]
    returns: str

    @property
    def drop_clause(self) -> str:
        """Render ``name(input params)`` in the form DROP FUNCTION accepts.

        OUT parameters are not part of a function's identity and must be
        omitted; DEFAULT expressions were already stripped during parsing.
        """
        parts = []
        for parameter in self.parameters:
            if parameter.mode == 'out':
                continue
            prefix = f'{parameter.mode} ' if parameter.mode in ('inout', 'variadic') else ''
            parts.append(f'{prefix}{parameter.definition}')
        return f'{self.name}({", ".join(parts)})'


def parse_function_signature(sql: str) -> FunctionSignature:
    # Comments are only meaningful to a human reader, but they are valid
    # anywhere whitespace is allowed in the statement header and parameter
    # list, which would otherwise confuse the regex/paren matching below.
    # strip_comments preserves comment-like text inside dollar-quoted
    # bodies and single-quoted strings, so it's safe to parse from here on.
    # Error messages still quote the original ``sql`` since that's what the
    # caller passed in and will recognize.
    uncommented = sqlparse.format(sql, strip_comments=True)
    match = CREATE_FUNCTION_RE.search(uncommented)
    if not match:
        raise SqlFunParseError(
            'Could not parse a CREATE FUNCTION statement with a parenthesized '
            f'parameter list from SQL definition:\n{sql}'
        )
    name = _normalize_identifier(match.group('name'))
    parameter_text, params_end = _extract_parenthesized(
        uncommented, match.end() - 1, original_sql=sql
    )
    parameters = tuple(
        _parse_parameter(part) for part in _split_top_level(parameter_text)
    )
    returns = _parse_returns(uncommented, params_end, original_sql=sql)
    return FunctionSignature(name=name, parameters=parameters, returns=returns)


def _normalize_identifier(name: str) -> str:
    name = re.sub(r'\s*\.\s*', '.', name.strip())
    if '"' in name:
        return name
    return name.lower()


def _normalize(text: str) -> str:
    """Lowercase outside double quotes, collapse whitespace, and remove
    spaces adjacent to parens, brackets, and commas."""
    parts = re.split(r'("[^"]*")', text)
    lowered = ''.join(
        part if part.startswith('"') else part.lower()
        for part in parts
    )
    collapsed = re.sub(r'\s+', ' ', lowered).strip()
    return re.sub(r'\s*([(),\[\]])\s*', r'\1', collapsed)


def _extract_parenthesized(
    sql: str, open_index: int, original_sql: str | None = None
) -> tuple[str, int]:
    """Return the text inside the paren group opening at ``open_index`` and
    the index just past its closing paren. Respects single-quoted strings.

    ``original_sql`` is quoted in error messages instead of ``sql`` when given,
    so callers that pass a comment-stripped ``sql`` can still surface the
    original SQL the caller recognizes.
    """
    depth = 0
    in_string = False
    for i in range(open_index, len(sql)):
        char = sql[i]
        if in_string:
            if char == "'":
                in_string = False
        elif char == "'":
            in_string = True
        elif char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
            if depth == 0:
                return sql[open_index + 1:i], i + 1
    raise SqlFunParseError(f'Unbalanced parentheses in SQL definition:\n{original_sql or sql}')


def _split_top_level(text: str) -> list[str]:
    """Split on commas that are not nested inside parens, brackets, or
    single-quoted strings."""
    if not text.strip():
        return []
    parts = []
    current = []
    depth = 0
    in_string = False
    for char in text:
        if in_string:
            current.append(char)
            if char == "'":
                in_string = False
        elif char == "'":
            in_string = True
            current.append(char)
        elif char in '([':
            depth += 1
            current.append(char)
        elif char in ')]':
            depth -= 1
            current.append(char)
        elif char == ',' and depth == 0:
            parts.append(''.join(current).strip())
            current = []
        else:
            current.append(char)
    parts.append(''.join(current).strip())
    return parts


def _strip_default(text: str) -> str:
    """Remove a trailing ``DEFAULT expr`` or ``= expr`` from a parameter."""
    depth = 0
    in_string = False
    for i, char in enumerate(text):
        if in_string:
            if char == "'":
                in_string = False
        elif char == "'":
            in_string = True
        elif char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
        elif depth == 0:
            if char == '=':
                return text[:i].strip()
            if char in 'dD' and _matches_keyword(text, i, 'default'):
                return text[:i].strip()
    return text.strip()


def _matches_keyword(text: str, start: int, keyword: str) -> bool:
    end = start + len(keyword)
    if text[start:end].lower() != keyword:
        return False
    before = text[start - 1] if start > 0 else ' '
    after = text[end] if end < len(text) else ' '
    is_word_char = lambda c: c.isalnum() or c == '_'  # noqa: E731
    return not is_word_char(before) and not is_word_char(after)


def _parse_parameter(text: str) -> Parameter:
    without_default = _strip_default(text)
    if not without_default:
        raise SqlFunParseError(f'Could not parse function parameter: {text!r}')
    normalized = _normalize(without_default)
    first_word, _, rest = normalized.partition(' ')
    if first_word in PARAM_MODES and rest:
        return Parameter(definition=rest, mode=first_word)
    return Parameter(definition=normalized)


def _parse_returns(sql: str, start: int, original_sql: str | None = None) -> str:
    match = RETURNS_RE.match(sql, start)
    if not match:
        raise SqlFunParseError(
            f'Could not find a RETURNS clause in SQL definition:\n{original_sql or sql}'
        )
    table_match = RETURNS_TABLE_RE.match(sql, match.end())
    if table_match:
        columns, _ = _extract_parenthesized(sql, table_match.end() - 1, original_sql=original_sql)
        return _normalize(f'table({columns})')
    words = []
    for word_match in re.finditer(r'\S+', sql[match.end():]):
        word = word_match.group()
        stripped = word.rstrip(';')
        if not stripped or stripped.lower() in RETURNS_TERMINATORS or stripped.startswith('$'):
            break
        words.append(stripped)
        if stripped != word:
            break
    if not words:
        raise SqlFunParseError(
            f'Could not parse the RETURNS clause in SQL definition:\n{original_sql or sql}'
        )
    return _normalize(' '.join(words))

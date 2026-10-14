"""Annotation scanner for C/C++ and Python sources and tests.

A tag applies to the innermost function enclosing it, otherwise to the function
immediately following it (only blank lines, comments or decorators between).
A block containing @file applies to the whole file. Anything else is an error:
misattributing a trace link is worse than missing one.
"""
import ast
import bisect
import io
import re
import tokenize
from collections import defaultdict
from dataclasses import dataclass, field

KEY_RE = re.compile(r"^[A-Z][A-Z0-9]*-[A-Z0-9][A-Z0-9._-]*$")
TAG_RE = re.compile(r"@(satisfies|implements|verifies|infrastructure|test-level|file)\b([^@]*)")
KEY_TAGS = {"satisfies", "implements", "verifies"}
ROLE_TAGS = {
    "source": {"satisfies", "implements", "infrastructure", "file"},
    "test": {"verifies", "test-level", "file"},
}
C_TEST_MACROS = {"ZTEST", "ZTEST_F", "ZTEST_USER", "ZTEST_USER_F", "TEST", "TEST_F", "TEST_P"}
C_NOT_FUNCTIONS = {"if", "for", "while", "switch", "return", "else", "do", "sizeof", "case", "defined"}


@dataclass
class Tag:
    tag: str
    value: str
    line: int


@dataclass
class Symbol:
    name: str
    start: int
    end: int
    kind: str              # function | test | class
    parent: str | None = None


@dataclass
class Unit:
    """A code unit (role=source) or test case (role=test) with its resolved tags."""
    path: str
    symbol: str | None
    start: int
    end: int
    satisfies: list = field(default_factory=list)
    implements: list = field(default_factory=list)
    verifies: list = field(default_factory=list)
    infrastructure: str | None = None
    test_level: str | None = None
    tag_lines: dict = field(default_factory=dict)   # key -> line declared, for link provenance


def _clean(value):
    return re.sub(r"""(\*/|\"\"\"|''')\s*$""", "", value).strip().rstrip("*").strip()


_DECORATION = re.compile(r"^\s*(?:/\*+|\*+(?!/)|//+|#+|\"\"\"|''')?\s*")


def _tags_in(lines_with_numbers):
    """Find tags line by line. Untagged lines directly after @infrastructure continue its reason,
    up to a blank line or the next tag."""
    tags, open_reason = [], False
    for lineno, text in lines_with_numbers:
        found = list(TAG_RE.finditer(text))
        if found:
            tags += [Tag(m.group(1), _clean(m.group(2)), lineno) for m in found]
            open_reason = tags[-1].tag == "infrastructure"
            continue
        rest = _clean(_DECORATION.sub("", text, count=1))
        if open_reason and rest:
            tags[-1].value = f"{tags[-1].value} {rest}".strip()
        else:
            open_reason = False
    return tags


# ------------------------------------------------------------------ C / C++

def _blank(chars, a, b):
    for k in range(a, b):
        if chars[k] != "\n":
            chars[k] = " "


def _strip_c(text):
    """Return (code view with comments/strings/preprocessor blanked, [(start_off, end_off)] of comments)."""
    chars, comments = list(text), []
    i, n = 0, len(text)
    while i < n:
        c, nxt = text[i], text[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            j = text.find("\n", i)
            j = n if j == -1 else j
            comments.append((i, j))
            _blank(chars, i, j)
            i = j
        elif c == "/" and nxt == "*":
            j = text.find("*/", i + 2)
            j = n if j == -1 else j + 2
            comments.append((i, j))
            _blank(chars, i, j)
            i = j
        elif c in "\"'":
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            j = min(j + 1, n)
            _blank(chars, i, j)
            i = j
        else:
            i += 1
    code = "".join(chars)
    out, continuing = [], False
    for line in code.splitlines(keepends=True):
        if continuing or line.lstrip().startswith("#"):
            continuing = line.rstrip("\n").rstrip().endswith("\\")
            out.append("".join("\n" if ch == "\n" else " " for ch in line))
        else:
            out.append(line)
    return "".join(out), comments


_C_FUNC = re.compile(
    r"^[ \t]*"
    r"(?P<prefix>(?:[A-Za-z_]\w*[\s\*&]+)*?)"      # storage class, return type, pointers; may span lines
    r"(?P<name>[A-Za-z_~][\w:~]*)\s*"
    r"\((?P<args>[^;{}()]*(?:\([^;{}()]*\)[^;{}()]*)*)\)\s*"
    r"(?:const\s*)?(?:noexcept\s*)?"
    r"\{",
    re.M,
)


def _match_brace(code, open_at):
    depth = 0
    for k in range(open_at, len(code)):
        if code[k] == "{":
            depth += 1
        elif code[k] == "}":
            depth -= 1
            if depth == 0:
                return k
    return len(code) - 1


def _c_symbols(code, line_of):
    syms, pos = [], 0
    while True:
        m = _C_FUNC.search(code, pos)
        if not m:
            break
        name = m.group("name")
        if name in C_NOT_FUNCTIONS:
            pos = m.end()
            continue
        close = _match_brace(code, m.end() - 1)
        start = line_of(m.start("prefix") if m.group("prefix").strip() else m.start("name"))
        end = line_of(close)
        if name in C_TEST_MACROS:
            args = [a.strip() for a in m.group("args").split(",")]
            if len(args) >= 2 and all(re.fullmatch(r"\w+", a) for a in args[:2]):
                syms.append(Symbol(f"{args[0]}.{args[1]}", start, end, "test"))
        else:
            syms.append(Symbol(name, start, end, "function"))
        pos = close + 1
    return syms


def _scan_c(path, text):
    code, comment_spans = _strip_c(text)
    starts = [0] + [i + 1 for i, ch in enumerate(text) if ch == "\n"]

    def line_of(off):
        return bisect.bisect_right(starts, off)

    symbols = _c_symbols(code, line_of)
    raw_lines = text.splitlines()
    code_lines = code.splitlines()
    blocks = []
    for a, b in comment_spans:
        first, last = line_of(a), line_of(max(a, b - 1))
        tags = _tags_in((ln, raw_lines[ln - 1]) for ln in range(first, last + 1))
        if tags:
            blocks.append((first, last, tags))

    def blank(ln):
        return ln - 1 >= len(code_lines) or not code_lines[ln - 1].strip()

    return symbols, blocks, blank


# ------------------------------------------------------------------ Python

def _scan_python(path, text):
    tree = ast.parse(text, filename=path)
    raw_lines = text.splitlines()

    def start_of(node):
        return min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])

    symbols, doc_nodes = [], [tree]
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(Symbol(node.name, start_of(node), node.end_lineno, "function"))
            doc_nodes.append(node)
        elif isinstance(node, ast.ClassDef):
            symbols.append(Symbol(node.name, start_of(node), node.end_lineno, "class"))
            doc_nodes.append(node)
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.append(Symbol(f"{node.name}.{sub.name}", start_of(sub), sub.end_lineno, "function", node.name))
                    doc_nodes.append(sub)

    blocks = []
    for node in doc_nodes:
        body = getattr(node, "body", [])
        if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                and isinstance(body[0].value.value, str):
            d = body[0]
            tags = _tags_in((ln, raw_lines[ln - 1]) for ln in range(d.lineno, d.end_lineno + 1))
            if tags:
                blocks.append((d.lineno, d.end_lineno, tags))

    comment_lines = set()
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.COMMENT:
            ln = tok.start[0]
            if not raw_lines[ln - 1][: tok.start[1]].strip():
                comment_lines.add(ln)
            tags = _tags_in([(ln, tok.string)])
            if tags:
                blocks.append((ln, ln, tags))

    def blank(ln):
        return ln - 1 >= len(raw_lines) or not raw_lines[ln - 1].strip() or ln in comment_lines

    return symbols, blocks, blank


# ------------------------------------------------------------------ attribution

def _attribute(path, symbols, blocks, blank):
    file_tags, per_symbol, errors = [], defaultdict(list), []
    for first, last, tags in sorted(blocks, key=lambda b: b[0]):
        if any(t.tag == "file" for t in tags):
            file_tags += [t for t in tags if t.tag != "file"]
            continue
        enclosing = [s for s in symbols if s.start <= first and s.end >= last]
        if enclosing:
            target = max(enclosing, key=lambda s: s.start)
        else:
            following = [s for s in symbols if s.start > last]
            target = min(following, key=lambda s: s.start) if following else None
            if target is not None and not all(blank(ln) for ln in range(last + 1, target.start)):
                target = None
        if target is None:
            errors.append(f"{path}:{tags[0].line}: @{tags[0].tag} is not directly above or inside a function; "
                          f"move it there, or add @file to apply it to the whole file")
            continue
        per_symbol[target.name] += tags
    return file_tags, per_symbol, errors


def _apply(unit, tags, path, role, errors):
    allowed = ROLE_TAGS[role]
    for t in tags:
        if t.tag not in allowed:
            what = "test" if role == "test" else "source"
            errors.append(f"{path}:{t.line}: @{t.tag} is not valid in a {what} file")
            continue
        if t.tag in KEY_TAGS:
            keys = [k for k in re.split(r"[,\s]+", t.value) if k]
            if not keys:
                errors.append(f"{path}:{t.line}: @{t.tag} names no requirement or element")
            for k in keys:
                if not KEY_RE.match(k):
                    errors.append(f"{path}:{t.line}: @{t.tag}: {k!r} is not a valid key")
                    continue
                bucket = getattr(unit, t.tag)
                if k not in bucket:
                    bucket.append(k)
                    unit.tag_lines[(t.tag, k)] = t.line
        elif t.tag == "infrastructure":
            if not t.value:
                errors.append(f"{path}:{t.line}: @infrastructure needs a reason")
            else:
                unit.infrastructure = t.value
        elif t.tag == "test-level":
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", t.value or ""):
                errors.append(f"{path}:{t.line}: @test-level needs a single level id")
            else:
                unit.test_level = t.value


def scan_file(path, text, language, role):
    """Scan one file. role is 'source' or 'test'. Returns (units, errors)."""
    try:
        if language == "python":
            symbols, blocks, blank = _scan_python(path, text)
        else:
            symbols, blocks, blank = _scan_c(path, text)
    except SyntaxError as e:
        return [], [f"{path}:{e.lineno}: cannot parse: {e.msg}"]

    file_tags, per_symbol, errors = _attribute(path, symbols, blocks, blank)
    classes = {s.name for s in symbols if s.kind == "class"}
    units = []

    def is_test(s):
        if s.kind == "test":
            return True
        last = s.name.rsplit(".", 1)[-1]
        return s.kind == "function" and last.startswith("test") and (s.parent is None or s.parent.startswith("Test"))

    for s in symbols:
        if s.kind == "class":
            continue
        inherited = per_symbol.get(s.parent, []) if s.parent in classes else []
        if role == "test":
            if not is_test(s):
                if per_symbol.get(s.name):
                    errors.append(f"{path}:{per_symbol[s.name][0].line}: annotation on {s.name}, which is not a test")
                continue
            u = Unit(path, s.name, s.start, s.end)
            _apply(u, file_tags + inherited + per_symbol.get(s.name, []), path, role, errors)
        else:
            u = Unit(path, s.name, s.start, s.end)
            _apply(u, inherited + per_symbol.get(s.name, []), path, role, errors)
        units.append(u)

    if role == "source" and file_tags:
        last_line = max([s.end for s in symbols], default=1)
        u = Unit(path, None, 1, max(last_line, len(text.splitlines())))
        _apply(u, file_tags, path, role, errors)
        units.append(u)
    elif role == "test" and file_tags and not any(is_test(s) for s in symbols):
        errors.append(f"{path}: @file annotations but no tests found in the file")

    return units, sorted(set(errors), key=errors.index)

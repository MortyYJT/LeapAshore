"""Every code path that writes a `verified_at` column is named here (openspec source-verification D5).

`verified_at` is a person's statement that they read a page; the red line is that no default, importer
or job ever writes it. Two layers prove it:

- this file scans the repository for every write to a column of that name (Python stores, keywords,
  dict keys, `setattr`, SQL in strings; any other tracked file that mentions it at all) and requires
  each one to be on the allow-list below, which says whether it may write anything but NULL;
- `test_source_verification.py` shows the database trigger refusing a non-null `sources.verified_at`
  from anything but an admin's recorded confirmation.

A new writer fails here until someone adds it to the list with a reason. A listed writer that no longer
exists fails too, so the list stays the truth rather than a history.
"""

import ast
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

API = Path(__file__).resolve().parents[1]
REPO = API.parent
COLUMN = "verified_at"

# SQL that writes the column: an UPDATE … SET that names it, or an INSERT whose column list does.
SQL_WRITE = re.compile(
    rf"\bupdate\b[^;]*?\bset\b[^;]*?\b{COLUMN}\b|\binsert\s+into\s+\w+\s*\([^)]*\b{COLUMN}\b",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class Site:
    path: str  # relative to the repository
    scope: str  # the enclosing function's qualified name, or <module>
    kind: str  # store | keyword | dict | setattr | sql
    clears: bool  # the value written is the literal None


def _is_none(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _names_column(target: ast.AST) -> bool:
    if isinstance(target, ast.Attribute):
        return target.attr == COLUMN
    if isinstance(target, ast.Subscript):
        return isinstance(target.slice, ast.Constant) and target.slice.value == COLUMN
    return False


class _Scanner(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.scope: list[str] = []
        self.sites: list[Site] = []
        self.docstrings: set[int] = set()

    def _add(self, kind: str, value: ast.AST | None, clears: bool | None = None) -> None:
        clears = _is_none(value) if clears is None else clears
        self.sites.append(Site(self.path, ".".join(self.scope) or "<module>", kind, clears))

    def _enter(self, node: ast.AST) -> None:
        body = getattr(node, "body", [])
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            self.docstrings.add(id(body[0].value))

    def visit_Module(self, node: ast.Module) -> None:
        self._enter(node)
        self.generic_visit(node)

    def _scoped(self, node) -> None:
        self._enter(node)
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _scoped

    def _store(self, target: ast.AST, value: ast.AST | None) -> None:
        if isinstance(target, (ast.Tuple, ast.List)):
            values = value.elts if isinstance(value, (ast.Tuple, ast.List)) and len(value.elts) == len(target.elts) else None
            for index, element in enumerate(target.elts):
                self._store(element, values[index] if values else value)
        elif _names_column(target):
            self._add("store", value)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._store(target, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._store(node.target, node.value)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._store(node.target, node.value)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        for keyword in node.keywords:
            if keyword.arg == COLUMN:
                self._add("keyword", keyword.value)
        if (isinstance(node.func, ast.Name) and node.func.id == "setattr" and len(node.args) >= 3
                and isinstance(node.args[1], ast.Constant) and node.args[1].value == COLUMN):
            self._add("setattr", node.args[2])
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        for key, value in zip(node.keys, node.values):
            # A string key, or a column expression (`{Source.verified_at: x}`, `table.c.verified_at`).
            if (isinstance(key, ast.Constant) and key.value == COLUMN) or (key is not None and _names_column(key)):
                self._add("dict", value)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and id(node) not in self.docstrings and SQL_WRITE.search(node.value):
            self._add("sql", None, clears=False)  # what SQL writes is not read here


def scan_source(text: str, path: str) -> list[Site]:
    scanner = _Scanner(path)
    scanner.visit(ast.parse(text))
    return scanner.sites


def python_files() -> list[Path]:
    """Every Python file the application, its commands, migrations, evaluations and scripts are made of."""
    skip = {".venv", "tests", "var", "__pycache__", "node_modules", ".runtime-tools"}
    files = [p for p in API.rglob("*.py") if not skip & set(p.relative_to(API).parts)]
    files += sorted((REPO / "scripts").glob("*.py"))
    return sorted(files)


def all_sites() -> set[Site]:
    sites: set[Site] = set()
    for path in python_files():
        sites.update(scan_source(path.read_text(encoding="utf-8"), str(path.relative_to(REPO))))
    return sites


# (path, scope, kind) -> (may write a value other than NULL, why it is here)
ALLOWED: dict[tuple[str, str, str], tuple[bool, str]] = {
    ("api/app/services/source_verification.py", "verify", "store"):
        (True, "the admin's confirmation (P2 #3); the trigger also demands the confirmation row"),
    ("api/app/services/source_verification.py", "revoke", "store"):
        (False, "the admin withdraws a confirmation"),
    ("api/app/services/reviews.py", "verify_criterion", "store"):
        (True, "material-review criteria (another table), set by the operator command review_cli.py"),
    ("api/app/routers/review_criteria.py", "read_review_criteria", "keyword"):
        (True, "a response model copying the stored value out; not a database write"),
    ("api/app/collect/importer.py", "import_school", "keyword"):
        (False, "a new page source starts unverified"),
    ("api/app/collect/importer.py", "import_school", "store"):
        (False, "new content on a verified page withdraws the verification"),
    ("api/app/seed.py", "seed_programs", "keyword"): (False, "seeded sources start unverified"),
    ("api/app/seed_catalog.py", "_ensure_source", "keyword"): (False, "seeded sources start unverified"),
    ("api/app/seed_roadmap.py", "seed_roadmap", "keyword"): (False, "seeded sources start unverified"),
}


def test_the_scanner_finds_every_shape_of_write():
    sample = '''
def a(row, s, t):
    row.verified_at = now()
    row.status, row.verified_at = "x", None
    d["verified_at"] = 1
    Source(verified_at=stamp)
    update(Source).values({"verified_at": stamp})
    update(Source).values({Source.verified_at: stamp, Source.__table__.c.verified_at: stamp})
    setattr(row, "verified_at", stamp)
    s.execute(text("UPDATE sources SET status = 'x', verified_at = now() WHERE id = :id"))
    t.execute("insert into sources (id, url, verified_at) values (1, 2, 3)")
    row.verified_at += delta
def b(row):
    """UPDATE sources SET verified_at is only prose in a docstring."""
    return row.verified_at
'''
    found = sorted((s.kind, s.clears) for s in scan_source(sample, "sample.py"))
    assert found == sorted([
        ("store", False), ("store", True), ("store", False), ("store", False), ("keyword", False),
        ("dict", False), ("dict", False), ("dict", False), ("setattr", False), ("sql", False), ("sql", False),
    ])
    assert all(s.scope == "a" for s in scan_source(sample, "sample.py"))


def test_every_write_to_verified_at_is_on_the_allow_list():
    sites = all_sites()
    unlisted = sorted(f"{s.path}:{s.scope} ({s.kind})" for s in sites if (s.path, s.scope, s.kind) not in ALLOWED)
    assert not unlisted, f"a new writer of verified_at; add it to ALLOWED with a reason, or remove it: {unlisted}"
    setting = sorted(f"{s.path}:{s.scope} ({s.kind})" for s in sites
                     if not s.clears and not ALLOWED[(s.path, s.scope, s.kind)][0])
    assert not setting, f"may only clear verified_at, but writes a value: {setting}"


def test_the_allow_list_has_no_stale_entries():
    present = {(s.path, s.scope, s.kind) for s in all_sites()}
    assert set(ALLOWED) <= present, sorted(set(ALLOWED) - present)


def test_only_the_admin_entry_and_the_criteria_command_may_set_a_date():
    setters = {key for key, (may_set, _) in ALLOWED.items() if may_set and key[2] != "keyword"}
    assert setters == {
        ("api/app/services/source_verification.py", "verify", "store"),
        ("api/app/services/reviews.py", "verify_criterion", "store"),
    }


def test_the_collection_importers_and_jobs_never_set_it():
    """The collector, queue, chunker, judge, backfills and every command under app/ may only clear it."""
    for site in all_sites():
        if site.path.startswith(("api/app/collect/", "api/app/agent/", "api/evals/")) or site.path in {
            "api/app/worker.py", "api/app/cleanup.py", "api/app/knowledge_gaps.py", "api/app/roles.py",
        }:
            assert site.clears, site


def test_no_other_tracked_file_mentions_the_column():
    """SQL in shell scripts, the walkthrough, compose files or the web app would bypass the Python scan."""
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True).stdout
    paths = [p for p in listed.decode().split("\0") if p]
    assert paths, "git ls-files listed nothing"
    mentions = []
    for rel in paths:
        if rel.endswith((".py", ".md")) or rel.startswith(("api/tests/", "openspec/", "note/", "docs/")):
            continue
        path = REPO / rel
        try:
            if COLUMN in path.read_text(encoding="utf-8"):
                mentions.append(rel)
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
    # The fake-date checker spells the name out to look for it.
    assert mentions == ["scripts/check-no-fake-dates.cjs"], mentions

import ast
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _boundary_files() -> list[Path]:
    backend_app = REPOSITORY_ROOT / "backend" / "app"
    auth_app = REPOSITORY_ROOT / "auth_service" / "app"
    return sorted(
        [
            *backend_app.joinpath("services").glob("*.py"),
            *backend_app.joinpath("operators").glob("*.py"),
            *backend_app.glob("*routes.py"),
            backend_app / "main.py",
            *auth_app.joinpath("services").glob("*.py"),
            auth_app / "main.py",
        ]
    )


def test_database_access_is_confined_to_repositories_and_infrastructure():
    violations: list[str] = []

    for path in _boundary_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        relative = path.relative_to(REPOSITORY_ROOT)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "sqlalchemy" or alias.name.startswith("sqlalchemy."):
                        violations.append(f"{relative}:{node.lineno} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "sqlalchemy" or module.startswith("sqlalchemy.") or module == "app.database":
                    violations.append(f"{relative}:{node.lineno} imports from {module}")
            elif isinstance(node, ast.Attribute) and node.attr in {"db", "commit", "rollback"}:
                violations.append(f"{relative}:{node.lineno} accesses .{node.attr}")
            elif (
                isinstance(node, ast.Attribute)
                and node.attr == "repository"
                and "routes" in path.name
            ):
                violations.append(f"{relative}:{node.lineno} reaches through a service to its repository")
            elif isinstance(node, ast.Name) and node.id.startswith("SqlAlchemy") and node.id.endswith("Repository"):
                violations.append(f"{relative}:{node.lineno} uses concrete repository {node.id}")

    assert violations == [], "Database boundary violations:\n" + "\n".join(violations)

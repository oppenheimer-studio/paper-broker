from pathlib import Path

from paper_broker.migrate import MIGRATIONS, _optional_file


def test_migrations_are_ordered_sql():
    files = sorted(MIGRATIONS.glob("*.sql"))
    names = [p.name for p in files]
    assert names[0].startswith("001")
    assert any(n.startswith("002") for n in names)
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "CREATE" in text.upper() or "INSERT" in text.upper()


def test_002_is_optional():
    path = MIGRATIONS / "002_wrappers.sql"
    assert _optional_file(path)
    assert not _optional_file(Path("001_schema_migrations.sql"))

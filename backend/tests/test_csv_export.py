"""Activity-log CSV export must not emit live spreadsheet formulas."""
from routers.activity_logs import _csv_safe


def test_formula_cells_are_escaped():
    row = ["=HYPERLINK(\"http://evil\")", "+1", "-2", "@SUM(A1)", "\tx"]
    assert all(cell.startswith("'") for cell in _csv_safe(row))


def test_normal_cells_unchanged():
    row = ["user_login", "10.0.0.1", "Mozilla/5.0", None, 5]
    assert _csv_safe(row) == row

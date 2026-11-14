"""
Plain ASCII table formatting for terminal output (no extra libraries needed).

Cells may contain several lines (separated by "\\n"); long lines are wrapped
to fit each column's maximum width.
"""

import textwrap
from typing import List, Optional, Sequence


def wrap_cell(cell_text: str, max_width: int) -> List[str]:
    """Split a cell into lines, wrapping any line that is wider than max_width."""
    wrapped_lines = []
    for line in str(cell_text).split("\n"):
        # textwrap returns [] for an empty string, so keep a blank line instead
        wrapped_lines.extend(textwrap.wrap(line, max_width, subsequent_indent="  ") or [""])
    return wrapped_lines


def format_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    max_widths: Optional[Sequence[int]] = None,
) -> str:
    """Return a bordered ASCII table where each row can span multiple lines."""
    column_count = len(headers)
    if max_widths is None:
        max_widths = [60] * column_count

    # Wrap every cell first so we know how wide and tall each one is
    wrapped_rows = [
        [wrap_cell(cell, max_widths[column]) for column, cell in enumerate(row)]
        for row in rows
    ]
    wrapped_headers = [wrap_cell(header, max_widths[column]) for column, header in enumerate(headers)]

    # Each column is as wide as its widest line (header included)
    column_widths = []
    for column in range(column_count):
        all_lines = wrapped_headers[column] + [
            line for wrapped_row in wrapped_rows for line in wrapped_row[column]
        ]
        column_widths.append(max(len(line) for line in all_lines))

    border = "+" + "+".join("-" * (width + 2) for width in column_widths) + "+"
    header_border = border.replace("-", "=")

    def render_row(wrapped_cells: List[List[str]]) -> List[str]:
        """Render one logical row, padding shorter cells with blank lines."""
        row_height = max(len(cell_lines) for cell_lines in wrapped_cells)
        output_lines = []
        for line_index in range(row_height):
            pieces = []
            for column, cell_lines in enumerate(wrapped_cells):
                text = cell_lines[line_index] if line_index < len(cell_lines) else ""
                pieces.append(f" {text.ljust(column_widths[column])} ")
            output_lines.append("|" + "|".join(pieces) + "|")
        return output_lines

    table_lines = [border, *render_row(wrapped_headers), header_border]
    for wrapped_row in wrapped_rows:
        table_lines.extend(render_row(wrapped_row))
        table_lines.append(border)
    return "\n".join(table_lines)

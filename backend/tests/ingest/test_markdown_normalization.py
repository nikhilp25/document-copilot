"""Markdown normalization applied before Docling re-parses a filing.

Both transforms exist because SEC HTML carries meaning in styling rather than
structure. The cases below are taken from the actual corpus — each filer botches
it differently.
"""

from ingest.chunks import promote_item_headings, strip_empty_table_columns


class TestPromoteItemHeadings:
    def test_plain_item_line_becomes_a_heading(self) -> None:
        """Apple, Google and NVIDIA put the heading on its own line."""
        assert promote_item_headings("Item 1A. Risk Factors") == (
            "## Item 1A. Risk Factors"
        )

    def test_heading_inside_a_table_row_is_recovered(self) -> None:
        """Amazon wraps headings in a table, repeating cells across the colspan."""
        row = "| Item 1A. | Item 1A. | Item 1A. | Risk Factors | Risk Factors |"
        assert promote_item_headings(row) == "## Item 1A. Risk Factors"

    def test_uppercase_and_letter_spaced_titles_are_promoted(self) -> None:
        """Microsoft's letter-spaced caps survive the HTML conversion mangled."""
        assert promote_item_headings("ITEM 1. B USINESS") == "## Item 1. B USINESS"

    def test_bare_running_header_is_not_a_heading(self) -> None:
        """Microsoft stamps "Item 1" atop every page; there are ~130 per filing."""
        assert promote_item_headings("Item 1") == "Item 1"

    def test_table_of_contents_row_is_left_alone(self) -> None:
        """The TOC links to the body, so promoting it opens the section twice."""
        toc = "| Item 1A. | Item 1A. | [Risk Factors](#i8a64c58) |"
        assert promote_item_headings(toc) == toc

    def test_prose_cross_reference_is_not_promoted(self) -> None:
        line = (
            "Item 1A. Risk Factors of this Annual Report on Form 10-K describes "
            "the risks that could materially affect our business, and should be "
            "read together with the consolidated financial statements."
        )
        assert promote_item_headings(line) == line

    def test_body_text_passes_through_unchanged(self) -> None:
        body = "The Company's fiscal year 2024 ended on September 28, 2024."
        assert promote_item_headings(body) == body


class TestStripEmptyTableColumns:
    def test_empty_columns_are_removed(self) -> None:
        table = (
            "| Total net sales |  | $ | 391,035 |  |\n"
            "|---|---|---|---|---|\n"
            "| Gross margin |  | $ | 180,683 |  |"
        )
        assert strip_empty_table_columns(table) == (
            "| Total net sales | $ | 391,035 |\n"
            "| --- | --- | --- |\n"
            "| Gross margin | $ | 180,683 |"
        )

    def test_column_with_any_value_anywhere_is_kept(self) -> None:
        """One populated cell makes the column data, not scaffolding."""
        table = "| Revenue |  | 100 |\n| Costs | 25 | 40 |"
        assert strip_empty_table_columns(table) == table

    def test_layout_only_table_is_dropped_entirely(self) -> None:
        """SEC filings use empty tables purely to position things on a page."""
        table = "|  |  |  |\n|----|----|----|\n|  |  |  |"
        assert strip_empty_table_columns(table) == ""

    def test_surrounding_prose_is_preserved(self) -> None:
        markdown = (
            "Net sales by category:\n| iPhone |  | 201,183 |\n\nSee accompanying notes."
        )
        assert strip_empty_table_columns(markdown) == (
            "Net sales by category:\n| iPhone | 201,183 |\n\nSee accompanying notes."
        )

    def test_document_without_tables_is_unchanged(self) -> None:
        markdown = "Item 1. Business\n\nThe Company designs smartphones."
        assert strip_empty_table_columns(markdown) == markdown

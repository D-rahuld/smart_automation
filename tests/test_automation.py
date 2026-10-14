"""Tests for the extraction-only checkpoint."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from logic import format_record, parse_reference_text


KEVIN = (
    "Kevin Winn * Director Information Technology * Hill-Rom * "
    "http://www.hill-rom.com/ * Two Prudential Plaza, Suite 4100 180 N. "
    "Stetson Avenue Chicago IL USA 60601 * kevin.winn@hillrom.com * (312) 819-7200"
)


def test_parses_the_visible_seven_field_record() -> None:
    record = parse_reference_text(KEVIN)
    assert record is not None
    assert record["name"] == "Kevin Winn"
    assert record["designation"] == "Director Information Technology"
    assert record["company"] == "Hill-Rom"
    assert record["website"] == "http://www.hill-rom.com/"
    assert record["email"] == "kevin.winn@hillrom.com"
    assert record["phone"] == "(312) 819-7200"


def test_finds_record_inside_surrounding_page_text() -> None:
    page_text = "START WORK * Select Form * " + KEVIN + " * Name * Designation * Company Name"
    record = parse_reference_text(page_text)
    assert record is not None
    assert record["name"] == "Kevin Winn"


def test_rejects_form_placeholders() -> None:
    placeholders = "Name * Designation * Company Name * Website * Address * Email * Office Contact"
    assert parse_reference_text(placeholders) is None


def test_requires_a_real_email_and_website() -> None:
    invalid = "A Person * Director * Company * Website * Address * Email * 555-1234"
    assert parse_reference_text(invalid) is None


def test_format_contains_all_review_labels() -> None:
    record = parse_reference_text(KEVIN)
    assert record is not None
    formatted = format_record(record)
    for label in ("Name", "Designation", "Company Name", "Website", "Address", "Email", "Office Contact"):
        assert f"- {label}:" in formatted


def test_strips_navigation_text_before_dynamic_name() -> None:
    page_text = (
        "START WORK Data @ User Dashboard Select Form @ Generate QRCode @ "
        "Submit All ARCode Steve Pachter * Manager, Software Engineering * "
        "Corelogic * www.corelogic.com * 40 Pacifica, Suite 900 Irvine CA USA 92618 * "
        "steve.pachter@corelogic.com * (714) 250-6400 / (949) 214-1000"
    )
    record = parse_reference_text(page_text)
    assert record is not None
    assert record["name"] == "Steve Pachter"
    assert record["designation"] == "Manager, Software Engineering"
    assert record["company"] == "Corelogic"


def test_navigation_cleanup_keeps_different_names_dynamic() -> None:
    page_text = (
        "START WORK @ User Dashboard @ Select Form @ Generate QRCode @ "
        "Submit All QRCode A. J. Smith * Director of IT * Example Inc * "
        "www.example.com * 10 Main Street * aj.smith@example.com * 555-0100"
    )
    record = parse_reference_text(page_text)
    assert record is not None
    assert record["name"] == "A. J. Smith"

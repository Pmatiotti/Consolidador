"""Testes para date_parser."""

import pytest
from utils.date_parser import parse_date


class TestParseDate:
    def test_full_date(self):
        assert parse_date("22/07/2024") == "22/07/2024"

    def test_short_year_2000s(self):
        assert parse_date("26/01/26") == "26/01/2026"

    def test_short_year_2000s_2(self):
        assert parse_date("20/08/21") == "20/08/2021"

    def test_short_year_2000s_3(self):
        assert parse_date("30/09/21") == "30/09/2021"

    def test_short_year_1900s(self):
        assert parse_date("20/08/71") == "20/08/1971"

    def test_short_year_boundary(self):
        assert parse_date("01/01/50") == "01/01/1950"

    def test_short_year_49(self):
        assert parse_date("01/01/49") == "01/01/2049"

    def test_dash(self):
        assert parse_date("-") is None

    def test_empty(self):
        assert parse_date("") is None

    def test_none(self):
        assert parse_date(None) is None

    def test_with_spaces(self):
        assert parse_date("  22/07/2024  ") == "22/07/2024"

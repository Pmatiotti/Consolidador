"""Testes para number_parser."""

import pytest
from utils.number_parser import parse_br


class TestParseBr:
    def test_standard_number(self):
        assert parse_br("1.247.126,85") == 1247126.85

    def test_reais_prefix(self):
        assert parse_br("R$ 50.539,60") == 50539.60

    def test_zero(self):
        assert parse_br("R$ 0,00") == 0.0

    def test_dash(self):
        assert parse_br("-") is None

    def test_empty(self):
        assert parse_br("") is None

    def test_none(self):
        assert parse_br(None) is None

    def test_reais_with_spaces(self):
        assert parse_br("R$ 12.155,26") == 12155.26

    def test_arrow_up(self):
        assert parse_br("50.000,00↑") == 50000.00

    def test_arrow_down(self):
        assert parse_br("↓30.000,00") == 30000.00

    def test_simple_number(self):
        assert parse_br("100,50") == 100.50

    def test_large_number(self):
        assert parse_br("10.000.000,00") == 10000000.00

    def test_spaces_only(self):
        assert parse_br("   ") is None

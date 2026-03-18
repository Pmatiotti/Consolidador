"""Testes para tax_parser — cobre TODOS os formatos das 5 corretoras."""

import pytest
from utils.tax_parser import parse_tax, parse_tax_bradesco


class TestParseTaxBTG:
    def test_prefixado(self):
        assert parse_tax("16,37% a.a.") == ("Prefixado", 16.37)

    def test_pct_cdi(self):
        assert parse_tax("122,00% do CDI") == ("% CDI", 122.00)

    def test_cdi_plus(self):
        assert parse_tax("CDI + 0,85%") == ("CDI +", 0.85)

    def test_cdi_minus(self):
        assert parse_tax("CDI -0,75%") == ("CDI +", -0.75)

    def test_ipca_plus(self):
        assert parse_tax("IPCA + 8,75%") == ("IPCA +", 8.75)

    def test_100_pre(self):
        assert parse_tax("100% PRE") == ("Alternativo", 100.00)


class TestParseTaxMonteBravoXP:
    def test_prefixado(self):
        assert parse_tax("+ 13,70%") == ("Prefixado", 13.70)

    def test_pct_cdi(self):
        assert parse_tax("92,00% CDI") == ("% CDI", 92.00)

    def test_cdi_plus(self):
        assert parse_tax("CDI + 0,53%") == ("CDI +", 0.53)

    def test_pct_cdi_105(self):
        assert parse_tax("105,00% CDI") == ("% CDI", 105.00)

    def test_ipca_plus(self):
        assert parse_tax("IPC-A + 6,40%") == ("IPCA +", 6.40)

    def test_ipca_plus_no_space(self):
        assert parse_tax("IPC-A +7,27%") == ("IPCA +", 7.27)


class TestParseTaxItau:
    def test_cdi_100(self):
        assert parse_tax("100,0000000%CDI") == ("% CDI", 100.00)

    def test_prefixado_12_90(self):
        assert parse_tax("12,90000000000%aa") == ("Prefixado", 12.90)

    def test_prefixado_13_60(self):
        assert parse_tax("13,60000000000%aa") == ("Prefixado", 13.60)

    def test_prefixado_12_24(self):
        assert parse_tax("12,23720000000%aa") == ("Prefixado", 12.24)

    def test_ipca_7_1(self):
        assert parse_tax("100,0000000%IPCA+7,1") == ("IPCA +", 7.10)

    def test_ipca_8_2(self):
        assert parse_tax("100,0000000%IPCA+8,2") == ("IPCA +", 8.20)

    def test_ipca_6_4(self):
        assert parse_tax("100,0000000%IPCA+6,4") == ("IPCA +", 6.40)

    def test_ipca_6_2(self):
        assert parse_tax("100,0000000%IPCA+6,2") == ("IPCA +", 6.20)

    def test_ipca_6_7(self):
        assert parse_tax("100,0000000%IPCA+6,7") == ("IPCA +", 6.70)

    def test_vcp(self):
        assert parse_tax("100,0000000%VCP") == ("% VCP", 100.00)


class TestParseTaxEmpty:
    def test_dash(self):
        assert parse_tax("-") == ("-", None)

    def test_empty(self):
        assert parse_tax("") == ("-", None)

    def test_none(self):
        assert parse_tax(None) == ("-", None)


class TestParseTaxBradesco:
    def test_ipca(self):
        assert parse_tax_bradesco("IPCA", "8,70%") == ("IPCA +", 8.70)

    def test_pre(self):
        assert parse_tax_bradesco("PRÉ", "11,38%") == ("Prefixado", 11.38)

    def test_pre_10_70(self):
        assert parse_tax_bradesco("PRÉ", "10,70%") == ("Prefixado", 10.70)

    def test_dash_dash(self):
        assert parse_tax_bradesco("-", "-") == ("-", None)

    def test_empty(self):
        assert parse_tax_bradesco("", "") == ("-", None)

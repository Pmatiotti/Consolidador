"""Testes para plugin Itaú Personnalité."""

import pytest
from plugins.itau import ItauPlugin, SUBCLASSE_MAP, SKIP_PATTERNS


class TestItauDetect:
    def test_detect_itau(self):
        text = "Itaú Personnalité\nCarteira de Investimentos"
        assert ItauPlugin.detect(text) is True

    def test_detect_itau_no_accent(self):
        text = "itau personnalite Carteira de Investimentos"
        assert ItauPlugin.detect(text) is True

    def test_no_detect_without_carteira(self):
        text = "Itaú Personnalité - Extrato Mensal"
        assert ItauPlugin.detect(text) is False

    def test_no_detect_other(self):
        text = "BTG - Carteira de Investimentos"
        assert ItauPlugin.detect(text) is False

    def test_broker_name(self):
        assert ItauPlugin.broker_name() == "Itaú"


class TestItauSectionHeader:
    def test_pos_fixados(self):
        assert ItauPlugin._detect_section_header("48,8% juros pós-fixados") == "Pós-fixado"

    def test_prefixados(self):
        assert ItauPlugin._detect_section_header("13,0% juros prefixados") == "Pré-fixado"

    def test_inflacao(self):
        assert ItauPlugin._detect_section_header("25,5% inflação") == "Inflação"

    def test_multimercados(self):
        assert ItauPlugin._detect_section_header("2,8% multimercados") == "Multimercado"

    def test_acoes(self):
        assert ItauPlugin._detect_section_header("9,9% ações") == "Renda Variável"

    def test_not_section(self):
        assert ItauPlugin._detect_section_header("CDB ITAU 100%CDI") is None


class TestItauSkipLines:
    def test_skip_pct_cdi(self):
        assert ItauPlugin._is_skip_line("% do cdi") is True

    def test_skip_ibovespa(self):
        assert ItauPlugin._is_skip_line("% do ibovespa") is True

    def test_skip_ifix(self):
        assert ItauPlugin._is_skip_line("retorno sobre o ifix") is True

    def test_skip_ipca(self):
        assert ItauPlugin._is_skip_line("retorno sobre o ipca") is True

    def test_no_skip_asset(self):
        assert ItauPlugin._is_skip_line("cdb itau 100% cdi") is False

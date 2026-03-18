"""Testes para plugin Monte Bravo."""

import pytest
from plugins.monte_bravo import MonteBravoPlugin


class TestMBDetect:
    def test_detect_montebravo(self):
        text = "montebravo PRECIFICAÇÃO DE RENDA FIXA relatório"
        assert MonteBravoPlugin.detect(text) is True

    def test_detect_monte_bravo_spaced(self):
        text = "MONTE BRAVO Investimentos\nPRECIFICAÇÃO DE RENDA FIXA"
        assert MonteBravoPlugin.detect(text) is True

    def test_no_detect_without_rf(self):
        text = "Monte Bravo - Relatório Mensal"
        assert MonteBravoPlugin.detect(text) is False

    def test_no_detect_xp(self):
        text = "XP Investimentos PRECIFICAÇÃO DE RENDA FIXA"
        assert MonteBravoPlugin.detect(text) is False

    def test_broker_name(self):
        assert MonteBravoPlugin.broker_name() == "Monte Bravo"

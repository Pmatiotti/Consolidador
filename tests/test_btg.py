"""Testes para plugin BTG Pactual."""

import pytest
from plugins.btg_pactual import BTGPactualPlugin


class TestBTGDetect:
    def test_detect_one(self):
        text = "Relatório de Performance\nONE Investimentos\nbtgpactual.com"
        assert BTGPactualPlugin.detect(text) is True

    def test_detect_btg(self):
        text = "Relatório de Performance do BTG Pactual"
        assert BTGPactualPlugin.detect(text) is True

    def test_no_detect_without_relatorio(self):
        text = "BTG Pactual - Extrato Mensal"
        assert BTGPactualPlugin.detect(text) is False

    def test_no_detect_other_broker(self):
        text = "Relatório de Performance - Bradesco"
        assert BTGPactualPlugin.detect(text) is False

    def test_broker_name(self):
        assert BTGPactualPlugin.broker_name() == "BTG Pactual"

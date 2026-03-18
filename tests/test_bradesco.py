"""Testes para plugin Bradesco."""

import pytest
from plugins.bradesco import BradescoPlugin, SUBCLASSE_MAP


class TestBradescoDetect:
    def test_detect_relatorio(self):
        text = "Bradesco Principal\nRelatório de investimentos"
        assert BradescoPlugin.detect(text) is True

    def test_detect_principal(self):
        text = "bradesco principal - carteira"
        assert BradescoPlugin.detect(text) is True

    def test_no_detect_other(self):
        text = "BTG Pactual - Relatório de investimentos"
        assert BradescoPlugin.detect(text) is False

    def test_broker_name(self):
        assert BradescoPlugin.broker_name() == "Bradesco"


class TestBradescoSubclasseMap:
    def test_cdi_selic(self):
        assert SUBCLASSE_MAP["cdi/selic"] == "Pós-fixado"

    def test_juro_real(self):
        assert SUBCLASSE_MAP["juro real"] == "Inflação"

    def test_prefixado(self):
        assert SUBCLASSE_MAP["prefixado"] == "Pré-fixado"

    def test_rv_global(self):
        assert SUBCLASSE_MAP["rv global"] == "RV Global"

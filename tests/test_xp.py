"""Testes para plugin XP Investimentos."""

import pytest
from plugins.xp import XPPlugin


class TestXPDetect:
    def test_detect_xp(self):
        text = "XP INVESTIMENTOS CORRETORA - Relatório de Posição"
        assert XPPlugin.detect(text) is True

    def test_no_detect_monte_bravo(self):
        text = "XP INVESTIMENTOS CORRETORA - Monte Bravo"
        assert XPPlugin.detect(text) is False

    def test_no_detect_other(self):
        text = "Bradesco - Relatório de Investimentos"
        assert XPPlugin.detect(text) is False

    def test_broker_name(self):
        assert XPPlugin.broker_name() == "XP"

    def test_xp_inherits_monte_bravo(self):
        from plugins.monte_bravo import MonteBravoPlugin
        assert issubclass(XPPlugin, MonteBravoPlugin)

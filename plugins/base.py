"""Classe abstrata base para plugins de corretoras."""

from abc import ABC, abstractmethod
from typing import List

from models.asset import Asset


class BrokerPlugin(ABC):
    @staticmethod
    @abstractmethod
    def detect(text: str) -> bool:
        """Recebe texto completo do PDF. True se reconhecer como seu."""
        pass

    @staticmethod
    @abstractmethod
    def broker_name() -> str:
        """Nome da corretora para coluna 'Corretora'."""
        pass

    @abstractmethod
    def extract(self, pdf_path: str) -> List[Asset]:
        """Extrai e retorna lista de ativos normalizados."""
        pass

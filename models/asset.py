"""Modelo de dados padronizado para ativos de investimento."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Asset:
    corretora: str              # "BTG Pactual", "Monte Bravo", "XP", "Bradesco", "Itaú"
    ativo: str                  # Nome do ativo
    tipo_ativo: str             # "CDB","LCA","LCI","CRA","CRI","DEB","LIG","LCD","LF","NTN-B","CDCA","CPR","COE","Fundo","FII","Previdência","Conta Corrente"
    data_aplicacao: Optional[str]    # "22/07/2024" ou None
    indexador: str              # "Prefixado","% CDI","CDI +","IPCA +","Alternativo","Renda Variável","% VCP","-"
    taxa: Optional[float]       # Valor numérico LIMPO. None se não aplicável.
    vencimento: Optional[str]
    liquidez: Optional[str]     # "D+0","D+11", data, ou None
    valor_aplicado: Optional[float]  # None quando não disponível
    valor_bruto: float          # Posição bruta
    valor_liquido: Optional[float]   # None quando não disponível
    classe: str                 # "Renda Fixa","Fundo de Investimento","COE","Previdência","Renda Variável","Conta Corrente"
    subclasse: str              # "Pré-fixado","Pós-fixado","Inflação","Alternativo", etc.

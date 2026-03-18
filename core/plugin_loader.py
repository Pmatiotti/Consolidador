"""Auto-discovery de plugins de corretoras."""

import importlib
import inspect
import os
import sys
from typing import List, Type

from plugins.base import BrokerPlugin


def discover_plugins() -> List[Type[BrokerPlugin]]:
    """Varre o diretório plugins/ e retorna classes filhas de BrokerPlugin.

    Ordem de detecção: Monte Bravo antes de XP (plataforma compartilhada).
    """
    plugins_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "plugins")

    if plugins_dir not in sys.path:
        sys.path.insert(0, os.path.dirname(plugins_dir))

    found = []
    for filename in sorted(os.listdir(plugins_dir)):
        if not filename.endswith(".py") or filename.startswith("_") or filename == "base.py":
            continue

        module_name = f"plugins.{filename[:-3]}"
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue

        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (issubclass(obj, BrokerPlugin)
                    and obj is not BrokerPlugin
                    and obj.__module__ == module_name):
                found.append(obj)

    # Ordenar: Monte Bravo antes de XP
    priority = {"Monte Bravo": 0, "XP": 1}
    found.sort(key=lambda p: priority.get(p.broker_name(), 5))

    return found

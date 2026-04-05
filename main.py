"""main.py — Point d'entrée unique Titanium v12.

Usage:
    cd C:\\Users\\flore\\Desktop\\TITANIUM\\Titanium\\v12
    python main.py
"""
from __future__ import annotations
import sys
import os

# Ajouter le répertoire v12 au PYTHONPATH
sys.path.insert(0, os.path.dirname(__file__))

from api.api_server import run

if __name__ == "__main__":
    run()

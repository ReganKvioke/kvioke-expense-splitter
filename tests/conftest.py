"""Shared pytest configuration and utilities."""
import os
import sys

# Ensure project root is importable before any bot modules are loaded
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def near(a: float, b: float, tol: float = 0.02) -> bool:
    """Float comparison with tolerance for rounding cents."""
    return abs(a - b) <= tol

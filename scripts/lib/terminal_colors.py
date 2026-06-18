"""Shared ANSI palette for Python demo scripts."""

from __future__ import annotations

import os
import sys


def colors_enabled() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("DEMO_COLOR") or os.environ.get("FORCE_COLOR"):
        return True
    return sys.stdout.isatty()


def c(code: str, text: str) -> str:
    if not colors_enabled():
        return text
    return f"\033[{code}m{text}\033[0m"


def reset() -> str:
    return "\033[0m" if colors_enabled() else ""


def white(text: str) -> str:
    return c("1;37", text)


def blue(text: str) -> str:
    return c("94", text)


def cyan(text: str) -> str:
    return c("96", text)


def green(text: str) -> str:
    return c("32", text)


def yellow(text: str) -> str:
    return c("33", text)


def magenta(text: str) -> str:
    return c("35", text)


def red(text: str) -> str:
    return c("31", text)


def dim(text: str) -> str:
    return c("2", text)


def bold(text: str) -> str:
    return c("1", text)

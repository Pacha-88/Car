"""A scripts/ inditok sorvegeit orzi.

A .bat fajlt a felhasznalo nyersen tolti le GitHubrol es duplan kattint
ra; cmd.exe a goto/call cimkeket LF-only fajlban egyes Windows-verziokon
nem talalja meg, ugy hogy a hiba csak az o gepen, futas kozben latszana.
Linuxrol szerkesztve pontosan ez tortent egyszer: a javitas csendben
LF-re irta at az egesz fajlt, es csak a gyanusan nagy diff bukatta le.
A .gitattributes -text-je miatt a git szandekosan nem konvertal semmit,
tehat a bajtokert ez a teszt felel, nem a git.
"""

from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def test_bat_lines_end_with_crlf() -> None:
    raw = (SCRIPTS / "scrape-local.bat").read_bytes()
    bad = [
        i
        for i, line in enumerate(raw.split(b"\n")[:-1], start=1)
        if not line.endswith(b"\r")
    ]
    assert not bad, f"LF-only sorok a .bat-ban (cmd.exe-nek CRLF kell): {bad}"


def test_command_has_no_carriage_returns() -> None:
    raw = (SCRIPTS / "scrape-local.command").read_bytes()
    assert b"\r" not in raw, "CR a bash scriptben - a bash 'command not found^M'-et adna"

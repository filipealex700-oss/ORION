"""Iniciar o ORION com o Windows (chave Run do utilizador, sem administrador)."""
import os
import sys

NOME = "ORION"
CHAVE = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _comando():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimizado'
    py = sys.executable.replace("python.exe", "pythonw.exe")
    return f'"{py}" "{os.path.abspath(sys.argv[0])}" --minimizado'


def ativo():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE) as k:
            winreg.QueryValueEx(k, NOME)
            return True
    except Exception:
        return False


def definir(ligar):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE, 0, winreg.KEY_SET_VALUE) as k:
        if ligar:
            winreg.SetValueEx(k, NOME, 0, winreg.REG_SZ, _comando())
        else:
            try:
                winreg.DeleteValue(k, NOME)
            except FileNotFoundError:
                pass

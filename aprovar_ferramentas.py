"""Revê e aprova ferramentas novas escritas pelo ORION antes de poderem correr."""
import shutil
from pathlib import Path


def main():
    base = Path(__file__).parent
    pend, ativo = base / "plugins_pendentes", base / "plugins"
    ativo.mkdir(exist_ok=True)

    ficheiros = sorted(pend.glob("*.py"))
    if not ficheiros:
        print("Não há ferramentas pendentes.")
        return
    for f in ficheiros:
        print("=" * 60, f"\n{f.name}\n", "=" * 60)
        print(f.read_text(encoding="utf-8"))
        print("=" * 60)
        print("ATENÇÃO: depois de aprovado, este código corre com as tuas permissões.")
        r = input("Aprovar? [s/N] ").strip().lower()
        if r == "s":
            shutil.move(str(f), str(ativo / f.name))
            print("Aprovada. Reinicia o ORION para a carregar.")
        else:
            f.unlink()
            print("Rejeitada e apagada.")


if __name__ == "__main__":
    main()

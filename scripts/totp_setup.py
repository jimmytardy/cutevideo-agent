"""Génère la clé de connexion Google Authenticator (TOTP) à mettre dans .env.

Usage : .venv/bin/python scripts/totp_setup.py vous@exemple.com
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.core.totp import generate_secret, provisioning_uri, totp_now  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2 or "@" not in sys.argv[1]:
        sys.exit("Usage : python scripts/totp_setup.py <email du compte>")
    email = sys.argv[1].strip()
    secret = generate_secret()
    uri = provisioning_uri(secret, email)
    print("1. Ajoutez ces lignes à .env puis redémarrez l'appli (docker restart cutevideo) :\n")
    print(f"TOTP_SECRET={secret}")
    print(f"TOTP_LOGIN_EMAIL={email}\n")
    print("2. Dans Google Authenticator : « + » → « Saisir une clé de configuration »")
    print(f"   Compte : CuteVideo ({email}) · Clé : {secret} · Basée sur l'heure\n")
    try:
        import qrcode  # type: ignore[import-not-found]

        qr = qrcode.QRCode(border=1)
        qr.add_data(uri)
        qr.print_ascii(invert=True)
    except ImportError:
        print(f"   (ou un QR code généré à partir de : {uri})")
    print(f"\nCode actuel attendu (pour vérifier) : {totp_now(secret)}")


if __name__ == "__main__":
    main()

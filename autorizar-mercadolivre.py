"""Inicia OAuth localmente; nenhuma credencial é exibida."""
import argparse

from services.cloud import cloud_request


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "status"), default="start", nargs="?")
    args = parser.parse_args()
    result = cloud_request("mercadolivre-callback/" + args.action)
    if args.action == "start":
        print("Abra este link privado no navegador e autorize a aplicação. Expira em dez minutos:")
        print(result["authorization_url"])
    else:
        print("Conectado:", result.get("connected", False))
        print("Requer revisão:", result.get("requires_review", False))
        if result.get("last_error"):
            error = result["last_error"]
            print("Ultima falha:", error.get("phase"), error.get("code"), error.get("provider_code") or "")

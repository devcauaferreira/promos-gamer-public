"""Inicializa o estado remoto uma única vez. Pare o monitor local antes de executar."""
from services.cloud import CloudState
from services.settings import load_settings


if __name__ == "__main__":
    config, _ = load_settings()
    CloudState(config.database_path).initialize_from_local()
    print("Histórico inicial enviado ao estado privado. Use somente um monitor após a migração.")

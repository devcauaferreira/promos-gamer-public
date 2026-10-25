"""Monitor de preços reais com publicação opcional em grupo do WhatsApp."""
import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from config import Config
from database.models import Offer, connect
from services.price_history import record_price
from services.discount_filter import evaluate
from services.message_builder import build_message


def demo(path):
    config = Config(database_path=path, trusted_sellers=frozenset({("demo", "loja-demo")}))
    with closing(connect(path)) as db:
        now = datetime.now(timezone.utc)
        for days, price in [(4, 48000), (3, 50000), (2, 49000)]:
            record_price(db, "demo", "ryzen-5500", price, now - timedelta(days=days))
        offer = Offer("demo", "ryzen-5500", "Ryzen 5 5500", "loja-demo",
                      38000, 0, "à vista", True, "https://example.com/oferta", True)
        decision = evaluate(db, offer, config, now)
        print(build_message(offer, decision))
        print("Status:", decision.status)
        for reason in decision.reasons:
            print("-", reason)
        record_price(db, offer.store, offer.product_id, offer.total_cents, now)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--collect", action="store_true", help="Coleta real sem envio")
    parser.add_argument("--send", action="store_true", help="Coleta e envia ofertas aprovadas")
    parser.add_argument("--watch", action="store_true", help="Repete a coleta no intervalo configurado")
    parser.add_argument("--visible", action="store_true", help="Exibe o navegador da coleta")
    parser.add_argument("--add", metavar="URL", help="Cadastra um link de produto das cinco lojas")
    parser.add_argument("--groups", action="store_true", help="Lista grupos da sessão conectada")
    parser.add_argument("--choose-group", action="store_true", help="Escolhe o grupo pelo número")
    parser.add_argument("--discover", action="store_true", help="Busca produtos nas cinco lojas sem publicar")
    parser.add_argument("--status", action="store_true", help="Mostra o relatório de cobertura das lojas")
    parser.add_argument("--sources", action="store_true", help="Mostra acesso/configuração de cada fonte, sem consultar lojas")
    parser.add_argument("--reset-source", metavar="LOJA", help="Libera nova tentativa após corrigir acesso da fonte")
    parser.add_argument("--check-source", metavar="LOJA", help="Valida uma fonte isolada, sem publicar mensagens")
    args = parser.parse_args()
    if args.demo:
        with TemporaryDirectory() as folder:
            demo(Path(folder) / "demo.sqlite3")
    elif args.add:
        import json
        from collectors.catalog import canonical_product, store_for_url
        store = store_for_url(args.add)
        key, url = canonical_product(args.add)
        path = Path("products.json")
        entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        if not any(entry["id"] == key for entry in entries):
            entries.append({"id": key, "store": store, "url": url,
                            "enabled": True, "payment_terms": ""})
            path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Produto cadastrado. Confirme a condição de pagamento em products.json.")
    elif args.check_source:
        import json
        from collectors.catalog import DOMAINS
        from collectors.registry import LazyBrowser, build_sources
        from services.settings import load_settings
        if args.check_source not in DOMAINS:
            parser.error("Loja inválida")
        config, settings = load_settings()
        browser = LazyBrowser(args.visible)
        with closing(connect(config.database_path)) as db:
            try:
                source = build_sources(db, settings, browser)[args.check_source]
                health = source.status()
                if "error" in health:
                    print(f"{args.check_source}: {health['state']} — {health['error']}")
                else:
                    entries = json.loads(Path("products.json").read_text(encoding="utf-8")) if Path("products.json").exists() else []
                    entries = [entry for entry in entries if entry["store"] == args.check_source and entry.get("enabled", True)]
                    if source.mode == "official_catalog":
                        entries = [entry for entry in entries if entry.get("catalog_id")]
                    entries = entries or source.search("processador", 1)
                    if entries:
                        offer = source.collect(entries[0])
                        print(f"Fonte validada: {args.check_source} [{offer.source}] — {offer.title}")
                        print(f"Preço: {offer.price_cents} centavos; estoque disponível: {offer.available}. Nenhuma mensagem enviada.")
                    else:
                        print("Fonte consultada sem produtos. Configure anúncios específicos ou um feed atualizado.")
            except Exception as exc:
                print(f"Falha na validação: {exc}")
            finally:
                browser.close()
    elif args.sources or args.reset_source:
        import json
        from services.settings import load_settings
        from collectors.registry import LazyBrowser, build_sources, source_report
        from collectors.catalog import DOMAINS
        config, settings = load_settings()
        with closing(connect(config.database_path)) as db:
            sources = build_sources(db, settings, LazyBrowser())
            if args.reset_source:
                if args.reset_source not in DOMAINS:
                    parser.error("Loja inválida")
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='discovery_runs'").fetchone():
                    db.execute("DELETE FROM discovery_runs WHERE store=?", (args.reset_source,))
                db.execute("DELETE FROM source_health WHERE store=?", (args.reset_source,))
                db.commit()
                print("Suspensão removida. Uma nova tentativa ocorrerá no próximo ciclo.")
            report = source_report(sources)
            Path("reports").mkdir(exist_ok=True)
            Path("reports/sources.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            for row in report:
                print(f"{row['store']} [{row['mode']}]: {row['state']} — {row.get('error', 'sem pendências locais de acesso')}")
    elif args.status:
        import json
        path = Path("reports/discovery.json")
        if path.exists():
            for row in json.loads(path.read_text(encoding="utf-8")):
                print(f"{row['store']}/{row['category']}: {row.get('error') or str(row.get('found', 0)) + ' produtos'}")
        else:
            print("Busca automática ainda não executada.")
        sources_path = Path("reports/sources.json")
        if sources_path.exists():
            print("\nFontes de dados:")
            for row in json.loads(sources_path.read_text(encoding="utf-8")):
                print(f"{row['store']} [{row['mode']}]: {row['state']} — {row.get('error', 'sem pendências locais de acesso')}")
    elif args.groups or args.choose_group:
        import json
        from publishers.whatsapp import bridge_token
        from urllib.request import Request, urlopen
        request = Request("http://127.0.0.1:8787/groups", headers={"Authorization": "Bearer " + bridge_token()})
        try:
            with urlopen(request, timeout=30) as response:
                groups = json.load(response)
            if args.choose_group:
                if not groups:
                    print("Nenhum grupo encontrado. Crie o grupo no celular e aguarde a sincronização.")
                else:
                    for number, group in enumerate(groups, 1):
                        print(f"{number}. {group['name']}")
                    answer = input("Número do grupo para receber ofertas (Enter cancela): ").strip()
                    if answer:
                        if not answer.isdigit() or not 1 <= int(answer) <= len(groups):
                            raise ValueError("Número inválido. Nenhuma alteração realizada.")
                        selected = groups[int(answer) - 1]
                        path = Path("settings.json")
                        settings = json.loads(path.read_text(encoding="utf-8"))
                        settings["whatsapp_group_id"] = selected["id"]
                        path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
                        print(f"Grupo selecionado: {selected['name']}. Nenhuma mensagem foi enviada.")
            else:
                print(json.dumps(groups, ensure_ascii=False, indent=2))
        except Exception as exc:
            print(f"Não foi possível selecionar/listar grupos: {exc}")
            print("Mantenha conectar-whatsapp.cmd aberto e aguarde o WhatsApp conectar.")
    elif args.collect or args.send or args.watch or args.discover:
        from services.runner import cycle
        from services.settings import load_settings
        import time
        try:
            while True:
                try:
                    cycle(send=args.send and not args.discover, visible=args.visible,
                          discover_only=args.discover, force_discovery=args.discover)
                except Exception as exc:
                    if not args.watch:
                        raise
                    print(f"Falha no ciclo: {exc}. Nova tentativa no próximo intervalo.", flush=True)
                if not args.watch:
                    break
                _, settings = load_settings()
                time.sleep(int(settings.get("interval_seconds", 1800)))
        except KeyboardInterrupt:
            print("Monitor encerrado.")
    else:
        parser.print_help()

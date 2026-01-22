def main():
    print("Replay starting...")

    from runners.data_loader import load_csv_bars
    from runners.replay import ReplayEngine
    from strategies.factory import build_ict_from_yaml

    # Choose ES or NQ config here
    config_path = "config/strategies/ict_es.yaml"
    csv_path = "data/es_1m.csv"

    print(f"Config: {config_path}")
    print(f"Using data: {csv_path}")

    strategy = build_ict_from_yaml(config_path)
    bars = load_csv_bars(csv_path)

    engine = ReplayEngine(strategy)
    result = engine.run(bars)

    print(f"Bars processed: {result.bars_processed}")
    print(f"Signals: {len(result.signals)}")

    # Print first few signals for sanity
    for s in result.signals[:5]:
        print(s)

if __name__ == "__main__":
    main()

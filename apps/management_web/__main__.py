import argparse

from .app import create_app


def main():
    parser = argparse.ArgumentParser(description="Fishery management Web R1 (Demo, no model requests)")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    app = create_app(allowed_hosts=(f"127.0.0.1:{args.port}", f"localhost:{args.port}"))
    print(f"Management Web · Demo: http://127.0.0.1:{args.port}", flush=True)
    app.run(host="127.0.0.1", port=args.port, debug=False, load_dotenv=False)


if __name__ == "__main__":
    main()

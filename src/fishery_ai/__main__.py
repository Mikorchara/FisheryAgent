"""Offline command line demo."""

import argparse
import json
import socket
import sys

from .application import result_to_dict
from .composition import build_offline_demo
from .contracts import AnalysisRequest, Mode


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description="Fishery AI V0.1 offline demo")
    parser.add_argument("demo", choices=["demo"])
    parser.add_argument("--profile", choices=["cloud-demo", "local-demo"], default="cloud-demo")
    parser.add_argument("--scenario", choices=["normal", "low_oxygen", "partial", "stale", "partial_stale"],
                        default="low_oxygen")
    parser.add_argument("--mode", choices=["chat", "advice"], default="advice")
    parser.add_argument("--question", default="当前水质有哪些风险？")
    args = parser.parse_args()
    def deny_network(*_args, **_kwargs):
        raise RuntimeError("network access is disabled in the offline demo")
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    socket.socket.sendto = deny_network
    socket.create_connection = deny_network
    orchestrator, _ = build_offline_demo()
    request = AnalysisRequest(Mode(args.mode), args.profile, args.question if args.mode == "chat" else "")
    result = orchestrator.analyze(request, scenario=args.scenario)
    print(json.dumps(result_to_dict(result), ensure_ascii=False, indent=2))
    print("\nOffline MockGateway used. No model or network request was made.")


if __name__ == "__main__":
    main()

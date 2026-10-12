"""Offline command line demo."""

import argparse
import json
import socket
import sys

from .application import result_to_dict
from .composition import build_offline_demo
from .contracts import AnalysisRequest, Mode, UsageAccumulator


def _usage_lines(usage, *, title: str) -> str:
    def show(value):
        return "unavailable" if value is None else str(value)
    return "\n".join((
        title,
        f"Input Tokens: {show(usage.input_tokens)}",
        f"Output Tokens: {show(usage.output_tokens)}",
        f"Reasoning Tokens: {show(usage.reasoning_tokens)}",
        f"Cached Input Tokens: {show(usage.cached_input_tokens)}",
        f"Total Tokens: {show(usage.total_tokens)}",
        f"Source: {usage.source.value}",
    ))


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description="Fishery AI demo, validation or local developer UI")
    parser.add_argument("command", choices=["demo", "validate-real", "web"])
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--profile", choices=["cloud-demo", "local-demo"], default="cloud-demo")
    parser.add_argument("--scenario", choices=["normal", "low_oxygen", "partial", "stale", "partial_stale"],
                        default="low_oxygen")
    parser.add_argument("--mode", choices=["chat", "advice"], default="advice")
    parser.add_argument("--question", default="当前水质有哪些风险？")
    parser.add_argument("--check", default="basic",
                        choices=["network", "basic", "auto", "on", "off", "effort-low", "temperature", "top-p",
                                 "output-limit", "stream", "full-chain", "invalid-model"])
    parser.add_argument("--confirm-network", action="store_true")
    args = parser.parse_args()
    if args.command == "web":
        if not 1 <= args.port <= 65535:
            parser.error("--port must be between 1 and 65535")
        from .web import run_web
        run_web(port=args.port)
        return
    if args.command == "validate-real":
        from .development.qualification.real_validation import run_real_validation
        raise SystemExit(run_real_validation(
            check=args.check, scenario=args.scenario, confirm_network=args.confirm_network))
    def deny_network(*_args, **_kwargs):
        raise RuntimeError("network access is disabled in the offline demo")
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    socket.socket.sendto = deny_network
    socket.create_connection = deny_network
    socket.getaddrinfo = deny_network
    orchestrator, _ = build_offline_demo()
    request = AnalysisRequest(Mode(args.mode), args.profile, args.question if args.mode == "chat" else "")
    result = orchestrator.analyze(request, scenario=args.scenario)
    print(json.dumps(result_to_dict(result), ensure_ascii=False, indent=2))
    session = UsageAccumulator()
    session.add(result.usage)
    print("\n" + _usage_lines(result.usage, title="Request Usage"))
    print("\n" + _usage_lines(session.snapshot().usage, title="Validation Session Usage"))
    print(f"Requests with provider usage: {session.snapshot().reported_count}/{session.snapshot().request_count}")
    print("\nOffline MockGateway used. No model or network request was made.")


if __name__ == "__main__":
    main()

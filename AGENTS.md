# Instructions for AI coding assistants

## Project Purpose

This project is a fishery AI architecture prototype. It studies LLM integration, RAG, Tool architecture, and Agent evolution. Current V0.1 behavior is a fixed offline-capable analysis flow.

## Architecture Principles

1. Deterministic facts come from programs and data sources.
2. LLM responsibilities are reasoning, explanation, and natural-language interaction.
3. Do not let an LLM invent sensor values, detection results, or database facts.
4. Keep RAG, Tools, Memory, Database, and Agent as separate concepts.
5. Do not introduce frameworks without a concrete requirement.

## Development Rules

- Before major changes, explain the reason, identify affected modules, and update documentation.
- Treat `_` in Windows paths as a literal character; prefer PowerShell `-LiteralPath` for file operations.
- Do not modify `D:\Fishery_Project`; it is a read-only reference.
- Do not commit secrets or local model files.
- Do not add unused abstractions or unnecessary empty modules.

## Testing Rules

- Preserve offline tests with every change.
- Avoid real API calls in tests.
- Add tests for new behavior.

# macOS TTS deployment

## ADDED Requirements

### Requirement: macOS TTS runs on native-host Kokoro

On macOS (Apple Silicon), the system SHALL run Kokoro TTS as a native host process
(reachable by the Docker services via `host.docker.internal:8880`) rather than as the
CPU-TTS Docker container, because Docker Desktop on macOS cannot pass the Apple GPU into
a container. The native process SHALL default to the Metal/MPS backend and SHALL offer a
CPU backend as a documented fallback.

#### Scenario: Agent reaches native Kokoro on macOS

- **WHEN** the stack is started with `-f docker-compose.yml -f docker-compose.macos.yml`
- **THEN** the in-stack `kokoro` container is a no-op stub (publishes no port)
- **AND** the agent's `KOKORO_BASE_URL` resolves to `http://host.docker.internal:8880/v1`
- **AND** the native Kokoro server answers `GET /health` with 200 from both host and
  container.

#### Scenario: Bring-up helper defaults to Metal with a CPU fallback

- **WHEN** an operator runs `scripts/kokoro-native-macos.sh` with no backend flag
- **THEN** the helper starts the pinned (`v0.5.0`) Kokoro-FastAPI on the Metal/MPS backend
  bound to `0.0.0.0:8880`
- **AND** running it with `--cpu` instead starts the CPU backend on the same port
- **AND** the `stop` subcommand terminates the backgrounded server.

"""AgentSession option guardrails."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_session_disables_aec_warmup_for_barge_in() -> None:
    source = (ROOT / "agent" / "main.py").read_text(encoding="utf-8")

    assert "AEC_WARMUP_DURATION_S: float = 0.0" in source
    assert "aec_warmup_duration=AEC_WARMUP_DURATION_S" in source


def test_session_keeps_false_interruption_resume_enabled() -> None:
    source = (ROOT / "agent" / "main.py").read_text(encoding="utf-8")

    assert "RESUME_FALSE_INTERRUPTION: bool = True" in source
    assert '"resume_false_interruption": RESUME_FALSE_INTERRUPTION' in source


if __name__ == "__main__":
    test_session_disables_aec_warmup_for_barge_in()
    test_session_keeps_false_interruption_resume_enabled()
    print("ok: AgentSession options")

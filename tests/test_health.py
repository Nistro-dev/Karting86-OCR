from apex_ocr.health import HealthMonitor, HealthStatus
from apex_ocr.session import SessionState


def test_idle_when_no_failures_and_not_running():
    h = HealthMonitor(error_threshold=5)
    assert h.status_for(SessionState.WAITING) == HealthStatus.IDLE
    assert h.status_for(SessionState.ARMED) == HealthStatus.IDLE


def test_active_when_running():
    h = HealthMonitor(error_threshold=5)
    assert h.status_for(SessionState.RUNNING) == HealthStatus.ACTIVE


def test_error_after_threshold_failures_overrides_running():
    h = HealthMonitor(error_threshold=3)
    for _ in range(3):
        h.record_capture_failure()
    assert h.is_erroring
    assert h.status_for(SessionState.RUNNING) == HealthStatus.ERROR


def test_success_resets_failure_streak():
    h = HealthMonitor(error_threshold=3)
    h.record_capture_failure()
    h.record_capture_failure()
    h.record_capture_success()
    h.record_capture_failure()
    assert not h.is_erroring
    assert h.status_for(SessionState.WAITING) == HealthStatus.IDLE

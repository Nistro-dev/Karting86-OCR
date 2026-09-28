"""Veille / session Windows : traduction des messages en callbacks (logique pure)."""
from apex_ocr import power


def make_monitor():
    posted = []
    events = []
    m = power.PowerMonitor(
        post=lambda fn: posted.append(fn),
        on_suspend=lambda: events.append("suspend"),
        on_resume=lambda: events.append("resume"),
        on_lock=lambda: events.append("lock"),
        on_unlock=lambda: events.append("unlock"),
    )
    return m, posted, events


def test_suspend_then_resume_once_even_if_windows_sends_two_resume_messages():
    m, posted, events = make_monitor()
    assert m.dispatch(power.WM_POWERBROADCAST, power.PBT_APMSUSPEND) == "suspend"
    assert m.dispatch(power.WM_POWERBROADCAST, power.PBT_APMRESUMEAUTOMATIC) == "resume"
    assert m.dispatch(power.WM_POWERBROADCAST, power.PBT_APMRESUMESUSPEND) is None   # déjà repris
    for fn in posted:
        fn()
    assert events == ["suspend", "resume"]


def test_resume_without_suspend_is_ignored():
    m, posted, _ = make_monitor()
    assert m.dispatch(power.WM_POWERBROADCAST, power.PBT_APMRESUMEAUTOMATIC) is None
    assert posted == []


def test_session_lock_unlock():
    m, posted, events = make_monitor()
    assert m.dispatch(power.WM_WTSSESSION_CHANGE, power.WTS_SESSION_LOCK) == "lock"
    assert m.dispatch(power.WM_WTSSESSION_CHANGE, power.WTS_SESSION_UNLOCK) == "unlock"
    assert m.dispatch(0x0001, 0) is None
    for fn in posted:
        fn()
    assert events == ["lock", "unlock"]


def test_post_failure_does_not_raise():
    def broken(fn):
        raise RuntimeError("main thread is not in main loop")
    m = power.PowerMonitor(post=broken, on_suspend=lambda: None)
    assert m.dispatch(power.WM_POWERBROADCAST, power.PBT_APMSUSPEND) == "suspend"

from apex_ocr.ocr.parsing import LenientReading, StrictReading
from apex_ocr.session import SessionEvent, SessionState, StopReason, SessionTracker, current_display


def strict(time_text, laps_done=None, laps_total=None):
    return StrictReading(time_text=time_text, laps_done=laps_done, laps_total=laps_total)


def lenient(time_text=None, laps_done=None, laps_total=None):
    return LenientReading(time_text=time_text, laps_done=laps_done, laps_total=laps_total)


def test_waiting_to_armed_on_first_valid_reading():
    t = SessionTracker()
    events = t.on_strict_reading(strict("10:00"), now=0.0)
    assert events == [SessionEvent.ARMED]
    assert t.state == SessionState.ARMED


def test_armed_stays_armed_if_time_does_not_decrease():
    t = SessionTracker()
    t.on_strict_reading(strict("10:00"), now=0.0)
    events = t.on_strict_reading(strict("10:00"), now=1.0)
    assert events == []
    assert t.state == SessionState.ARMED

    events = t.on_strict_reading(strict("10:05"), now=2.0)
    assert events == []
    assert t.state == SessionState.ARMED


def test_single_noisy_dip_does_not_falsely_start_session():
    """Une frame OCR isolée qui lit une valeur plus basse sur un timer par
    ailleurs statique ne doit pas suffire à déclencher un départ."""
    t = SessionTracker()
    t.on_strict_reading(strict("10:00"), now=0.0)
    events = t.on_strict_reading(strict("09:59"), now=1.0)
    assert events == []
    assert t.state == SessionState.ARMED

    events = t.on_strict_reading(strict("10:00"), now=2.0)
    assert events == []
    assert t.state == SessionState.ARMED


def test_armed_to_running_requires_two_consecutive_decreases():
    t = SessionTracker()
    t.on_strict_reading(strict("10:00"), now=0.0)

    events = t.on_strict_reading(strict("09:59"), now=1.0)
    assert events == []
    assert t.state == SessionState.ARMED

    events = t.on_strict_reading(strict("09:58"), now=2.0)
    assert events == [SessionEvent.STARTED]
    assert t.state == SessionState.RUNNING
    assert t.live_display(now=2.0).time_text == "09:58"


def test_running_clock_counts_down_smoothly_without_ocr():
    t = SessionTracker()
    t.on_strict_reading(strict("10:00"), now=0.0)
    t.on_strict_reading(strict("09:59"), now=1.0)
    t.on_strict_reading(strict("09:58"), now=2.0)  # départ confirmé, 598s @ now=2.0

    live = t.live_display(now=12.0)
    assert live.time_text == "09:48"


def test_tick_stops_session_at_zero():
    t = SessionTracker()
    t.on_strict_reading(strict("00:04"), now=0.0)
    t.on_strict_reading(strict("00:03"), now=1.0)
    t.on_strict_reading(strict("00:02"), now=2.0)  # départ confirmé, 2s @ now=2.0

    assert t.tick(now=3.5) == []
    events = t.tick(now=4.0)
    assert events == [SessionEvent.STOPPED]
    assert t.state == SessionState.WAITING
    assert t.last_completed.time_text == "00:00"
    assert t.last_completed.reason == StopReason.TIME_ZERO


def test_laps_update_immediately_and_stop_on_completion():
    t = SessionTracker()
    t.on_strict_reading(strict("10:00", laps_done=0, laps_total=2), now=0.0)
    t.on_strict_reading(strict("09:59", laps_done=0, laps_total=2), now=1.0)
    t.on_strict_reading(strict("09:58", laps_done=0, laps_total=2), now=2.0)
    assert t.state == SessionState.RUNNING

    events = t.on_lenient_reading(lenient(time_text="09:57", laps_done=1, laps_total=2), now=3.0)
    assert SessionEvent.LAPS_UPDATED in events
    assert t.live_display(now=3.0).laps_done == 1

    events = t.on_lenient_reading(lenient(time_text="05:00", laps_done=2, laps_total=2), now=4.0)
    assert SessionEvent.STOPPED in events
    assert t.last_completed.reason == StopReason.LAPS_COMPLETE
    assert t.last_completed.laps_done == 2


def test_time_not_updated_directly_only_resynced_beyond_tolerance():
    t = SessionTracker(resync_tolerance_seconds=3)
    t.on_strict_reading(strict("10:00"), now=0.0)
    t.on_strict_reading(strict("09:59"), now=1.0)
    t.on_strict_reading(strict("09:58"), now=2.0)  # départ confirmé, 598s @ now=2.0

    # 5s plus tard, l'horloge interne dit 09:53 ; l'OCR lit 09:52 -> 1s d'écart, pas de resync
    events = t.on_lenient_reading(lenient(time_text="09:52"), now=7.0)
    assert SessionEvent.RESYNCED not in events
    assert t.live_display(now=7.0).time_text == "09:53"

    # grand écart -> resync
    events = t.on_lenient_reading(lenient(time_text="09:39"), now=7.0)
    assert SessionEvent.RESYNCED in events
    assert t.live_display(now=7.0).time_text == "09:39"


def test_format_self_heals_if_first_arming_reading_missed_the_hour_digit():
    t = SessionTracker()
    # lecture initiale bruitée : le chiffre des heures a été raté par l'OCR
    t.on_strict_reading(strict("23:33"), now=0.0)
    # lecture suivante correcte : 01:23:30 (> 23:33, ne confirme rien -> nouveau candidat)
    t.on_strict_reading(strict("01:23:30"), now=1.0)
    # deux baisses de suite confirment le départ
    t.on_strict_reading(strict("01:23:29"), now=2.0)
    t.on_strict_reading(strict("01:23:28"), now=3.0)

    live = t.live_display(now=3.0)
    assert live.time_text == "01:23:28"  # et pas "83:28"


def test_format_switches_dynamically_based_on_latest_reading():
    t = SessionTracker(resync_tolerance_seconds=5)
    t.on_strict_reading(strict("00:01:30"), now=0.0)
    t.on_strict_reading(strict("00:01:29"), now=1.0)
    t.on_strict_reading(strict("00:01:28"), now=2.0)
    assert t.live_display(now=2.0).time_text.count(":") == 2  # hh:mm:ss

    # la source repasse en mm:ss (plus d'heure affichée) : le format suit
    t.on_lenient_reading(lenient(time_text="00:26"), now=62.0)
    assert t.live_display(now=62.0).time_text.count(":") == 1  # mm:ss


def test_laps_appearing_mid_session_are_detected_even_though_absent_at_start():
    # armée/démarrée sans tours détectés (lecture initiale sans "/tt")
    t = SessionTracker()
    t.on_strict_reading(strict("10:00"), now=0.0)
    t.on_strict_reading(strict("09:59"), now=1.0)
    t.on_strict_reading(strict("09:58"), now=2.0)
    assert t.state == SessionState.RUNNING
    assert t.live_display(now=2.0).laps_done is None

    events = t.on_lenient_reading(lenient(time_text="09:57", laps_done=1, laps_total=20), now=3.0)
    assert SessionEvent.LAPS_UPDATED in events
    assert t.live_display(now=3.0).laps_done == 1


def test_laps_reading_lower_than_known_is_ignored_as_noise():
    t = SessionTracker()
    t.on_strict_reading(strict("10:00", laps_done=0, laps_total=20), now=0.0)
    t.on_strict_reading(strict("09:59", laps_done=0, laps_total=20), now=1.0)
    t.on_strict_reading(strict("09:58", laps_done=0, laps_total=20), now=2.0)

    t.on_lenient_reading(lenient(time_text="09:57", laps_done=5, laps_total=20), now=3.0)
    assert t.live_display(now=3.0).laps_done == 5

    # lecture aberrante (5 mal lu comme 1) : ignorée, on garde 5
    events = t.on_lenient_reading(lenient(time_text="09:56", laps_done=1, laps_total=20), now=4.0)
    assert SessionEvent.LAPS_UPDATED not in events
    assert t.live_display(now=4.0).laps_done == 5


def test_live_display_shows_new_value_immediately_while_cancellation_pending():
    t = SessionTracker(resync_tolerance_seconds=3)
    t.on_strict_reading(strict("10:00"), now=0.0)
    t.on_strict_reading(strict("09:59"), now=1.0)
    t.on_strict_reading(strict("09:58"), now=2.0)  # 598s @ now=2.0

    # 1ère lecture "10:00" pas encore confirmée -> pas d'arrêt, mais déjà affichée
    events = t.on_lenient_reading(lenient(time_text="10:00"), now=5.0)
    assert events == []
    assert t.state == SessionState.RUNNING
    assert t.live_display(now=5.0).time_text == "10:00"  # pas "09:35" (horloge interne périmée)


def test_time_jumping_back_up_cancels_session_after_two_confirmations():
    t = SessionTracker(resync_tolerance_seconds=3)
    t.on_strict_reading(strict("10:00"), now=0.0)
    t.on_strict_reading(strict("09:59"), now=1.0)
    t.on_strict_reading(strict("09:58"), now=2.0)
    assert t.state == SessionState.RUNNING

    # la source revient à son temps de base (ex: bouton Stop sur Apex Timing) :
    # une seule lecture ne suffit pas (pourrait être du bruit)
    events = t.on_lenient_reading(lenient(time_text="10:00"), now=5.0)
    assert events == []
    assert t.state == SessionState.RUNNING

    events = t.on_lenient_reading(lenient(time_text="10:00"), now=5.5)
    assert events == [SessionEvent.STOPPED]
    assert t.state == SessionState.WAITING
    assert t.last_completed.reason == StopReason.CANCELLED
    assert t.last_completed.time_text == "10:00"


def test_small_upward_drift_within_tolerance_is_not_a_cancellation():
    t = SessionTracker(resync_tolerance_seconds=3)
    t.on_strict_reading(strict("10:00"), now=0.0)
    t.on_strict_reading(strict("09:59"), now=1.0)
    t.on_strict_reading(strict("09:58"), now=2.0)

    events = t.on_lenient_reading(lenient(time_text="09:56"), now=6.0)
    assert events == []
    assert t.state == SessionState.RUNNING


def test_ocr_lost_stops_session_after_sustained_timeout():
    t = SessionTracker(ocr_lost_timeout_seconds=5.0)
    t.on_strict_reading(strict("10:00"), now=0.0)
    t.on_strict_reading(strict("09:59"), now=1.0)
    t.on_strict_reading(strict("09:58"), now=2.0)  # départ, last_good_time_wall=2.0

    # de brefs trous (quelques lectures ratées ponctuelles) ne doivent rien casser
    assert t.on_lenient_reading(lenient(time_text=None), now=3.0) == []
    assert t.on_lenient_reading(lenient(time_text=None), now=4.0) == []
    assert t.on_lenient_reading(lenient(time_text=None), now=6.9) == []  # < 5s depuis 2.0

    events = t.on_lenient_reading(lenient(time_text=None), now=7.0)  # >= 5s sans lecture valide
    assert events == [SessionEvent.STOPPED]
    assert t.last_completed.reason == StopReason.OCR_LOST


def test_intermittent_valid_reading_resets_ocr_lost_timeout():
    t = SessionTracker(ocr_lost_timeout_seconds=5.0)
    t.on_strict_reading(strict("10:00"), now=0.0)
    t.on_strict_reading(strict("09:59"), now=1.0)
    t.on_strict_reading(strict("09:58"), now=2.0)

    assert t.on_lenient_reading(lenient(time_text=None), now=6.0) == []  # 4s, ok
    # une lecture valide relance le compteur
    t.on_lenient_reading(lenient(time_text="09:52"), now=6.5)
    assert t.on_lenient_reading(lenient(time_text=None), now=11.0) == []  # 4.5s depuis 6.5, ok
    assert t.state == SessionState.RUNNING


def test_laps_only_miss_does_not_reset_time_ocr_lost_timeout():
    t = SessionTracker(ocr_lost_timeout_seconds=5.0)
    t.on_strict_reading(strict("10:00", laps_done=0, laps_total=20), now=0.0)
    t.on_strict_reading(strict("09:59", laps_done=0, laps_total=20), now=1.0)
    t.on_strict_reading(strict("09:58", laps_done=0, laps_total=20), now=2.0)

    # les tours continuent d'être lus, mais jamais le temps -> le compteur ne se réinitialise pas
    t.on_lenient_reading(lenient(time_text=None, laps_done=1, laps_total=20), now=3.0)
    t.on_lenient_reading(lenient(time_text=None, laps_done=2, laps_total=20), now=5.0)
    events = t.on_lenient_reading(lenient(time_text=None, laps_done=3, laps_total=20), now=7.5)
    assert SessionEvent.STOPPED in events


def test_reading_none_while_waiting_is_ignored():
    t = SessionTracker()
    assert t.on_strict_reading(None, now=0.0) == []
    assert t.state == SessionState.WAITING


def test_armed_display_shows_pending_value_immediately():
    t = SessionTracker()
    t.on_strict_reading(strict("10:00", laps_done=0, laps_total=20), now=0.0)
    d = current_display(t, now=0.0)
    assert d.time_text == "10:00" and d.laps_done == 0 and d.laps_total == 20 and d.is_live


def test_armed_display_replaces_stale_frozen_result_from_previous_session():
    t = SessionTracker()
    # une session se termine (temps écoulé), fige un résultat
    t.on_strict_reading(strict("00:05"), now=0.0)
    t.on_strict_reading(strict("00:04"), now=1.0)
    t.on_strict_reading(strict("00:03"), now=2.0)  # départ confirmé, 3s @ now=2.0
    t.tick(now=100.0)  # bien après la fin -> TIME_ZERO, fige last_completed
    assert t.last_completed is not None

    # une nouvelle lecture statique arrive (nouveau format/nouvelle source)
    d = current_display(t, now=101.0)
    assert not d.is_live and d.time_text == t.last_completed.time_text  # encore figé, rien lu

    t.on_strict_reading(strict("10:00"), now=102.0)
    d = current_display(t, now=102.0)
    assert d.time_text == "10:00" and d.is_live  # remplace l'ancien résultat figé


def test_current_display_placeholder_then_live_then_frozen():
    t = SessionTracker()
    d = current_display(t, now=0.0)
    assert d.time_text == "--:--" and not d.is_live

    t.on_strict_reading(strict("00:04"), now=0.0)
    t.on_strict_reading(strict("00:03"), now=1.0)
    t.on_strict_reading(strict("00:02"), now=2.0)
    d = current_display(t, now=2.0)
    assert d.time_text == "00:02" and d.is_live

    t.tick(now=4.0)
    d = current_display(t, now=4.0)
    assert d.time_text == "00:00" and not d.is_live

"""Dynamic scan progress tracker with tqdm-backed ETA estimation.

Uses headless tqdm instances (no terminal output) for accurate,
self-correcting ETA via exponential moving average smoothing.
Each phase gets its own tqdm bar; for phases without sub-progress
updates, synthetic elapsed-time ticks keep the ETA smooth.
"""

from __future__ import annotations

import io
import threading
import time

from tqdm import tqdm as _tqdm

_DEVNULL = io.StringIO()


class ScanProgressTracker:
    """Tracks multi-phase scan progress with tqdm-backed ETA.

    Each phase has an initial estimated duration (seconds).  As phases
    complete, their actual duration replaces the estimate so the total
    projected time (and therefore the ETA) stays accurate.
    """

    @classmethod
    def create(
        cls,
        phases: list[tuple[str, float]],
        state_dict: dict,
        cache_key: str = "",
    ) -> ScanProgressTracker:
        """Create a tracker with the given phase estimates."""
        return cls(phases, state_dict)

    def __init__(
        self,
        phases: list[tuple[str, float]],
        state_dict: dict,
    ) -> None:
        self._phase_names = [p[0] for p in phases]
        self._estimates: dict[str, float] = {p[0]: p[1] for p in phases}
        self._actuals: dict[str, float] = {}
        self._state = state_dict
        self._start = time.monotonic()
        self._phase_start: float | None = None
        self._current_phase: str | None = None
        self._label = ""
        self._sub_done = 0
        self._sub_total = 0
        self._high_water = 0
        self._phase_bar: _tqdm | None = None
        self._auto_push_stop = threading.Event()
        self._auto_push_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Auto-push: pushes tqdm-computed progress every 2s so the SSE
    # stream sees smooth updates even without explicit sub-progress.
    # For phases without sub-progress, generates synthetic ticks based
    # on elapsed time vs estimate.
    # ------------------------------------------------------------------

    def _auto_push_loop(self) -> None:
        while not self._auto_push_stop.wait(2.0):
            if self._current_phase is not None:
                if self._sub_total == 0 and self._phase_bar is not None:
                    est = self._estimates.get(self._current_phase, 180)
                    elapsed = self._elapsed_in_current
                    target_n = min(95, int(elapsed / max(est, 1) * 100))
                    delta = target_n - self._phase_bar.n
                    if delta > 0:
                        self._phase_bar.update(delta)
                self._push()

    def _start_auto_push(self) -> None:
        if self._auto_push_thread is None or not self._auto_push_thread.is_alive():
            self._auto_push_stop.clear()
            self._auto_push_thread = threading.Thread(
                target=self._auto_push_loop, daemon=True,
            )
            self._auto_push_thread.start()

    def _stop_auto_push(self) -> None:
        self._auto_push_stop.set()
        self._auto_push_thread = None

    # ------------------------------------------------------------------
    # Phase lifecycle
    # ------------------------------------------------------------------

    def start_phase(self, name: str, label: str) -> None:
        if self._current_phase and self._current_phase != name:
            self.complete_phase(self._current_phase)
        self._current_phase = name
        self._phase_start = time.monotonic()
        self._label = label
        self._sub_done = 0
        self._sub_total = 0
        if self._phase_bar is not None:
            self._phase_bar.close()
        self._phase_bar = _tqdm(total=100, file=_DEVNULL, smoothing=0.3, mininterval=0)
        self._push()
        self._start_auto_push()

    def complete_phase(self, name: str) -> None:
        if self._phase_start is not None:
            self._actuals[name] = time.monotonic() - self._phase_start
        self._phase_start = None
        if self._phase_bar is not None:
            remaining = self._phase_bar.total - self._phase_bar.n
            if remaining > 0:
                self._phase_bar.update(remaining)
        self._push()

    def update_within_phase(self, done: int, total: int, label: str) -> None:
        self._sub_done = done
        self._sub_total = total
        self._label = label
        if self._phase_bar is not None and total > 0:
            target_n = int(done / total * 100)
            delta = target_n - self._phase_bar.n
            if delta > 0:
                self._phase_bar.update(delta)
        self._push()

    def finish(self) -> None:
        self._stop_auto_push()
        if self._current_phase:
            self.complete_phase(self._current_phase)
        if self._phase_bar is not None:
            self._phase_bar.close()
            self._phase_bar = None
        elapsed = time.monotonic() - self._start
        self._label = f"Done in {int(elapsed)}s"
        self._state["progress"] = 100
        self._state["total"] = 100
        self._state["step"] = self._label

    def save_history(self, cache_key: str = "") -> None:
        """No-op. Kept for backward compatibility with callers."""

    # ------------------------------------------------------------------
    # Progress math (tqdm-backed)
    # ------------------------------------------------------------------

    @property
    def _estimated_total(self) -> float:
        total = 0.0
        for name in self._phase_names:
            if name in self._actuals:
                total += self._actuals[name]
            else:
                total += self._estimates[name]
        return max(total, 1.0)

    @property
    def _elapsed_in_current(self) -> float:
        if self._phase_start is None:
            return 0.0
        return time.monotonic() - self._phase_start

    @property
    def progress_pct(self) -> int:
        """Overall 0-99 progress across all phases. Never decreases."""
        completed_time = sum(self._actuals.values())

        if self._current_phase and self._current_phase not in self._actuals:
            current_est = self._estimates[self._current_phase]
            if self._phase_bar is not None and self._phase_bar.total > 0:
                frac = self._phase_bar.n / self._phase_bar.total
            else:
                frac = 0.0
            completed_time += current_est * min(frac, 0.95)

        pct = int(completed_time / self._estimated_total * 100)
        pct = max(0, min(99, pct))
        if pct > self._high_water:
            self._high_water = pct
        return self._high_water

    @property
    def _phase_eta(self) -> float:
        """ETA for the current phase using tqdm's smoothed rate."""
        if self._phase_bar is None:
            return 0.0
        fmt = self._phase_bar.format_dict
        rate = fmt.get("rate")
        n = fmt.get("n", 0)
        total = fmt.get("total", 100)
        remaining_units = total - n
        if rate and rate > 0 and remaining_units > 0:
            return remaining_units / rate
        est = self._estimates.get(self._current_phase or "", 60)
        elapsed = self._elapsed_in_current
        return max(0, est - elapsed)

    @property
    def eta_seconds(self) -> float:
        """Estimated seconds remaining for current + all future phases."""
        current_remaining = self._phase_eta if self._current_phase else 0.0

        future_time = 0.0
        past_current = False
        for name in self._phase_names:
            if name == self._current_phase:
                past_current = True
                continue
            if past_current and name not in self._actuals:
                future_time += self._estimates[name]

        return current_remaining + future_time

    @property
    def eta_str(self) -> str:
        remaining = self.eta_seconds
        if remaining < 5:
            return " · almost done"
        if remaining < 60:
            return f" · ~{int(remaining)}s left"
        return f" · ~{int(remaining // 60)}m {int(remaining % 60)}s left"

    @property
    def step(self) -> str:
        return self._label + self.eta_str

    # ------------------------------------------------------------------
    # Push to state dict
    # ------------------------------------------------------------------

    def _push(self) -> None:
        self._state["progress"] = self.progress_pct
        self._state["total"] = 100
        self._state["step"] = self.step

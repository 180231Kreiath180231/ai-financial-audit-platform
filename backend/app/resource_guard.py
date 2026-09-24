from __future__ import annotations

from dataclasses import dataclass

CPU_PAUSE_PERCENT = 50.0
CPU_RESUME_PERCENT = 30.0
MEMORY_BLOCK_PERCENT = 70.0
CPU_SUSTAIN_SECONDS = 10.0


@dataclass(frozen=True)
class ResourceTransition:
    kind: str
    cpu_percent: float
    memory_percent: float


class ResourceGuard:
    """Track sustained CPU pressure and immediate memory admission pressure."""

    def __init__(
        self,
        *,
        cpu_pause_percent: float = CPU_PAUSE_PERCENT,
        cpu_resume_percent: float = CPU_RESUME_PERCENT,
        memory_block_percent: float = MEMORY_BLOCK_PERCENT,
        cpu_sustain_seconds: float = CPU_SUSTAIN_SECONDS,
    ) -> None:
        self.cpu_pause_percent = cpu_pause_percent
        self.cpu_resume_percent = cpu_resume_percent
        self.memory_block_percent = memory_block_percent
        self.cpu_sustain_seconds = cpu_sustain_seconds
        self.cpu_paused = False
        self.memory_blocked = False
        self._cpu_high_since: float | None = None
        self._cpu_low_since: float | None = None

    @property
    def admission_blocked(self) -> bool:
        return self.cpu_paused or self.memory_blocked

    def observe(
        self, cpu_percent: float, memory_percent: float, *, now: float
    ) -> list[ResourceTransition]:
        transitions: list[ResourceTransition] = []

        memory_blocked = memory_percent > self.memory_block_percent
        if memory_blocked != self.memory_blocked:
            self.memory_blocked = memory_blocked
            transitions.append(
                ResourceTransition(
                    "memory_block" if memory_blocked else "memory_resume",
                    cpu_percent,
                    memory_percent,
                )
            )

        if not self.cpu_paused:
            self._cpu_low_since = None
            if cpu_percent > self.cpu_pause_percent:
                if self._cpu_high_since is None:
                    self._cpu_high_since = now
                elif now - self._cpu_high_since >= self.cpu_sustain_seconds:
                    self.cpu_paused = True
                    self._cpu_high_since = None
                    transitions.append(
                        ResourceTransition("cpu_pause", cpu_percent, memory_percent)
                    )
            else:
                self._cpu_high_since = None
        else:
            self._cpu_high_since = None
            if cpu_percent < self.cpu_resume_percent:
                if self._cpu_low_since is None:
                    self._cpu_low_since = now
                elif now - self._cpu_low_since >= self.cpu_sustain_seconds:
                    self.cpu_paused = False
                    self._cpu_low_since = None
                    transitions.append(
                        ResourceTransition("cpu_resume", cpu_percent, memory_percent)
                    )
            else:
                self._cpu_low_since = None

        return transitions

# Copyright 2026 importtime-check contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Opt-in profile capture, immutable evidence, and bounded child-output tests."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, cast

import pytest

import importtime_check._profile as profile_module
from importtime_check import (
    ImportMeasurement,
    ImportMeasurementError,
    ImportProfile,
    ImportProfileError,
    ImportTimeEvent,
    ImportTimeParseResult,
    ProfileRun,
    ProfileTarget,
    ReportIdentity,
    SamplingPolicy,
    capture_import_profile,
)


def _identity() -> ReportIdentity:
    return ReportIdentity("cpython", "3.11", "linux", "x86_64")


def _events(module: str = "sample") -> tuple[ImportTimeEvent, ...]:
    return (
        ImportTimeEvent("shared", 2, 3, 1),
        ImportTimeEvent("shared", 4, 5, 1),
        ImportTimeEvent(module, 6, 20, 0),
    )


def _target(module: str = "sample") -> ProfileTarget:
    return ProfileTarget(module, (ProfileRun("sample", 1, _events(module)),))


def _measurement(module: str, interpreter: str) -> ImportMeasurement:
    events = _events(module)
    return ImportMeasurement(
        module,
        interpreter,
        ImportTimeParseResult(events, ("private diagnostic",)),
        events[-1],
    )


def test_capture_preserves_target_run_and_repeated_event_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, str, int, dict[str, str]]] = []
    snapshots: list[dict[str, str]] = []
    monkeypatch.setenv("IMPORTTIME_PROFILE_SNAPSHOT", "original")

    def fake_probe(
        interpreter: str, timeout: float, directory: Path, environment: dict[str, str]
    ) -> ReportIdentity:
        assert interpreter == str(Path(sys.executable).resolve())
        assert timeout == 7
        assert directory == tmp_path.resolve()
        snapshots.append(environment)
        monkeypatch.setenv("IMPORTTIME_PROFILE_SNAPSHOT", "changed")
        return _identity()

    def fake_measure(
        module: str,
        interpreter: str,
        timeout: float,
        directory: Path,
        environment: dict[str, str],
        phase: str,
        number: int,
    ) -> ImportMeasurement:
        assert timeout == 7
        assert directory == tmp_path.resolve()
        assert environment is snapshots[0]
        assert environment["IMPORTTIME_PROFILE_SNAPSHOT"] == "original"
        calls.append((module, phase, number, environment))
        return _measurement(module, interpreter)

    monkeypatch.setattr(profile_module, "_probe_identity", fake_probe)
    monkeypatch.setattr(profile_module, "_profile_measurement", fake_measure)
    result = capture_import_profile(
        ("zeta", "alpha"),
        python_executable=sys.executable,
        timeout_seconds=7,
        working_directory=tmp_path,
        warmups=1,
        samples=2,
    )

    assert list(result.targets) == ["alpha", "zeta"]
    assert [(name, phase, number) for name, phase, number, _ in calls] == [
        (name, phase, number)
        for name in ("alpha", "zeta")
        for phase, count in (("warmup", 1), ("sample", 2))
        for number in range(1, count + 1)
    ]
    assert result.environment == _identity()
    assert result.sampling == SamplingPolicy(1, 2)
    assert result.source_sha256 is None
    assert result.profile_version == 1
    assert [event.module for event in result.targets["alpha"].runs[0].events] == [
        "shared",
        "shared",
        "alpha",
    ]
    assert "private diagnostic" not in str(result)
    with pytest.raises(TypeError):
        result.targets["alpha"] = _target("alpha")  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        result.profile_version = 2  # type: ignore[misc]


@pytest.mark.parametrize(
    ("modules", "warmups", "samples", "message"),
    (
        ("sample", 0, 1, "non-empty sequence"),
        (b"sample", 0, 1, "non-empty sequence"),
        (None, 0, 1, "non-empty sequence"),
        ((), 0, 1, "1 to 16"),
        (("sample",) * 17, 0, 1, "1 to 16"),
        (("sample", "sample"), 0, 1, "distinct"),
        (("bad-name",), 0, 1, "dotted"),
        (("sample",), 6, 1, "sampling counts"),
        (("sample",), 0, 21, "sampling counts"),
        (("a" * 257,), 0, 1, "256 UTF-8"),
        (("sample", "other", "third", "fourth", "fifth", "sixth"), 0, 20, "total run"),
        (("sample",), -1, 1, "warmups"),
        (("sample",), 0, 0, "samples"),
        (("sample",), True, 1, "warmups"),
    ),
    ids=(
        "text-selection",
        "bytes-selection",
        "none-selection",
        "empty-selection",
        "too-many-targets",
        "duplicate-target",
        "invalid-target",
        "too-many-warmups",
        "too-many-samples",
        "long-target",
        "total-run-limit",
        "negative-warmups",
        "zero-samples",
        "boolean-warmups",
    ),
)
def test_invalid_capture_fails_before_probe_or_child(
    monkeypatch: pytest.MonkeyPatch,
    modules: object,
    warmups: int,
    samples: int,
    message: str,
) -> None:
    def unexpected(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("probe or child started before validation")

    monkeypatch.setattr(profile_module, "_probe_identity", unexpected)
    monkeypatch.setattr(profile_module, "_profile_measurement", unexpected)
    with pytest.raises(ValueError, match=message):
        capture_import_profile(cast(Any, modules), warmups=warmups, samples=samples)


def test_capture_validates_runtime_before_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        profile_module,
        "_probe_identity",
        lambda *args: pytest.fail("probe started"),
    )
    with pytest.raises(ValueError, match="absolute path"):
        capture_import_profile(("sample",), python_executable="relative-python")
    with pytest.raises(ValueError, match="timeout_seconds"):
        capture_import_profile(("sample",), timeout_seconds=0)
    with pytest.raises(ValueError, match="working_directory"):
        capture_import_profile(("sample",), working_directory="nonexistent-directory")


def test_later_run_failure_has_index_and_returns_no_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, int]] = []
    monkeypatch.setattr(profile_module, "_probe_identity", lambda *args: _identity())

    def fake_measure(
        module: str,
        interpreter: str,
        timeout: float,
        directory: Path,
        environment: dict[str, str],
        phase: str,
        number: int,
    ) -> ImportMeasurement:
        calls.append((module, phase, number))
        if (module, phase, number) == ("zeta", "sample", 2):
            raise ImportMeasurementError(
                module=module,
                kind="parse",
                python_executable=interpreter,
                reason="invalid import-time output",
            )
        return _measurement(module, interpreter)

    monkeypatch.setattr(profile_module, "_profile_measurement", fake_measure)
    with pytest.raises(ImportMeasurementError) as failure:
        capture_import_profile(("zeta", "alpha"), warmups=0, samples=2)
    assert failure.value.module == "zeta"
    assert failure.value.kind == "parse"
    assert (failure.value.run_phase, failure.value.run_number) == ("sample", 2)
    assert calls == [
        ("alpha", "sample", 1),
        ("alpha", "sample", 2),
        ("zeta", "sample", 1),
        ("zeta", "sample", 2),
    ]


def test_capture_limit_failure_carries_exact_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(profile_module, "_probe_identity", lambda *args: _identity())

    def too_large(
        module: str,
        interpreter: str,
        timeout: float,
        directory: Path,
        environment: dict[str, str],
        phase: str,
        number: int,
    ) -> ImportMeasurement:
        raise ImportProfileError(
            "limit", "too many bytes", module=module, run_phase="sample", run_number=1
        )

    monkeypatch.setattr(profile_module, "_profile_measurement", too_large)
    with pytest.raises(ImportProfileError) as failure:
        capture_import_profile(("sample",), warmups=0, samples=1)
    assert (failure.value.kind, failure.value.module) == ("limit", "sample")
    assert (failure.value.run_phase, failure.value.run_number) == ("sample", 1)


@pytest.mark.parametrize(
    ("limit", "events", "kind"),
    (
        (2, _events(), "limit"),
        (5_000, (ImportTimeEvent("bad-name", 1, 1, 0), _events()[-1]), "invalid"),
    ),
    ids=("too-many-run-events", "unrepresentable-event"),
)
def test_capture_rejects_unrepresentable_complete_run(
    monkeypatch: pytest.MonkeyPatch,
    limit: int,
    events: tuple[ImportTimeEvent, ...],
    kind: str,
) -> None:
    monkeypatch.setattr(profile_module, "_MAX_EVENTS_PER_RUN", limit)
    monkeypatch.setattr(profile_module, "_probe_identity", lambda *args: _identity())

    def fake_measure(
        module: str,
        interpreter: str,
        timeout: float,
        directory: Path,
        environment: dict[str, str],
        phase: str,
        number: int,
    ) -> ImportMeasurement:
        return ImportMeasurement(
            module,
            interpreter,
            ImportTimeParseResult(events, ()),
            events[-1],
        )

    monkeypatch.setattr(profile_module, "_profile_measurement", fake_measure)
    with pytest.raises(ImportProfileError) as failure:
        capture_import_profile(("sample",), warmups=0, samples=1)
    assert failure.value.kind == kind
    assert (
        failure.value.module,
        failure.value.run_phase,
        failure.value.run_number,
    ) == (
        "sample",
        "sample",
        1,
    )


def test_capture_rejects_total_event_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(profile_module, "_MAX_EVENTS_TOTAL", 2)
    monkeypatch.setattr(profile_module, "_probe_identity", lambda *args: _identity())
    monkeypatch.setattr(
        profile_module,
        "_profile_measurement",
        lambda module, interpreter, *args: _measurement(module, interpreter),
    )
    with pytest.raises(ImportProfileError) as failure:
        capture_import_profile(("sample",), warmups=0, samples=1)
    assert failure.value.kind == "limit"


def test_profile_models_copy_values_and_validate_complete_runs() -> None:
    events = list(_events())
    run = ProfileRun("sample", 1, cast(tuple[ImportTimeEvent, ...], events))
    events.clear()
    assert len(run.events) == 3
    runs = [run]
    target = ProfileTarget("sample", cast(tuple[ProfileRun, ...], runs))
    runs.clear()
    assert len(target.runs) == 1
    targets = {"sample": target}
    profile = ImportProfile(_identity(), SamplingPolicy(0, 1), targets)
    targets.clear()
    assert list(profile.targets) == ["sample"]
    with pytest.raises(FrozenInstanceError):
        target.runs = ()  # type: ignore[misc]
    assert (
        ImportProfile(
            _identity(), SamplingPolicy(0, 1), {"sample": _target()}, "a" * 64
        ).source_sha256
        == "a" * 64
    )


def test_profile_model_total_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    modules = ("alpha", "beta", "gamma", "delta", "epsilon", "zeta")
    targets = {
        module: ProfileTarget(
            module,
            tuple(
                ProfileRun("sample", number, _events(module)) for number in range(1, 21)
            ),
        )
        for module in modules
    }
    with pytest.raises(ValueError, match="total run count"):
        ImportProfile(_identity(), SamplingPolicy(0, 20), targets)

    monkeypatch.setattr(profile_module, "_MAX_EVENTS_TOTAL", 2)
    with pytest.raises(ValueError, match="total event count"):
        ImportProfile(_identity(), SamplingPolicy(0, 1), {"sample": _target()})


@pytest.mark.parametrize(
    ("phase", "number", "events", "message"),
    (
        ("other", 1, _events(), "phase"),
        ("sample", 0, _events(), "run number"),
        ("sample", True, _events(), "run number"),
        ("sample", 1, None, "events must"),
        ("sample", 1, (), "event count"),
        ("sample", 1, ("not an event",), "ImportTimeEvent"),
        ("sample", 1, (ImportTimeEvent("bad-name", 1, 1, 0),), "dotted"),
        ("sample", 1, (ImportTimeEvent("a" * 257, 1, 1, 0),), "256 UTF-8"),
        ("sample", 1, (ImportTimeEvent("a", 1, 2**63, 0),), "supported range"),
        ("sample", 1, (ImportTimeEvent("a", 1, 1, 5_001),), "supported range"),
    ),
    ids=(
        "phase",
        "zero-number",
        "boolean-number",
        "none-events",
        "empty-events",
        "wrong-event-type",
        "invalid-module",
        "long-module",
        "large-time",
        "large-depth",
    ),
)
def test_profile_run_rejects_invalid_values(
    phase: object, number: object, events: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        ProfileRun(cast(Any, phase), cast(Any, number), cast(Any, events))


@pytest.mark.parametrize(
    ("module", "runs", "message"),
    (
        ("bad-name", (_target().runs[0],), "dotted"),
        ("sample", None, "runs must"),
        ("sample", (), "run count"),
        ("sample", ("not a run",), "ProfileRun"),
        ("other", (_target().runs[0],), "target event"),
        (
            "sample",
            (
                ProfileRun(
                    "sample", 1, (*_events(), ImportTimeEvent("sample", 1, 1, 0))
                ),
            ),
            "target event",
        ),
    ),
    ids=(
        "invalid-module",
        "none-runs",
        "empty-runs",
        "wrong-run-type",
        "missing-target",
        "duplicate-target",
    ),
)
def test_profile_target_rejects_invalid_values(
    module: object, runs: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        ProfileTarget(cast(Any, module), cast(Any, runs))


@pytest.mark.parametrize(
    ("environment", "sampling", "targets", "source", "version", "message"),
    (
        (None, SamplingPolicy(0, 1), {"sample": _target()}, None, 1, "environment"),
        (_identity(), None, {"sample": _target()}, None, 1, "sampling"),
        (
            _identity(),
            SamplingPolicy(6, 1),
            {"sample": _target()},
            None,
            1,
            "sampling counts",
        ),
        (_identity(), SamplingPolicy(0, 1), {}, None, 1, "targets"),
        (_identity(), SamplingPolicy(0, 1), None, None, 1, "targets"),
        (
            _identity(),
            SamplingPolicy(0, 1),
            {"other": _target()},
            None,
            1,
            "must match",
        ),
        (_identity(), SamplingPolicy(0, 1), {"bad-name": _target()}, None, 1, "dotted"),
        (_identity(), SamplingPolicy(1, 1), {"sample": _target()}, None, 1, "complete"),
        (_identity(), SamplingPolicy(0, 2), {"sample": _target()}, None, 1, "complete"),
        (_identity(), SamplingPolicy(0, 1), {"sample": _target()}, "BAD", 1, "SHA-256"),
        (
            _identity(),
            SamplingPolicy(0, 1),
            {"sample": _target()},
            None,
            2,
            "profile_version",
        ),
        (
            _identity(),
            SamplingPolicy(0, 1),
            {"sample": _target()},
            None,
            True,
            "profile_version",
        ),
    ),
    ids=(
        "environment",
        "sampling",
        "sampling-limit",
        "empty-targets",
        "none-targets",
        "target-mismatch",
        "invalid-target",
        "missing-warmup",
        "missing-sample",
        "bad-digest",
        "future-version",
        "boolean-version",
    ),
)
def test_import_profile_rejects_invalid_values(
    environment: object,
    sampling: object,
    targets: object,
    source: object,
    version: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ImportProfile(
            cast(Any, environment),
            cast(Any, sampling),
            cast(Any, targets),
            cast(Any, source),
            cast(Any, version),
        )


def test_probe_uses_same_environment_and_safe_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    def fake_run(
        command: list[str], **options: Any
    ) -> subprocess.CompletedProcess[str]:
        observed.update(options)
        assert command[1:3] == ["-I", "-c"]
        assert "__import__" not in command[3]
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(
                {
                    "implementation": "cpython",
                    "python": "3.11",
                    "platform": "linux",
                    "machine": "X86_64",
                }
            ),
            "private stderr",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    environment = {"IMPORTTIME_PROFILE_SNAPSHOT": "value"}
    identity = profile_module._probe_identity("python", 5.0, Path.cwd(), environment)
    assert identity == _identity()
    assert observed["env"] is environment
    assert observed["stdin"] == subprocess.DEVNULL
    assert observed["capture_output"] is True
    assert observed["shell"] is False
    assert observed["timeout"] == 5.0


@pytest.mark.parametrize(
    ("outcome", "kind"),
    (
        (OSError("private path"), "probe"),
        (subprocess.TimeoutExpired("python", 1), "probe"),
        (subprocess.CompletedProcess([], 1, "", "private stderr"), "probe"),
        (subprocess.CompletedProcess([], 0, "not json", ""), "probe"),
        (subprocess.CompletedProcess([], 0, "[]", ""), "probe"),
        (subprocess.CompletedProcess([], 0, '{"python":"3.11"}', ""), "probe"),
        (
            subprocess.CompletedProcess(
                [],
                0,
                '{"implementation":"pypy","python":"3.11",'
                '"platform":"linux","machine":"x86_64"}',
                "",
            ),
            "probe",
        ),
    ),
    ids=(
        "launch-error",
        "timeout",
        "exit",
        "invalid-json",
        "array-json",
        "missing-fields",
        "wrong-interpreter",
    ),
)
def test_probe_fails_closed_without_echoing_output(
    monkeypatch: pytest.MonkeyPatch, outcome: object, kind: str
) -> None:
    def fake_run(*args: Any, **kwargs: Any) -> Any:
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ImportProfileError) as failure:
        profile_module._probe_identity("python", 1, Path.cwd(), {})
    assert failure.value.kind == kind
    assert "private" not in str(failure.value)


def test_bounded_child_real_process_and_public_api(tmp_path: Path) -> None:
    profile = capture_import_profile(
        ("json", "email"),
        python_executable=sys.executable,
        working_directory=tmp_path,
        warmups=0,
        samples=1,
    )
    assert list(profile.targets) == ["email", "json"]
    assert profile.environment.implementation == "cpython"
    assert profile.sampling == SamplingPolicy(0, 1)
    for module, target in profile.targets.items():
        assert len(target.runs) == 1
        assert (target.runs[0].phase, target.runs[0].number) == ("sample", 1)
        assert len(target.runs[0].events) > 1
        assert sum(event.module == module for event in target.runs[0].events) == 1


def test_bounded_child_fails_without_truncating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(profile_module, "_MAX_STDERR_BYTES", 1)
    with pytest.raises(ImportProfileError) as failure:
        capture_import_profile(("json",), warmups=0, samples=1)
    assert failure.value.kind == "limit"
    assert (
        failure.value.module,
        failure.value.run_phase,
        failure.value.run_number,
    ) == (
        "json",
        "sample",
        1,
    )


class _FakePipe:
    def __init__(self, chunks: list[bytes] | None = None, error: bool = False) -> None:
        self.chunks = chunks or []
        self.error = error
        self.closed = False

    def read1(self, size: int) -> bytes:
        assert size == 65536
        if self.error:
            raise OSError("read failed")
        return self.chunks.pop(0) if self.chunks else b""

    def close(self) -> None:
        self.closed = True


class _FakeProcess:
    def __init__(
        self,
        pipe: _FakePipe | None,
        *,
        wait_error: BaseException | None = None,
        kill_error: bool = False,
    ) -> None:
        self.stderr = pipe
        self.wait_error = wait_error
        self.kill_error = kill_error
        self.killed = False
        self.waited = False

    def poll(self) -> int | None:
        return -9 if self.killed else None

    def kill(self) -> None:
        self.killed = True
        if self.kill_error:
            raise OSError("already exited")

    def wait(self, timeout: float | None = None) -> int:
        self.waited = True
        if self.wait_error is not None:
            error = self.wait_error
            self.wait_error = None
            raise error
        return -9 if self.killed else 0


def _bounded_call() -> tuple[str, int]:
    return profile_module._bounded_stderr(
        "sample", "python", 1.0, Path.cwd(), {}, "sample", 1
    )


def test_bounded_child_argv_utf8_and_pipe_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipe = _FakePipe([b"first\n", b"\xff"])
    process = _FakeProcess(pipe)
    observed: dict[str, Any] = {}

    def fake_popen(args: list[str], **options: Any) -> _FakeProcess:
        observed["args"] = args
        observed.update(options)
        return process

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    assert _bounded_call() == ("first\n\ufffd", 0)
    assert observed["args"][:5] == ["python", "-I", "-X", "importtime", "-c"]
    assert observed["args"][-1] == "sample"
    assert observed["env"] == {}
    assert observed["cwd"] == Path.cwd()
    assert observed["stdin"] == subprocess.DEVNULL
    assert observed["stdout"] == subprocess.DEVNULL
    assert observed["stderr"] == subprocess.PIPE
    assert observed["shell"] is False
    assert pipe.closed


def test_bounded_child_launch_and_read_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def denied(*args: Any, **kwargs: Any) -> None:
        raise OSError("launch denied")

    monkeypatch.setattr(subprocess, "Popen", denied)
    with pytest.raises(ImportMeasurementError) as launch:
        _bounded_call()
    assert launch.value.kind == "launch"

    process = _FakeProcess(_FakePipe(error=True))
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    with pytest.raises(ImportProfileError) as failed_read:
        _bounded_call()
    assert failed_read.value.kind == "io"
    assert process.killed and process.waited


def test_bounded_child_missing_pipe_and_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeProcess(None)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    with pytest.raises(ImportProfileError, match="complete child stderr"):
        _bounded_call()

    monkeypatch.setattr(profile_module, "_MAX_STDERR_BYTES", 2)
    process = _FakeProcess(_FakePipe([b"abc"]))
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    with pytest.raises(ImportProfileError) as exceeded:
        _bounded_call()
    assert exceeded.value.kind == "limit"
    assert process.killed


def test_bounded_child_handles_exited_process_before_reader_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeProcess(_FakePipe(error=True))
    process.poll = lambda: 0  # type: ignore[method-assign]
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    with pytest.raises(ImportProfileError) as failed_read:
        _bounded_call()
    assert failed_read.value.kind == "io"
    assert not process.killed

    monkeypatch.setattr(profile_module, "_MAX_STDERR_BYTES", 2)
    process = _FakeProcess(_FakePipe([b"abc"]))
    process.poll = lambda: 0  # type: ignore[method-assign]
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    with pytest.raises(ImportProfileError) as overflow:
        _bounded_call()
    assert overflow.value.kind == "limit"
    assert not process.killed


def test_bounded_child_timeout_and_interrupt_reap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeProcess(
        _FakePipe(), wait_error=subprocess.TimeoutExpired("python", 1)
    )
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    with pytest.raises(ImportMeasurementError) as timed_out:
        _bounded_call()
    assert timed_out.value.kind == "timeout"
    assert process.killed and process.waited

    process = _FakeProcess(_FakePipe(), wait_error=KeyboardInterrupt())
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    with pytest.raises(KeyboardInterrupt):
        _bounded_call()
    assert process.killed and process.waited


def test_kill_and_reap_tolerates_already_exited_child() -> None:
    process = _FakeProcess(_FakePipe(), kill_error=True)
    profile_module._kill_and_reap(cast(Any, process))
    assert process.waited

    process = _FakeProcess(_FakePipe())
    process.poll = lambda: 0  # type: ignore[method-assign]
    profile_module._kill_and_reap(cast(Any, process))
    assert process.waited and not process.killed


def test_bounded_child_times_out_when_pipe_never_reaches_eof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    released = threading.Event()

    class BlockingPipe(_FakePipe):
        def read1(self, size: int) -> bytes:
            released.wait(timeout=2)
            return b""

    class BlockingProcess(_FakeProcess):
        def kill(self) -> None:
            super().kill()
            released.set()

    process = BlockingProcess(BlockingPipe())
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    with pytest.raises(ImportMeasurementError) as failure:
        profile_module._bounded_stderr(
            "sample", "python", 0.001, Path.cwd(), {}, "sample", 1
        )
    assert failure.value.kind == "timeout"
    assert process.killed and released.is_set()


def test_profile_measurement_reuses_published_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        profile_module,
        "_bounded_stderr",
        lambda *args: (
            "import time: 1 | 2 | dependency\nimport time: 3 | 7 | sample",
            0,
        ),
    )
    measured = profile_module._profile_measurement(
        "sample", sys.executable, 1, Path.cwd(), {}, "sample", 1
    )
    assert measured.target_event == ImportTimeEvent("sample", 3, 7, 0)
    assert len(measured.parsed.events) == 2

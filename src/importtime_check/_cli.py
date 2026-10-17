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

"""Standard-library command-line workflows for import-time measurements."""

from __future__ import annotations

import argparse
import os
import re
import stat
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from ._baseline import (
    BaselineError,
    SamplingPolicy,
    TargetAllowance,
    _nonnegative_int,
    _percent,
    decode_baseline,
    encode_baseline,
    load_baseline,
    save_baseline,
)
from ._cohort import summarize_measurement_reports
from ._measurement import (
    ImportMeasurementError,
    _interpreter_path,
    _timeout,
    _validate_module_name,
    _working_directory,
)
from ._measurement_report import (
    MeasurementReport,
    MeasurementReportError,
    load_measurement_report,
)
from ._regression import (
    _require_same_environment,
    check_baseline,
    probe_environment,
    record_baseline,
    refresh_baseline,
)
from ._report import (
    cohort_summary_json,
    cohort_summary_text,
    error_json,
    measurement_json,
    measurement_text,
    report_json,
    report_text,
)
from ._sampling import sample_import, sample_imports

_BUDGET_US = re.compile(r"(?:0|[1-9][0-9]*)\Z")


def _add_runtime(parser: argparse.ArgumentParser, *, profile: bool = False) -> None:
    parser.add_argument("--python", dest="python_executable")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--working-directory")
    if profile:
        parser.add_argument("--profile", default="default")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="importtime-check",
        description="Measure CPython imports and check reviewable baselines.",
    )
    parser.add_argument(
        "--debug", action="store_true", help="show tracebacks for errors"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    measure = commands.add_parser("measure", help="sample installed modules")
    measure.add_argument("--module", action="append", required=True)
    measure.add_argument("--warmups", type=int, default=1)
    measure.add_argument("--samples", type=int, default=5)
    measure.add_argument("--format", choices=("text", "json"), default="text")
    _add_runtime(measure)

    report = commands.add_parser("report", help="analyze saved measurement reports")
    report_commands = report.add_subparsers(dest="report_command", required=True)
    summarize = report_commands.add_parser(
        "summarize", help="summarize a comparable report cohort"
    )
    summarize.add_argument("--file", action="append", required=True)
    summarize.add_argument("--runner-context", required=True)
    summarize.add_argument("--install-context", required=True)
    summarize.add_argument("--format", choices=("text", "json"), default="text")

    baseline = commands.add_parser(
        "baseline", help="record, refresh, or inspect a baseline"
    )
    baseline_commands = baseline.add_subparsers(dest="baseline_command", required=True)
    record = baseline_commands.add_parser("record", help="record a baseline file")
    record.add_argument("--output", required=True)
    record.add_argument("--module", action="append", required=True)
    record.add_argument("--max-increase-us", type=int)
    record.add_argument("--max-increase-percent")
    record.add_argument(
        "--budget",
        action="append",
        metavar="MODULE=US,PERCENT",
        help="repeat once per --module; cannot mix with common allowance options",
    )
    record.add_argument("--warmups", type=int, default=1)
    record.add_argument("--samples", type=int, default=5)
    record.add_argument("--replace", action="store_true")
    _add_runtime(record, profile=True)
    show = baseline_commands.add_parser("show", help="inspect a baseline file")
    show.add_argument("--file", required=True)
    show.add_argument("--format", choices=("text", "json"), default="text")
    refresh = baseline_commands.add_parser(
        "refresh", help="update timings without resetting baseline policy"
    )
    refresh.add_argument("--file", required=True)
    refresh.add_argument("--replace", action="store_true")
    _add_runtime(refresh, profile=True)

    check = commands.add_parser("check", help="compare current imports to a baseline")
    check.add_argument("--baseline", required=True)
    check.add_argument("--module", action="append")
    check.add_argument("--format", choices=("text", "json"), default="text")
    _add_runtime(check, profile=True)
    return parser


def _runtime(arguments: argparse.Namespace) -> tuple[str, float, Path]:
    return (
        _interpreter_path(arguments.python_executable),
        _timeout(arguments.timeout_seconds),
        _working_directory(arguments.working_directory),
    )


def _modules(values: Sequence[str]) -> tuple[str, ...]:
    for module in values:
        _validate_module_name(module)
    if len(values) != len(set(values)):
        repeated = sorted({module for module in values if values.count(module) > 1})
        raise ValueError(f"module names must not repeat: {', '.join(repeated)}")
    return tuple(sorted(values))


def _profile(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("profile must be non-blank")
    return value


def _record_allowances(
    arguments: argparse.Namespace, modules: tuple[str, ...]
) -> tuple[TargetAllowance | None, dict[str, TargetAllowance] | None]:
    entries: list[str] | None = arguments.budget
    if entries is None:
        if arguments.max_increase_us is None or arguments.max_increase_percent is None:
            raise ValueError(
                "supply both --max-increase-us and --max-increase-percent, "
                "or one --budget per module"
            )
        return (
            TargetAllowance(
                _nonnegative_int(arguments.max_increase_us, "max_increase_us"),
                _percent(arguments.max_increase_percent),
            ),
            None,
        )
    if (
        arguments.max_increase_us is not None
        or arguments.max_increase_percent is not None
    ):
        raise ValueError("--budget cannot be mixed with common allowance options")
    allowances: dict[str, TargetAllowance] = {}
    for entry in entries:
        if entry.count("=") != 1 or entry.count(",") != 1:
            raise ValueError(f"invalid --budget entry: {entry!r}")
        module, amounts = entry.split("=", 1)
        absolute, percent = amounts.split(",", 1)
        try:
            _validate_module_name(module)
            if _BUDGET_US.fullmatch(absolute) is None:
                raise ValueError("US must be plain non-negative decimal digits")
            allowance = TargetAllowance(int(absolute), percent)
        except ValueError as error:
            raise ValueError(f"invalid --budget entry {entry!r}: {error}") from error
        if module in allowances:
            raise ValueError(f"duplicate --budget for module {module!r}")
        allowances[module] = allowance
    missing = sorted(set(modules) - allowances.keys())
    unknown = sorted(allowances.keys() - set(modules))
    if missing or unknown:
        raise ValueError(
            "--budget target set differs: "
            f"missing: {', '.join(missing) or 'none'}; "
            f"unknown: {', '.join(unknown) or 'none'}"
        )
    return None, allowances


def _measure(arguments: argparse.Namespace) -> int:
    modules = _modules(arguments.module)
    policy = SamplingPolicy(arguments.warmups, arguments.samples)
    interpreter, timeout, directory = _runtime(arguments)
    environment = (
        probe_environment(
            python_executable=interpreter,
            timeout_seconds=timeout,
            working_directory=directory,
        )
        if arguments.format == "json"
        else None
    )
    observations = sample_imports(
        modules,
        python_executable=interpreter,
        timeout_seconds=timeout,
        working_directory=directory,
        warmups=policy.warmups,
        samples=policy.samples,
    )
    sys.stdout.write(
        measurement_json(observations, environment, policy)
        if environment is not None
        else measurement_text(observations)
    )
    return 0


def _record(arguments: argparse.Namespace) -> int:
    modules = _modules(arguments.module)
    policy = SamplingPolicy(arguments.warmups, arguments.samples)
    common_allowance, per_target_allowances = _record_allowances(arguments, modules)
    profile = _profile(arguments.profile)
    interpreter, timeout, directory = _runtime(arguments)
    output = Path(arguments.output)
    if output.exists() and not arguments.replace:
        raise ValueError(f"baseline already exists: {output}; use --replace")
    if not output.parent.is_dir():
        raise ValueError(f"baseline parent directory does not exist: {output.parent}")
    environment = probe_environment(
        python_executable=interpreter,
        timeout_seconds=timeout,
        working_directory=directory,
        profile=profile,
    )
    observations = {
        module: sample_import(
            module,
            python_executable=interpreter,
            timeout_seconds=timeout,
            working_directory=directory,
            warmups=policy.warmups,
            samples=policy.samples,
        )
        for module in modules
    }
    if per_target_allowances is None:
        assert common_allowance is not None
        baseline = record_baseline(
            observations,
            environment,
            max_increase_us=common_allowance.max_increase_us,
            max_increase_percent=common_allowance.max_increase_percent,
        )
    else:
        baseline = record_baseline(
            observations, environment, per_target_allowances=per_target_allowances
        )
    save_baseline(output, baseline, replace=arguments.replace)
    print(f"Recorded {len(modules)} target(s) in {output}")
    if per_target_allowances is not None:
        for module in modules:
            allowance = baseline.targets[module]
            print(
                f"{module}: allowances {allowance.max_increase_us} us or "
                f"{allowance.max_increase_percent}%"
            )
        print("Review the baseline file diff before accepting these budgets.")
    return 0


def _show(arguments: argparse.Namespace) -> int:
    baseline = load_baseline(arguments.file)
    if arguments.format == "json":
        sys.stdout.write(encode_baseline(baseline).decode("utf-8"))
    else:
        identity = baseline.environment
        print(
            f"Baseline schema {baseline.schema_version}: {identity.implementation} "
            f"{identity.python}, {identity.platform}/{identity.machine}, "
            f"profile {identity.profile}"
        )
        print(
            f"Sampling: {baseline.sampling.warmups} warmup(s), "
            f"{baseline.sampling.samples} recorded sample(s), "
            f"{baseline.sampling.statistic}"
        )
        for module, target in baseline.targets.items():
            print(
                f"{module}: {target.baseline_cumulative_us} us; "
                f"allowances {target.max_increase_us} us or "
                f"{target.max_increase_percent}%"
            )
    return 0


def _read_refresh_bytes(path: Path, *, initial: bool) -> bytes:
    """Read only an existing regular file, detecting a changed destination."""
    changed = "baseline changed during refresh"
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            raise BaselineError(
                "io-error",
                "baseline must be a regular non-symlink file" if initial else changed,
            )
        return path.read_bytes()
    except FileNotFoundError as error:
        if initial:
            raise BaselineError(
                "baseline-missing", "baseline file not found"
            ) from error
        raise BaselineError("io-error", changed) from error
    except OSError as error:
        reason = "cannot read baseline" if initial else changed
        raise BaselineError("io-error", reason) from error


def _commit_refresh(path: Path, original: bytes, updated: bytes) -> None:
    """Commit complete bytes only if the original file is still present."""
    try:
        with tempfile.TemporaryDirectory(
            prefix=".importtime-check-", dir=path.parent, ignore_cleanup_errors=True
        ) as directory:
            temporary = Path(directory) / "baseline.json"
            with temporary.open("wb") as stream:
                stream.write(updated)
                stream.flush()
                os.fsync(stream.fileno())
            if _read_refresh_bytes(path, initial=False) != original:
                raise BaselineError("io-error", "baseline changed during refresh")
            os.replace(temporary, path)
    except OSError as error:
        raise BaselineError("io-error", "cannot write baseline") from error


def _refresh(arguments: argparse.Namespace) -> int:
    if not arguments.replace:
        raise ValueError("baseline refresh requires --replace")
    profile = _profile(arguments.profile)
    interpreter, timeout, directory = _runtime(arguments)
    path = Path(arguments.file)
    original = _read_refresh_bytes(path, initial=True)
    baseline = decode_baseline(original)
    environment = probe_environment(
        python_executable=interpreter,
        timeout_seconds=timeout,
        working_directory=directory,
        profile=profile,
    )
    _require_same_environment(baseline, environment)
    observations = {
        module: sample_import(
            module,
            python_executable=interpreter,
            timeout_seconds=timeout,
            working_directory=directory,
            warmups=baseline.sampling.warmups,
            samples=baseline.sampling.samples,
        )
        for module in baseline.targets
    }
    updated = refresh_baseline(baseline, observations, environment)
    _commit_refresh(path, original, encode_baseline(updated))
    for module in baseline.targets:
        before = baseline.targets[module].baseline_cumulative_us
        after = updated.targets[module].baseline_cumulative_us
        print(f"{module}: {before} -> {after} us ({after - before:+d} us)")
    print("Target names, sampling, identity, and allowances retained; review the file.")
    return 0


def _check(arguments: argparse.Namespace) -> int:
    modules = _modules(arguments.module) if arguments.module is not None else None
    profile = _profile(arguments.profile)
    interpreter, timeout, directory = _runtime(arguments)
    baseline = load_baseline(arguments.baseline)
    result = check_baseline(
        baseline,
        python_executable=interpreter,
        timeout_seconds=timeout,
        working_directory=directory,
        profile=profile,
        modules=modules,
    )
    sys.stdout.write(
        report_json(result) if arguments.format == "json" else report_text(result)
    )
    return 1 if result.status == "regression" else 0


def _summarize(arguments: argparse.Namespace) -> int:
    if not 2 <= len(arguments.file) <= 64:
        raise MeasurementReportError(
            "cohort-invalid", "cohort must contain 2 to 64 reports"
        )
    reports: list[MeasurementReport] = []
    for index, path in enumerate(arguments.file, start=1):
        try:
            reports.append(load_measurement_report(path))
        except MeasurementReportError as error:
            raise MeasurementReportError(
                error.kind, error.reason, source_index=index
            ) from error
    summary = summarize_measurement_reports(
        reports,
        runner_context=arguments.runner_context,
        install_context=arguments.install_context,
    )
    sys.stdout.write(
        cohort_summary_json(summary)
        if arguments.format == "json"
        else cohort_summary_text(summary)
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run one CLI workflow and return its stable process exit code."""
    parser = _parser()
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "measure":
            return _measure(arguments)
        if arguments.command == "report":
            return _summarize(arguments)
        if arguments.command == "baseline":
            if arguments.baseline_command == "record":
                return _record(arguments)
            if arguments.baseline_command == "show":
                return _show(arguments)
            return _refresh(arguments)
        return _check(arguments)
    except MeasurementReportError as error:
        if arguments.debug:
            raise
        location = (
            f" at report #{error.source_index}"
            if error.source_index is not None
            else ""
        )
        fields = (
            f" ({', '.join(error.differing_fields)})" if error.differing_fields else ""
        )
        print(f"importtime-check: {error.kind}{location}{fields}", file=sys.stderr)
        return 2
    except (BaselineError, ImportMeasurementError) as error:
        if arguments.debug:
            raise
        if arguments.command == "check" and arguments.format == "json":
            sys.stdout.write(error_json(error))
        elif arguments.command == "measure" and isinstance(error, BaselineError):
            print(
                "importtime-check: selected interpreter could not be probed",
                file=sys.stderr,
            )
        elif arguments.command == "measure" and isinstance(
            error, ImportMeasurementError
        ):
            run = (
                f" ({error.run_phase} {error.run_number})"
                if error.run_phase is not None and error.run_number is not None
                else ""
            )
            reason = "" if error.kind == "launch" else f": {error.reason}"
            print(
                f"importtime-check: {error.kind} while measuring "
                f"{error.module!r}{run}{reason}",
                file=sys.stderr,
            )
        else:
            print(f"importtime-check: {error}", file=sys.stderr)
        return 2
    except ValueError as error:
        if arguments.debug:
            raise
        parser.error(str(error))

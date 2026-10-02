## Summary

<!-- Explain the user or maintainer problem and the chosen solution. -->

## Related issue

Closes #

## Validation

<!-- List exact commands and relevant manual checks. -->

- [ ] `python -m ruff format --check .`
- [ ] `python -m ruff check .`
- [ ] `python -m mypy src tests tools`
- [ ] `python -m pytest`
- [ ] Packaging checks, when packaging or artifact behavior changes

## Compatibility and risk

<!-- Describe API, format, Python, platform, security, or migration impact. -->

- [ ] Tests cover the changed behavior and failure paths.
- [ ] Public behavior and documentation agree.
- [ ] No runtime dependency or compatibility promise changed unintentionally.
- [ ] Commits include DCO sign-off (`Signed-off-by`).

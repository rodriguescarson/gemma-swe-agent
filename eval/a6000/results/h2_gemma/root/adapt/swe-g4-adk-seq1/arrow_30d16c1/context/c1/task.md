Repository: arrow-py/arrow

Problem statement:
Deprecate Python 2.7 and Python 3.5

# Python 2.7 & 3.5 Deprecation Checklist

- [x] Update `setup.py` classifiers and `python_requires` to declare arrow only supports Python 3.6+
- [x] Drop Python < 3.6 from CI
- [x] Remove Python < 3.6 from Makefile
- [x] Run `pyupgrade --py36-plus`
- [x] Convert all formatting to f-strings (should be done by pyupgrade)
- [x] Remove all future imports
- [x] Remove any remaining python 2 import shadowing
- [x] Audit and overhaul requirements file
- [x] Change timestamp formatting to use `datetime.timestamp()`
- [x] Update timestamp calls in formatter.py
- [x] Replace hardcoded `MAX_TIMESTAMP` constant with `datetime.max.timestamp()`
- [x] Convert `isinstance(value, numbers.Integral)` to `isinstance(value, int)`
- [x] Remove `isstr` function
- [x] Remove `__cmp__()` method in [arrow.py](https://github.com/arrow-py/arrow/blob/2cfb2b0f010ba60d3d9894f8ba5187b909fa97e8/arrow/arrow.py#L1217-L1222)
- [x] Remove coverage pragmas and skipped tests for py27
- [x] Revisit `enfold` calls in code @systemcatch 

# Breaking changes for v1.0.0

- [x] Change timestamp from property to method in `arrow.py` (requires deprecation warning beforehand)
- [x] Change the return value of Arrow's timestamp method (currently a property) to a float

# General Changes for v1.0.0

- [x] Remove beta label from `setup.py`

Closes: https://github.com/arrow-py/arrow/issues/465
Closes: https://github.com/arrow-py/arrow/issues/861
Closes: https://github.com/arrow-py/arrow/issues/739
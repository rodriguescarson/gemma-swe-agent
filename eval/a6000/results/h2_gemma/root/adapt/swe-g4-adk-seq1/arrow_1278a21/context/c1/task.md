Repository: arrow-py/arrow

Problem statement:
Audit errors and clean up utils

## Pull Request Checklist

Thank you for taking the time to improve Arrow! Before submitting your pull request, please check all *appropriate* boxes:

<!-- Check boxes by placing an x in the brackets like this: [x] -->
- [x] 🧪  Added **tests** for changed code.
- [x] 🛠️  All tests **pass** when run locally (run `tox` or `make test` to find out!).
- [x] 🧹  All linting checks **pass** when run locally (run `tox -e lint` or `make lint` to find out!).
- [ ] 📚  Updated **documentation** for changed code.
- [x] ⏩  Code is **up-to-date** with the `master` branch.

If you have *any* questions about your code changes or any of the points above, please submit your questions along with the pull request and we will try our best to help!

## Description of Changes
* Removed useless `total_seconds` function `utils.py`
* Change AttributeErrors to ValueErrors where appropriate. Many of our uses of `AttributeError` do not conform to Python's official [definition of an AttributeError](https://docs.python.org/3/library/exceptions.html). All of these errors are better suited for ValueErrors.
* Change a bunch of missed `format()` strings to f-strings
Repository: arrow-py/arrow

Problem statement:
Add support for week for the Slovak locale and complete the tests


## Pull Request Checklist

Thank you for taking the time to improve Arrow! Before submitting your pull request, please check all *appropriate* boxes:

<!-- Check boxes by placing an x in the brackets: [x] -->
- [x] 🧪 Added **tests** for changed code.
- [x] 🛠️ All tests **pass** when run locally (run `tox` or `make test` to find out!).
- [x] 🧹 All linting checks **pass** when run locally (run `tox -e lint` or `make lint` to find out!).
- [x] 📚 Updated **documentation** for changed code.
- [x] ⏩ Code is **up-to-date** with the `master` branch.

If you have *any* questions about your code changes or any of the points above, please submit your questions along with the pull request and we will try our best to help!

## Description of Changes

Add support for week for the Slovak locale, fix a translation error (“druhý” in Slovak means “second” like “the one after the first one”, not a short time unit; as well as “pár” means “a couple” and not a specific number) and complete the tests to cover all time units and all cases of a Slavic language.
Repository: arrow-py/arrow

Problem statement:
Fix multiple bugs in arrow.get() tzinfo kwarg handling

## Pull Request Checklist

Thank you for taking the time to improve Arrow! Before submitting your pull request, please check all *appropriate* boxes:

<!-- Check boxes by placing an x in the brackets like this: [x] -->
- [x] 🧪  Added **tests** for changed code.
- [ ] 🛠️  All tests **pass** when run locally (run `tox` or `make test` to find out!).
- [ ] 🧹  All linting checks **pass** when run locally (run `tox -e lint` or `make lint` to find out!).
- [x] 📚  Updated **documentation** for changed code.
- [x] ⏩  Code is **up-to-date** with the `master` branch.

If you have *any* questions about your code changes or any of the points above, please submit your questions along with the pull request and we will try our best to help!

## Description of Changes

The `tzinfo` kwarg should now be handled correctly rather than being dropped.

fixes #944 
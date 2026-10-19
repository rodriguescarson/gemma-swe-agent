Repository: arrow-py/arrow

Problem statement:
Add FORMAT_RFC3339_STRICT.

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

Adds a FORMAT variable for a more strict RFC3339 where the RFC called for a space for readability and is used by FORMAT_RFC3339, FORMAT_RFC3339_STRICT uses the T separator to adhere with ISO8601 spec.

[RFC Link](https://www.rfc-editor.org/rfc/rfc3339#section-5.6)
```
      NOTE: ISO 8601 defines date and time separated by "T".
      Applications using this syntax may choose, for the sake of
      readability, to specify a full-date and full-time separated by
      (say) a space character.
```

Closes #1138
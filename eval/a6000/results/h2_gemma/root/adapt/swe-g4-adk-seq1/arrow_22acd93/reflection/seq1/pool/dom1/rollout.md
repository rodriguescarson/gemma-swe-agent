[THINKING] The user wants to create built-in format strings for common formats in the `arrow` library.
Looking at the problem statement, it's a bit vague ("Create built-in format strings for common formats"), but it refers to #770 and #762.
Common formats for date/time might be ISO 8601, RFC 2822, etc.
Wait, Arrow already has some of these. Maybe they want a way to refer to them by name in the `.format()` method.

Let's see what's in `arrow/formatter.py` and `arrow/arrow.py`.

First, I'll explore the codebase to see how formatting is currently handled.
[ASSISTANT] // Thinking: I want to see how formatting is implemented in `arrow/formatter.py` and how it's called from `arrow/arrow.py`.
[ACTION] run_command({"command": "grep -n \"format\" arrow/arrow.py | head -n 20"})
[OBSERVATION] 19:from arrow import formatter, locales, parser, util
57:    _ATTRS_PLURAL = ["{}s".format(a) for a in _ATTRS]
158:                "The provided timestamp '{}' is invalid.".format(timestamp)
184:                "The provided timestamp '{}' is invalid.".format(timestamp)
251:        """ Constructs an :class:`Arrow <arrow.arrow.Arrow>` object from a date string and format,
255:        :param fmt: the format string.
466:        return "<{} [{}]>".format(self.__class__.__name__, self.__str__())
469:        return self._datetime.isoformat()
471:    def __format__(self, formatstr):
473:        if len(formatstr) > 0:
474:            return self.format(formatstr)
620:                raise AttributeError("setting absolute {} is not supported".format(key))
622:                raise AttributeError('unknown attribute: "{}"'.format(key))
673:                    "Invalid shift time frame. Please select one of the following: {}.".format(
840:    # string output and formatting.
842:    def format(self, fmt="YYYY-MM-DD HH:mm:ssZZ", locale="en_us"):
844:        formatted according to a format string.
846:        :param fmt: the format string.
850:            >>> arrow.utcnow().format('YYYY-MM-DD HH:mm:ss ZZ')
853:            >>> arrow.utcnow().format('X')

[ACTION] read_file({"filepath": "arrow/arrow.py", "start_line": 842, "end_line": 860})
[OBSERVATION]     def format(self, fmt="YYYY-MM-DD HH:mm:ssZZ", locale="en_us"):
        """ Returns a string representation of the :class:`Arrow <arrow.arrow.Arrow>` object,
        formatted according to a format string.

        :param fmt: the format string.

        Usage::

            >>> arrow.utcnow().format('YYYY-MM-DD HH:mm:ss ZZ')
            '2013-05-09 03:56:47 -00:00'

            >>> arrow.utcnow().format('X')
            '1368071882'

            >>> arrow.utcnow().format('MMMM DD, YYYY')
            'May 09, 2013'

            >>> arrow.utcnow().format()
            '2013-05-09 03:56:47 -00:00'
[THINKING] // Thinking: I need to see the implementation of `format` in `arrow/arrow.py` and how it uses `formatter`.
[ACTION] read_file({"end_line": 880, "filepath": "arrow/arrow.py", "start_line": 861})
[OBSERVATION] 
        """

        return formatter.DateTimeFormatter(locale).format(self._datetime, fmt)

    def humanize(
        self, other=None, locale="en_us", only_distance=False, granularity="auto"
    ):
        """ Returns a localized, humanized representation of a relative difference in time.

        :param other: (optional) an :class:`Arrow <arrow.arrow.Arrow>` or ``datetime`` object.
            Defaults to now in the current :class:`Arrow <arrow.arrow.Arrow>` object's timezone.
        :param locale: (optional) a ``str`` specifying a locale.  Defaults to 'en_us'.
        :param only_distance: (optional) returns only time difference eg: "11 seconds" without "in" or "ago" part.
        :param granularity: (optional) defines the precision of the output. Set it to strings 'second', 'minute',
                           'hour', 'day', 'week', 'month' or 'year' or a list of any combination of these strings

        Usage::

            >>> earlier = arrow.utcnow().shift(hours=-2)
[THINKING] // Thinking: Now let's look at `arrow/formatter.py` to see where the formats are defined.
[ACTION] run_command({"command": "grep -n \"format\" arrow/formatter.py | head -n 20"})
[OBSERVATION] 26:    def format(cls, dt, fmt):
28:        return cls._FORMAT_RE.sub(lambda m: cls._format_token(dt, m.group(0)), fmt)
30:    def _format_token(self, dt, token):
45:            return "{:02d}".format(dt.month)
50:            return "{:03d}".format(dt.timetuple().tm_yday)
54:            return "{:02d}".format(dt.day)
69:            return "{:02d}".format(dt.hour)
73:            return "{:02d}".format(dt.hour if 0 < dt.hour < 13 else abs(dt.hour - 12))
78:            return "{:02d}".format(dt.minute)
83:            return "{:02d}".format(dt.second)
88:            return str("{:06d}".format(int(dt.microsecond)))
90:            return str("{:05d}".format(int(dt.microsecond / 10)))
92:            return str("{:04d}".format(int(dt.microsecond / 100)))
94:            return str("{:03d}".format(int(dt.microsecond / 1000)))
96:            return str("{:02d}".format(int(dt.microsecond / 10000)))
121:            return "{}{:02d}{}{:02d}".format(sign, hour, separator, minute)
128:            return "{}-W{:02d}-{}".format(year, week, day)

[THINKING] // Thinking: The `DateTimeFormatter.format` method uses a regex to replace tokens.
If we want to support "built-in format strings", we might want to allow `fmt` to be a key in a dictionary of predefined formats.

Wait, the problem description says "Create built-in format strings for common formats".
Let's see what common formats are usually expected. ISO 8601 is already the default if no fmt is provided? No, the default is `"YYYY-MM-DD HH:mm:ssZZ"`.

Looking at `arrow/arrow.py` again:
```python
    def format(self, fmt="YYYY-MM-DD HH:mm:ssZZ", locale="en_us"):
        """ Returns a string representation of the :class:`Arrow <arrow.arrow.Arrow>` object,
        formatted according to a format string.
```

If I want to add built-in formats, I should probably define a dictionary of them and check if `fmt` is one of the keys.

Let's see if there are already any constants for this.
[ACTION] run_command({"command": "grep -n \"FORMAT\" arrow/constants.py"})
[OBSERVATION ERROR] {"status": "error", "error_type": "CommandError", "error_message": "", "details": {"stdout": "", "stderr": "", "exit_code": 1}}
[THINKING] // Thinking: Nothing in `constants.py`.

Let's check `arrow/formatter.py` again to see if there's a good place for this.
[ACTION] read_file({"end_line": 100, "filepath": "arrow/formatter.py", "start_line": 1})
[OBSERVATION] # -*- coding: utf-8 -*-
from __future__ import absolute_import, division

import calendar
import re

from dateutil import tz as dateutil_tz

from arrow import locales, util


class DateTimeFormatter(object):

    # This pattern matches characters enclosed in square brackets are matched as
    # an atomic group. For more info on atomic groups and how to they are
    # emulated in Python's re library, see https://stackoverflow.com/a/13577411/2701578

    _FORMAT_RE = re.compile(
        r"(\[(?:(?=(?P<literal>[^]]))(?P=literal))*\]|YYY?Y?|MM?M?M?|Do|DD?D?D?|d?dd?d?|HH?|hh?|mm?|ss?|SS?S?S?S?S?|ZZ?Z?|a|A|X|x|W)"
    )

    def __init__(self, locale="en_us"):

        self.locale = locales.get_locale(locale)

    def format(cls, dt, fmt):

        return cls._FORMAT_RE.sub(lambda m: cls._format_token(dt, m.group(0)), fmt)

    def _format_token(self, dt, token):

        if token and token.startswith("[") and token.endswith("]"):
            return token[1:-1]

        if token == "YYYY":
            return self.locale.year_full(dt.year)
        if token == "YY":
            return self.locale.year_abbreviation(dt.year)

        if token == "MMMM":
            return self.locale.month_name(dt.month)
        if token == "MMM":
            return self.locale.month_abbreviation(dt.month)
        if token == "MM":
            return "{:02d}".format(dt.month)
        if token == "M":
            return str(dt.month)

        if token == "DDDD":
            return "{:03d}".format(dt.timetuple().tm_yday)
        if token == "DDD":
            return str(dt.timetuple().tm_yday)
        if token == "DD":
            return "{:02d}".format(dt.day)
        if token == "D":
            return str(dt.day)

        if token == "Do":
            return self.locale.ordinal_number(dt.day)

        if token == "dddd":
            return self.locale.day_name(dt.isoweekday())
        if token == "ddd":
            return self.locale.day_abbreviation(dt.isoweekday())
        if token == "d":
            return str(dt.isoweekday())

        if token == "HH":
            return "{:02d}".format(dt.hour)
        if token == "H":
            return str(dt.hour)
        if token == "hh":
            return "{:02d}".format(dt.hour if 0 < dt.hour < 13 else abs(dt.hour - 12))
        if token == "h":
            return str(dt.hour if 0 < dt.hour < 13 else abs(dt.hour - 12))

        if token == "mm":
            return "{:02d}".format(dt.minute)
        if token == "m":
            return str(dt.minute)

        if token == "ss":
            return "{:02d}".format(dt.second)
        if token == "s":
            return str(dt.second)

        if token == "SSSSSS":
            return str("{:06d}".format(int(dt.microsecond)))
        if token == "SSSSS":
            return str("{:05d}".format(int(dt.microsecond / 10)))
        if token == "SSSS":
            return str("{:04d}".format(int(dt.microsecond / 100)))
        if token == "SSS":
            return str("{:03d}".format(int(dt.microsecond / 1000)))
        if token == "SS":
            return str("{:02d}".format(int(dt.microsecond / 10000)))
        if token == "S":
            return str(int(dt.microsecond / 100000))

        if token == "X":
[THINKING] // Thinking: Wait, I see a bug in `DateTimeFormatter.format` signature.
`def format(cls, dt, fmt):`
But `DateTimeFormatter` is a class, and it's called as `formatter.DateTimeFormatter(locale).format(self._datetime, fmt)`.
So `format` is an instance method, but it's defined as if it were a class method (using `cls`).
But it's called on an instance. This should work since `cls` just becomes `self`.

Anyway, back to the task. "Create built-in format strings for common formats".
If I check some other libraries like `arrow`'s competitors or just common patterns.
Common formats could be:
- ISO 8601: `YYYY-MM-DDTHH:mm:ssZZ`
- RFC 2822: `ddd, DD MMM YYYY HH:mm:ss ZZ`
- etc.

Wait, the issue says "replaces #770 ref #762". I can't see those issues, but I can guess.
Usually, "built-in format strings" mean that instead of passing `'YYYY-MM-DD'`, you could pass `'ISO8601'`.

Let's see if there is any existing list of formats in the codebase that I missed.

Actually, I'll check how `arrow` handles ISO 8601.
`arrow.utcnow().isoformat()` is a method.

If I look at `arrow/arrow.py` again, I can add a dictionary of formats there or in `formatter.py`.
If I add it to `formatter.py`, I can modify `DateTimeFormatter.format` to check if `fmt` is in that dictionary.

Let's define some common formats.
`ISO_8601`: `YYYY-MM-DDTHH:mm:ssZZ`
`RFC_2822`: `ddd, DD MMM YYYY HH:mm:ss ZZ` (roughly)

Let's see if there are any other candidates.
Actually, looking at the problem statement again, it doesn't specify WHICH formats.
If I'm an engineer fixing this, I'd look for a standard set of formats.

Wait, maybe I can find more info by looking at the tests? No, that would be cheating if the tests are already there, but they probably aren't.

Let's search for "format" in the whole repo to see if there's any hint of what formats are considered "common".
[ACTION] run_command({"command": "grep -r \"format\" arrow | grep \"=\\\"\""})
[OBSERVATION] arrow/arrow.py:    def format(self, fmt="YYYY-MM-DD HH:mm:ssZZ", locale="en_us"):
arrow/arrow.py:    def isoformat(self, sep="T"):

[THINKING] // Thinking: Not much.

Let's try to find where other "built-in" things are defined.
Maybe I should check if there's a standard for Arrow's built-in formats.
Wait, I am supposed to *create* them.

If I look at the `arrow` documentation (hypothetically), it might say something.
But I only have the code.

If I look at `arrow/formatter.py` again, maybe I can add a dictionary called `BUILTIN_FORMATS`.

```python
BUILTIN_FORMATS = {
    'ISO8601': 'YYYY-MM-DDTHH:mm:ssZZ',
    'RFC2822': 'ddd, DD MMM YYYY HH:mm:ss ZZ',
}
```

But wait, what if the user wants to use these?
They would call `arrow.utcnow().format('ISO8601')`.

Let's see if I can find any clues in the current `arrow/formatter.py`.

Actually, let's look at the `format` method again.
```python
    def format(cls, dt, fmt):

        return cls._FORMAT_RE.sub(lambda m: cls._format_token(dt, m.group(0)), fmt)
```

If `fmt` is `'ISO8601'`, and it's not in the regex, it will just return `'ISO8601'`.
So I should check if `fmt` is a key in `BUILTIN_FORMATS` first.

Wait, what if the user *wants* to format the string "ISO8601"? (Unlikely, but possible).
But usually, these built-in formats are identified by a specific set of strings.

Let's see if there are other similar libraries that do this.
Actually, if I'm not sure what the "common formats" are, maybe I should look at the tests to see if there are any "TODO" or "FIXME" related to this.
[ACTION] run_command({"command": "grep -r \"TODO\" ."})
[OBSERVATION] ./arrow/parser.py:    # TODO: since we support more than ISO 8601, we should rename this function
./arrow/parser.py:        # TODO: add a flag to normalize whitespace (useful in logs, ref issue #421)
./arrow/parser.py:        # TODO: allow users to specify the number of digits to parse
./arrow/formatter.py:            # TODO: replace with a call to dt.timestamp() when we drop Python 2.7
./arrow/formatter.py:            # TODO: replace with a call to dt.timestamp() when we drop Python 2.7
./.git/hooks/sendemail-validate.sample:# Replace the TODO placeholders with appropriate checks according to your
./.git/hooks/sendemail-validate.sample:	# TODO: Replace with appropriate checks (e.g. spell checking).
./.git/hooks/sendemail-validate.sample:	# TODO: Replace with appropriate checks for this patch
./.git/hooks/sendemail-validate.sample:	# TODO: Replace with appropriate checks for the whole series

[THINKING] // Thinking: Nothing useful.

Let's consider what common formats are actually used.
ISO 8601 is very common.
RFC 2822 is also common.
Maybe some others like "long", "short", "medium" as in some other date libraries?
But Arrow seems to focus on tokens like `YYYY-MM-DD`.

Wait, I can check if there are any constants already defined in the project that could be used.
I already checked `constants.py`.

Let's try to see if there's any mention of "built-in" in the codebase.
[ACTION] run_command({"command": "grep -r \"built-in\" ."})
[OBSERVATION] ./README.rst:Why use Arrow over built-in modules?

[THINKING] // Thinking: Nothing.

Wait, maybe I should look at how other people have implemented this in Arrow.
Since I can't search the web, I have to rely on what's in the repo.

Wait, I see `arrow/constants.py`. Let's read it.
[ACTION] read_file({"filepath": "arrow/constants.py"})
[OBSERVATION] # -*- coding: utf-8 -*-

# Output of time.mktime(datetime.max.timetuple()) on macOS
# This value must be hardcoded for compatibility with Windows
# Platform-independent max timestamps are hard to form
# https://stackoverflow.com/q/46133223
MAX_TIMESTAMP = 253402318799.0
MAX_TIMESTAMP_MS = MAX_TIMESTAMP * 1000
MAX_TIMESTAMP_US = MAX_TIMESTAMP * 1000000
[THINKING] // Thinking: Very empty.

Let's assume the common formats are ISO 8601 and RFC 2822.
But wait, if I don't know the exact formats requested, I might be implementing the wrong thing.
However, the problem statement says "Create built-in format strings for common formats".

If I look at the `format` method in `arrow/arrow.py`:
```python
    def format(self, fmt="YYYY-MM-DD HH:mm:ssZZ", locale="en_us"):
```
The default is `"YYYY-MM-DD HH:mm:ssZZ"`.

Maybe I can define a dictionary in `arrow/formatter.py` and use it in `format` method.

```python
BUILTIN_FORMATS = {
    'ISO8601': 'YYYY-MM-DDTHH:mm:ssZZ',
    'RFC2822': 'ddd, DD MMM YYYY HH:mm:ss ZZ',
}
```

Wait, let's see if I can find any other clues.
What about the `parser`? Maybe it has some built-in formats.
[ACTION] read_file({"filepath": "arrow/parser.py"})
[OBSERVATION] # -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals

import re
from datetime import datetime, timedelta

from dateutil import tz

from arrow import locales
from arrow.constants import MAX_TIMESTAMP, MAX_TIMESTAMP_MS, MAX_TIMESTAMP_US
from arrow.util import iso_to_gregorian

try:
    from functools import lru_cache
except ImportError:  # pragma: no cover
    from backports.functools_lru_cache import lru_cache  # pragma: no cover


class ParserError(ValueError):
    pass


# Allows for ParserErrors to be propagated from _build_datetime()
# when day_of_year errors occur.
# Before this, the ParserErrors were caught by the try/except in
# _parse_multiformat() and the appropriate error message was not
# transmitted to the user.
class ParserMatchError(ParserError):
    pass


class DateTimeParser(object):

    _FORMAT_RE = re.compile(
        r"(YYY?Y?|MM?M?M?|Do|DD?D?D?|d?d?d?d|HH?|hh?|mm?|ss?|S+|ZZ?Z?|a|A|x|X|W)"
    )
    _ESCAPE_RE = re.compile(r"\[[^\[\]]*\]")

    _ONE_OR_TWO_DIGIT_RE = re.compile(r"\d{1,2}")
    _ONE_OR_TWO_OR_THREE_DIGIT_RE = re.compile(r"\d{1,3}")
    _ONE_OR_MORE_DIGIT_RE = re.compile(r"\d+")
    _TWO_DIGIT_RE = re.compile(r"\d{2}")
    _THREE_DIGIT_RE = re.compile(r"\d{3}")
    _FOUR_DIGIT_RE = re.compile(r"\d{4}")
    _TZ_Z_RE = re.compile(r"([\+\-])(\d{2})(?:(\d{2}))?|Z")
    _TZ_ZZ_RE = re.compile(r"([\+\-])(\d{2})(?:\:(\d{2}))?|Z")
    _TZ_NAME_RE = re.compile(r"\w[\w+\-/]+")
    # NOTE: timestamps cannot be parsed from natural language strings (by removing the ^...$) because it will
    # break cases like "15 Jul 2000" and a format list (see issue #447)
    _TIMESTAMP_RE = re.compile(r"^\-?\d+\.?\d+$")
    _TIMESTAMP_EXPANDED_RE = re.compile(r"^\-?\d+$")
    _TIME_RE = re.compile(r"^(\d{2})(?:\:?(\d{2}))?(?:\:?(\d{2}))?(?:([\.\,])(\d+))?$")
    _WEEK_DATE_RE = re.compile(r"(?P<year>\d{4})[\-]?W(?P<week>\d{2})[\-]?(?P<day>\d)?")

    _BASE_INPUT_RE_MAP = {
        "YYYY": _FOUR_DIGIT_RE,
        "YY": _TWO_DIGIT_RE,
        "MM": _TWO_DIGIT_RE,
        "M": _ONE_OR_TWO_DIGIT_RE,
        "DDDD": _THREE_DIGIT_RE,
        "DDD": _ONE_OR_TWO_OR_THREE_DIGIT_RE,
        "DD": _TWO_DIGIT_RE,
        "D": _ONE_OR_TWO_DIGIT_RE,
        "HH": _TWO_DIGIT_RE,
        "H": _ONE_OR_TWO_DIGIT_RE,
        "hh": _TWO_DIGIT_RE,
        "h": _ONE_OR_TWO_DIGIT_RE,
        "mm": _TWO_DIGIT_RE,
        "m": _ONE_OR_TWO_DIGIT_RE,
        "ss": _TWO_DIGIT_RE,
        "s": _ONE_OR_TWO_DIGIT_RE,
        "X": _TIMESTAMP_RE,
        "x": _TIMESTAMP_EXPANDED_RE,
        "ZZZ": _TZ_NAME_RE,
        "ZZ": _TZ_ZZ_RE,
        "Z": _TZ_Z_RE,
        "S": _ONE_OR_MORE_DIGIT_RE,
        "W": _WEEK_DATE_RE,
    }

    SEPARATORS = ["-", "/", "."]

    def __init__(self, locale="en_us", cache_size=0):

        self.locale = locales.get_locale(locale)
        self._input_re_map = self._BASE_INPUT_RE_MAP.copy()
        self._input_re_map.update(
            {
                "MMMM": self._generate_choice_re(
                    self.locale.month_names[1:], re.IGNORECASE
                ),
                "MMM": self._generate_choice_re(
                    self.locale.month_abbreviations[1:], re.IGNORECASE
                ),
                "Do": re.compile(self.locale.ordinal_day_re),
                "dddd": self._generate_choice_re(
                    self.locale.day_names[1:], re.IGNORECASE
                ),
                "ddd": self._generate_choice_re(
                    self.locale.day_abbreviations[1:], re.IGNORECASE
                ),
                "d": re.compile(r"[1-7]"),
                "a": self._generate_choice_re(

…(+34054 chars — render truncation)
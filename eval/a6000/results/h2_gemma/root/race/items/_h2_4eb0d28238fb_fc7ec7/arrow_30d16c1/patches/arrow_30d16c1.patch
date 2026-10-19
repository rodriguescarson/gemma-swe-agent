diff --git a/Makefile b/Makefile
index 41b3519..cb2899c 100644
--- a/Makefile
+++ b/Makefile
@@ -2,14 +2,12 @@
 
 auto: build38
 
-build27: PYTHON_VER = python2.7
-build35: PYTHON_VER = python3.5
 build36: PYTHON_VER = python3.6
 build37: PYTHON_VER = python3.7
 build38: PYTHON_VER = python3.8
 build39: PYTHON_VER = python3.9
 
-build27 build35 build36 build37 build38 build39: clean
+build36 build37 build38 build39: clean
 	virtualenv venv --python=$(PYTHON_VER)
 	. venv/bin/activate; \
 	pip install -U pip setuptools wheel; \
diff --git a/arrow/constants.py b/arrow/constants.py
index 81e37b2..88a9863 100644
--- a/arrow/constants.py
+++ b/arrow/constants.py
@@ -1,9 +1,11 @@
 # -*- coding: utf-8 -*-
 
+import datetime
+
 # Output of time.mktime(datetime.max.timetuple()) on macOS
 # This value must be hardcoded for compatibility with Windows
 # Platform-independent max timestamps are hard to form
 # https://stackoverflow.com/q/46133223
-MAX_TIMESTAMP = 253402318799.0
+MAX_TIMESTAMP = datetime.datetime.max.timestamp()
 MAX_TIMESTAMP_MS = MAX_TIMESTAMP * 1000
 MAX_TIMESTAMP_US = MAX_TIMESTAMP * 1000000
diff --git a/arrow/util.py b/arrow/util.py
index acce887..6368bc5 100644
--- a/arrow/util.py
+++ b/arrow/util.py
@@ -1,115 +1 @@
-# -*- coding: utf-8 -*-
-from __future__ import absolute_import
-
-import datetime
-import numbers
-
-from dateutil.rrule import WEEKLY, rrule
-
-from arrow.constants import MAX_TIMESTAMP, MAX_TIMESTAMP_MS, MAX_TIMESTAMP_US
-
-
-def next_weekday(start_date, weekday):
-    """Get next weekday from the specified start date.
-
-    :param start_date: Datetime object representing the start date.
-    :param weekday: Next weekday to obtain. Can be a value between 0 (Monday) and 6 (Sunday).
-    :return: Datetime object corresponding to the next weekday after start_date.
-
-    Usage::
-
-        # Get first Monday after epoch
-        >>> next_weekday(datetime(1970, 1, 1), 0)
-        1970-01-05 00:00:00
-
-        # Get first Thursday after epoch
-        >>> next_weekday(datetime(1970, 1, 1), 3)
-        1970-01-01 00:00:00
-
-        # Get first Sunday after epoch
-        >>> next_weekday(datetime(1970, 1, 1), 6)
-        1970-01-04 00:00:00
-    """
-    if weekday < 0 or weekday > 6:
-        raise ValueError("Weekday must be between 0 (Monday) and 6 (Sunday).")
-    return rrule(freq=WEEKLY, dtstart=start_date, byweekday=weekday, count=1)[0]
-
-
-def total_seconds(td):
-    """Get total seconds for timedelta."""
-    return td.total_seconds()
-
-
-def is_timestamp(value):
-    """Check if value is a valid timestamp."""
-    if isinstance(value, bool):
-        return False
-    if not (
-        isinstance(value, numbers.Integral)
-        or isinstance(value, float)
-        or isinstance(value, str)
-    ):
-        return False
-    try:
-        float(value)
-        return True
-    except ValueError:
-        return False
-
-
-def normalize_timestamp(timestamp):
-    """Normalize millisecond and microsecond timestamps into normal timestamps."""
-    if timestamp > MAX_TIMESTAMP:
-        if timestamp < MAX_TIMESTAMP_MS:
-            timestamp /= 1e3
-        elif timestamp < MAX_TIMESTAMP_US:
-            timestamp /= 1e6
-        else:
-            raise ValueError(
-                "The specified timestamp '{}' is too large.".format(timestamp)
-            )
-    return timestamp
-
-
-# Credit to https://stackoverflow.com/a/1700069
-def iso_to_gregorian(iso_year, iso_week, iso_day):
-    """Converts an ISO week date tuple into a datetime object."""
-
-    if not 1 <= iso_week <= 53:
-        raise ValueError("ISO Calendar week value must be between 1-53.")
-
-    if not 1 <= iso_day <= 7:
-        raise ValueError("ISO Calendar day value must be between 1-7")
-
-    # The first week of the year always contains 4 Jan.
-    fourth_jan = datetime.date(iso_year, 1, 4)
-    delta = datetime.timedelta(fourth_jan.isoweekday() - 1)
-    year_start = fourth_jan - delta
-    gregorian = year_start + datetime.timedelta(days=iso_day - 1, weeks=iso_week - 1)
-
-    return gregorian
-
-
-def validate_bounds(bounds):
-    if bounds != "()" and bounds != "(]" and bounds != "[)" and bounds != "[]":
-        raise ValueError(
-            'Invalid bounds. Please select between "()", "(]", "[)", or "[]".'
-        )
-
-
-# Python 2.7 / 3.0+ definitions for isstr function.
-
-try:  # pragma: no cover
-    basestring
-
-    def isstr(s):
-        return isinstance(s, basestring)  # noqa: F821
-
-
-except NameError:  # pragma: no cover
-
-    def isstr(s):
-        return isinstance(s, str)
-
-
-__all__ = ["next_weekday", "total_seconds", "is_timestamp", "isstr", "iso_to_gregorian"]
+# -*- coding: utf-8 -*-\n\nimport datetime\n\nfrom dateutil.rrule import WEEKLY, rrule\n\nfrom arrow.constants import MAX_TIMESTAMP, MAX_TIMESTAMP_MS, MAX_TIMESTAMP_US\n\n\ndef next_weekday(start_date, weekday):\n    \"\"\"Get next weekday from the specified start date.\n\n    :param start_date: Datetime object representing the start date.\n    :param weekday: Next weekday to obtain. Can be a value between 0 (Monday) and 6 (Sunday).\n    :return: Datetime object corresponding to the next weekday after start_date.\n\n    Usage::\n\n        # Get first Monday after epoch\n        >>> next_weekday(datetime(1970, 1, 1), 0)\n        1970-01-05 00:00:00\n\n        # Get first Thursday after epoch\n        >>> next_weekday(datetime(1970, 1, 1), 3)\n        1970-01-01 00:00:00\n\n        # Get first Sunday after epoch\n        >>> next_weekday(datetime(1970, 1, 1), 6)\n        1970-01-04 00:00:00\n    \"\"\"\n    if weekday < 0 or weekday > 6:\n        raise ValueError(\"Weekday must be between 0 (Monday) and 6 (Sunday).\")\n    return rrule(freq=WEEKLY, dtstart=start_date, byweekday=weekday, count=1)[0]\n\n\ndef total_seconds(td):\n    \"\"\"Get total seconds for timedelta.\"\"\"\n    return td.total_seconds()\n\n\ndef is_timestamp(value):\n    \"\"\"Check if value is a valid timestamp.\"\"\"\n    if isinstance(value, bool):\n        return False\n    if not (\n        isinstance(value, int)\n        or isinstance(value, float)\n        or isinstance(value, str)\n    ):\n        return False\n    try:\n        float(value)\n        return True\n    except ValueError:\n        return False\n\n\ndef normalize_timestamp(timestamp):\n    \"\"\"Normalize millisecond and microsecond timestamps into normal timestamps.\"\"\"\n    if timestamp > MAX_TIMESTAMP:\n        if timestamp < MAX_TIMESTAMP_MS:\n            timestamp /= 1e3\n        elif timestamp < MAX_TIMESTAMP_US:\n            timestamp /= 1e6\n        else:\n            raise ValueError(\n                \"The specified timestamp '{}' is too large.\".format(timestamp)\n            )\n    return timestamp\n\n\n# Credit to https://stackoverflow.com/a/1700069\ndef iso_to_gregorian(iso_year, iso_week, iso_day):\n    \"\"\"Converts an ISO week date tuple into a datetime object.\"\"\"\n\n    if not 1 <= iso_week <= 53:\n        raise ValueError(\"ISO Calendar week value must be between 1-53.\")\n\n    if not 1 <= iso_day <= 7:\n        raise ValueError(\"ISO Calendar day value must be between 1-7\")\n\n    # The first week of the year always contains 4 Jan.\n    fourth_jan = datetime.date(iso_year, 1, 4)\n    delta = datetime.timedelta(fourth_jan.isoweekday() - 1)\n    year_start = fourth_jan - delta\n    gregorian = year_start + datetime.timedelta(days=iso_day - 1, weeks=iso_week - 1)\n\n    return gregorian\n\n\ndef validate_bounds(bounds):\n    if bounds != \"()\" and bounds != \"(]\" and bounds != \"[)\" and bounds != \"[]\":\n        raise ValueError(\n            'Invalid bounds. Please select between \"()\", \"(]\", \"[)\\", or \"[]\".'\n        )\n\n\n__all__ = [\"next_weekday\", \"total_seconds\", \"is_timestamp\", \"iso_to_gregorian\"]
\ No newline at end of file
diff --git a/setup.py b/setup.py
index dc4f0e7..84d3842 100644
--- a/setup.py
+++ b/setup.py
@@ -22,20 +22,16 @@ setup(
     license="Apache 2.0",
     packages=["arrow"],
     zip_safe=False,
-    python_requires=">=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*, !=3.4.*",
+    python_requires=">=3.6",
     install_requires=[
         "python-dateutil>=2.7.0",
-        "backports.functools_lru_cache>=1.2.1;python_version=='2.7'",
     ],
     classifiers=[
-        "Development Status :: 4 - Beta",
+        "Development Status :: 4 - Stable",
         "Intended Audience :: Developers",
         "License :: OSI Approved :: Apache Software License",
         "Topic :: Software Development :: Libraries :: Python Modules",
-        "Programming Language :: Python :: 2",
-        "Programming Language :: Python :: 2.7",
         "Programming Language :: Python :: 3",
-        "Programming Language :: Python :: 3.5",
         "Programming Language :: Python :: 3.6",
         "Programming Language :: Python :: 3.7",
         "Programming Language :: Python :: 3.8",

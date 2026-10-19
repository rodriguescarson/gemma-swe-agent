diff --git a/arrow/arrow.py b/arrow/arrow.py
index 1bb2192..e587754 100644
--- a/arrow/arrow.py
+++ b/arrow/arrow.py
@@ -16,7 +16,7 @@ from math import trunc
 from dateutil import tz as dateutil_tz
 from dateutil.relativedelta import relativedelta
 
-from arrow import formatter, locales, parser, util
+from arrow import constants, formatter, locales, parser, util
 
 
 class Arrow(object):
diff --git a/arrow/constants.py b/arrow/constants.py
index 81e37b2..982b821 100644
--- a/arrow/constants.py
+++ b/arrow/constants.py
@@ -1,9 +1 @@
-# -*- coding: utf-8 -*-
-
-# Output of time.mktime(datetime.max.timetuple()) on macOS
-# This value must be hardcoded for compatibility with Windows
-# Platform-independent max timestamps are hard to form
-# https://stackoverflow.com/q/46133223
-MAX_TIMESTAMP = 253402318799.0
-MAX_TIMESTAMP_MS = MAX_TIMESTAMP * 1000
-MAX_TIMESTAMP_US = MAX_TIMESTAMP * 1000000
+# -*- coding: utf-8 -*-\n\n# Output of time.mktime(datetime.max.timetuple()) on macOS\n# This value must be hardcoded for compatibility with Windows\n# Platform-independent max timestamps are hard to form\n# https://stackoverflow.com/q/46133223\nMAX_TIMESTAMP = 253402318799.0\nMAX_TIMESTAMP_MS = MAX_TIMESTAMP * 1000\nMAX_TIMESTAMP_US = MAX_TIMESTAMP * 1000000\n\nCOMMON_FORMATS = {\n    'ISO8601': 'YYYY-MM-DDTHH:mm:ssZZ',\n    'RFC2822': 'ddd, DD MMM YYYY HH:mm:ss Z',\n}
\ No newline at end of file

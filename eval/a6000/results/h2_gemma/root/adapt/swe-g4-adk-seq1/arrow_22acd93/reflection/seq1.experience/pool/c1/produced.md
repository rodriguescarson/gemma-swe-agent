diff --git a/arrow/arrow.py b/arrow/arrow.py
index 1bb2192..ba44ef8 100644
--- a/arrow/arrow.py
+++ b/arrow/arrow.py
@@ -16,7 +16,7 @@ from math import trunc
 from dateutil import tz as dateutil_tz
 from dateutil.relativedelta import relativedelta
 
-from arrow import formatter, locales, parser, util
+from arrow import constants, formatter, locales, parser, util
 
 
 class Arrow(object):
@@ -861,6 +861,8 @@ class Arrow(object):
 
         """
 
+        if fmt in constants.COMMON_FORMATS:
+            fmt = constants.COMMON_FORMATS[fmt]
         return formatter.DateTimeFormatter(locale).format(self._datetime, fmt)
 
     def humanize(
diff --git a/arrow/constants.py b/arrow/constants.py
index 81e37b2..dea81e6 100644
--- a/arrow/constants.py
+++ b/arrow/constants.py
@@ -7,3 +7,8 @@
 MAX_TIMESTAMP = 253402318799.0
 MAX_TIMESTAMP_MS = MAX_TIMESTAMP * 1000
 MAX_TIMESTAMP_US = MAX_TIMESTAMP * 1000000
+
+COMMON_FORMATS = {
+    'ISO8601': 'YYYY-MM-DDTHH:mm:ssZZ',
+    'RFC2822': 'ddd, DD MMM YYYY HH:mm:ss Z',
+}

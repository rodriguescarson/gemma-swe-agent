diff --git a/arrow/factory.py b/arrow/factory.py
index 27dea5c..0747bb8 100644
--- a/arrow/factory.py
+++ b/arrow/factory.py
@@ -232,15 +232,15 @@ class ArrowFactory:
 
             # (Arrow) -> from the object's datetime.
             elif isinstance(arg, Arrow):
-                return self.type.fromdatetime(arg.datetime)
+                return self.type.fromdatetime(arg.datetime, tzinfo=tz)
 
             # (datetime) -> from datetime.
             elif isinstance(arg, datetime):
-                return self.type.fromdatetime(arg)
+                return self.type.fromdatetime(arg, tzinfo=tz)
 
             # (date) -> from date.
             elif isinstance(arg, date):
-                return self.type.fromdate(arg)
+                return self.type.fromdate(arg, tzinfo=tz)
 
             # (tzinfo) -> now, @ tzinfo.
             elif isinstance(arg, dt_tzinfo):
diff --git a/reproduce_issue.py b/reproduce_issue.py
new file mode 100644
index 0000000..a2ebf97
--- /dev/null
+++ b/reproduce_issue.py
@@ -0,0 +1,23 @@
+
+import arrow
+from datetime import datetime, date
+from dateutil import tz
+
+# Case 1: datetime with tzinfo kwarg
+dt = datetime(2023, 1, 1, 12, 0)
+arw = arrow.get(dt, tzinfo='US/Pacific')
+print(f"Case 1: {arw}")
+assert arw.utcoffset().total_seconds() == -8 * 3600
+
+# Case 2: date with tzinfo kwarg
+d = date(2023, 1, 1)
+arw = arrow.get(d, tzinfo='US/Pacific')
+print(f"Case 2: {arw}")
+# US/Pacific offset in Jan is -8h
+assert arw.utcoffset().total_seconds() == -8 * 3600
+
+# Case 3: Arrow with tzinfo kwarg
+arw_orig = arrow.get(datetime(2023, 1, 1), tzinfo='UTC')
+arw = arrow.get(arw_orig, tzinfo='US/Pacific')
+print(f"Case 3: {arw}")
+assert arw.utcoffset().total_seconds() == -8 * 3600

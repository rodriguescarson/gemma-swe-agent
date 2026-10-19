diff --git a/arrow/arrow.py b/arrow/arrow.py
index 899c680..6b12132 100644
--- a/arrow/arrow.py
+++ b/arrow/arrow.py
@@ -775,9 +775,9 @@ class Arrow:
             if key in self._ATTRS:
                 absolute_kwargs[key] = value
             elif key in ["week", "quarter"]:
-                raise AttributeError(f"setting absolute {key} is not supported")
+                raise ValueError(f"setting absolute {key} is not supported")
             elif key not in ["tzinfo", "fold"]:
-                raise AttributeError(f'unknown attribute: "{key}"')
+                raise ValueError(f'unknown attribute: "{key}"')
 
         current = self._datetime.replace(**absolute_kwargs)
 
@@ -833,8 +833,8 @@ class Arrow:
             if key in self._ATTRS_PLURAL or key in additional_attrs:
                 relative_kwargs[key] = value
             else:
-                raise AttributeError(
-                    "Invalid shift time frame. Please select one of the following: {}.".format(
+                raise ValueError(
+                    "Invalid shift time frame. Please select one of the following: {}".format(
                         ", ".join(self._ATTRS_PLURAL + additional_attrs)
                     )
                 )
@@ -1053,7 +1053,7 @@ class Arrow:
                 elif granularity == "year":
                     delta = sign * delta / self._SECS_PER_YEAR
                 else:
-                    raise AttributeError(
+                    raise ValueError(
                         "Invalid level of granularity. Please select between 'second', 'minute', 'hour', 'day', 'week', 'month' or 'year'"
                     )
 
@@ -1098,7 +1098,7 @@ class Arrow:
                     timeframes.append(["second", seconds])
 
                 if len(timeframes) < len(granularity):
-                    raise AttributeError(
+                    raise ValueError(
                         "Invalid level of granularity. "
                         "Please select between 'second', 'minute', 'hour', 'day', 'week', 'month' or 'year'."
                     )
@@ -1517,7 +1517,7 @@ class Arrow:
                 "quarter(s)",
             ]
         )
-        raise AttributeError(
+        raise ValueError(
             "range/span over frame {} not supported. Supported frames: {}".format(
                 name, supported
             )
diff --git a/arrow/factory.py b/arrow/factory.py
index 9bae80c..64088bf 100644
--- a/arrow/factory.py
+++ b/arrow/factory.py
@@ -208,7 +208,7 @@ class ArrowFactory:
 
             else:
                 raise TypeError(
-                    "Can't parse single argument of type '{}'".format(type(arg))
+                    f"Can't parse single argument of type '{type(arg)}'"
                 )
 
         elif arg_count == 2:
diff --git a/arrow/util.py b/arrow/util.py
index 7053a88..a477c20 100644
--- a/arrow/util.py
+++ b/arrow/util.py
@@ -31,9 +31,7 @@ def next_weekday(start_date, weekday):
     return rrule(freq=WEEKLY, dtstart=start_date, byweekday=weekday, count=1)[0]
 
 
-def total_seconds(td):
-    """Get total seconds for timedelta."""
-    return td.total_seconds()
+
 
 
 def is_timestamp(value):

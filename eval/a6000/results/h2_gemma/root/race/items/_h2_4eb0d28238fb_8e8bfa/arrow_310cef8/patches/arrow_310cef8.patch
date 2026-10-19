diff --git a/arrow/arrow.py b/arrow/arrow.py
index d01fa89..1f5675b 100644
--- a/arrow/arrow.py
+++ b/arrow/arrow.py
@@ -1357,14 +1357,19 @@ class Arrow:
 
             # Numeric unit of change
             change_value = 0
+            timeframe_value = locale_obj.timeframes[unit]
+            timeframe_values = timeframe_value.values() if isinstance(timeframe_value, dict) else [timeframe_value]
 
-            # Replace {0} with regex \d representing digits
-            search_string = str(locale_obj.timeframes[unit])
-            search_string = search_string.format(r"\d+")
+            match = None
+            for val in timeframe_values:
+                # Replace {0} with regex \d representing digits
+                search_string = str(val).format(r"\d+")
 
-            # Create search pattern and find within string
-            pattern = re.compile(fr"{search_string}")
-            match = pattern.search(timestring)
+                # Create search pattern and find within string
+                match = re.search(fr"{search_string}", timestring)
+
+                if match:
+                    break
 
             # If there is no match continue to next iteration
             if not match:
diff --git a/arrow/constants.py b/arrow/constants.py
index 3fb00c1..1b2e57e 100644
--- a/arrow/constants.py
+++ b/arrow/constants.py
@@ -48,6 +48,10 @@ DEHUMANIZE_LOCALES = {
     "en-za",
     "en-ca",
     "en-ph",
+    "fi",
+    "ne",
+    "et",
+    "zu",
     "fr",
     "fr-fr",
     "fr-ca",

diff --git a/arrow/locales.py b/arrow/locales.py
index 970d614..3ed16fb 100644
--- a/arrow/locales.py
+++ b/arrow/locales.py
@@ -4787,7 +4787,7 @@ class MalayLocale(Locale):
         "Khamis",
         "Jumaat",
         "Sabtu",
-        "Ahad ",
+        "Ahad",
     ]
 
     day_abbreviations = [
@@ -4798,7 +4798,90 @@ class MalayLocale(Locale):
         "Khamis",
         "Jumaat",
         "Sabtu",
-        "Ahad ",
+        "Ahad",
+    ]
+
+
+class MalteseLocale(Locale):
+
+    names = ["mt", "mt-mt"]
+
+    past = "{0} ilu"
+    future = "ta' {0}"
+    and_word = "u"
+
+    timeframes = {
+        "now": "issa",
+        "second": "sekonda",
+        "seconds": "{0} sekondi",
+        "minute": "minuta",
+        "minutes": "{0} minuti",
+        "hour": "ora",
+        "hours": "{0} swiegh",
+        "day": "jum",
+        "days": "{0} jumilhom",
+        "week": "ġimgħa",
+        "weeks": "{0} ġimgħijiet",
+        "month": "xahar",
+        "months": "{0} xhura",
+        "year": "sena",
+        "years": "{0} snin",
+    }
+
+    meridians = {"am": "am", "pm": "pm", "AM": "AM", "PM": "PM"}
+
+    month_names = [
+        "",
+        "Jannwar",
+        "Febrarju",
+        "Mars",
+        "Aprile",
+        "Mejju",
+        "Ġjunju",
+        "Lulju",
+        "Aġostu",
+        "Settembru",
+        "Ottubru",
+        "Novembru",
+        "Diċembru",
+    ]
+
+    month_abbreviations = [
+        "",
+        "Jan",
+        "Feb",
+        "Mar",
+        "Apr",
+        "Mej",
+        "Ġun",
+        "Lul",
+        "Aġo",
+        "Set",
+        "Ott",
+        "Nov",
+        "Diċ",
+    ]
+
+    day_names = [
+        "",
+        "Tnejn",
+        "Martub",
+        "Erbħa",
+        "Ħamis",
+        "Ġimgħa",
+        "Sabt",
+        "Ħadd",
+    ]
+
+    day_abbreviations = [
+        "",
+        "Tnej",
+        "Mart",
+        "Erbħ",
+        "Ħami",
+        "Ġimg",
+        "Sabt",
+        "Ħadd",
     ]
 
 

diff --git a/arrow/locales.py b/arrow/locales.py
index 970d614..88e5619 100644
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
@@ -4798,11 +4798,11 @@ class MalayLocale(Locale):
         "Khamis",
         "Jumaat",
         "Sabtu",
-        "Ahad ",
+        "Ahad",
     ]
 
 
-class OdiaLocale(Locale):
+    ]\n\n\nclass MalteseLocale(Locale):\n    names = [\"mt\", \"mt-mt\"]\n    past = \"{0} ilu\"\n    future = \"fir-{0}\"\n    and_word = \"u\"\n\n    timeframes = {\n        \"now\": \"issa\",\n        \"second\": \"sekonda\",\n        \"seconds\": \"{0} sekondi\",\n        \"minute\": \"minuta\",\n        \"minutes\": \"{0} minuti\",\n        \"hour\": \"sigħa\",\n        \"hours\": \"{0} sigħa\",\n        \"day\": \"ġurnata\",\n        \"days\": \"{0} ġurnata\",\n        \"week\": \"ġimgħa\",\n        \"weeks\": \"{0} ġimgħat\",\n        \"month\": \"xahar\",\n        \"months\": \"{0} xhura\",\n        \"year\": \"sena\",\n        \"years\": \"{0} sena\",\n    }\n\n    month_names = [\n        \"\",\n        \"Janvarju\",\n        \"Februarju\",\n        \"Marzu\",\n        \"April\",\n        \"Majju\",\n        \"Ġjunju\",\n        \"Julju\",\n        \"Aġostu\",\n        \"Settembru\",\n        \"Ottubru\",\n        \"Novembru\",\n        \"Diċembru\",\n    ]\n    month_abbreviations = [\n        \"\",\n        \"Jan\",\n        \"Feb\",\n        \"Mar\",\n        \"Apr\",\n        \"Maj\",\n        \"Ġun\",\n        \"Jul\",\n        \"Aġo\",\n        \"Set\",\n        \"Ott\",\n        \"Nov\",\n        \"Diċ\",\n    ]\n    day_names = [\n        \"\",\n        \"tnejn\",\n        \"tlet\",\n        \"erbgħa\",\n        \"ġamma\",\n        \"ġimgħa\",\n        \"sebt\",\n        \"Ħadd\",\n    ]\n    day_abbreviations = [\n        \"\",\n        \"tnejn\",\n        \"tlet\",\n        \"erbgħa\",\n        \"ġamma\",\n        \"ġimgħa\",\n        \"sebt\",\n        \"Ħadd\",\n    ]\n\n\nclass OdiaLocale(Locale):
 
     names = ["or", "or-in"]
 

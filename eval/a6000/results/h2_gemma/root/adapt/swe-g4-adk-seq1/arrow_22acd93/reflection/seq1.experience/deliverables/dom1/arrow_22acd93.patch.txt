diff --git a/arrow/formatter.py b/arrow/formatter.py
index 325c393..5b19f23 100644
--- a/arrow/formatter.py
+++ b/arrow/formatter.py
@@ -15,7 +15,7 @@ class DateTimeFormatter(object):
     # an atomic group. For more info on atomic groups and how to they are
     # emulated in Python's re library, see https://stackoverflow.com/a/13577411/2701578
 
-    _FORMAT_RE = re.compile(
+    _FORMAT_RE = re.compile(\n        r"(\\[(?:(?=(?P<literal>[^]]))(?P=literal))*\\]|YYY?Y?|MM?M?M?|Do|DD?D?D?|d?dd?d?|HH?|hh?|mm?|ss?|SS?S?S?S?S?|ZZ?Z?|a|A|X|x|W)"\n    )\n\n    BUILTIN_FORMATS = {\n        'ISO8601': 'YYYY-MM-DDTHH:mm:ssZZ',\n        'RFC2822': 'ddd, DD MMM YYYY HH:mm:ss ZZ',\n    }
         r"(\[(?:(?=(?P<literal>[^]]))(?P=literal))*\]|YYY?Y?|MM?M?M?|Do|DD?D?D?|d?dd?d?|HH?|hh?|mm?|ss?|SS?S?S?S?S?|ZZ?Z?|a|A|X|x|W)"
     )
 

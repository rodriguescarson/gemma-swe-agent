diff --git a/arrow/__init__.py b/arrow/__init__.py
index bc59709..9232b37 100644
--- a/arrow/__init__.py
+++ b/arrow/__init__.py
@@ -11,6 +11,7 @@ from .formatter import (
     FORMAT_RFC1123,
     FORMAT_RFC2822,
     FORMAT_RFC3339,
+    FORMAT_RFC3339_STRICT,
     FORMAT_RSS,
     FORMAT_W3C,
 )
@@ -33,6 +34,7 @@ __all__ = [
     "FORMAT_RFC1123",
     "FORMAT_RFC2822",
     "FORMAT_RFC3339",
+    "FORMAT_RFC3339_STRICT",
     "FORMAT_RSS",
     "FORMAT_W3C",
     "ParserError",
diff --git a/arrow/formatter.py b/arrow/formatter.py
index 8cd61e9..6634545 100644
--- a/arrow/formatter.py
+++ b/arrow/formatter.py
@@ -17,6 +17,7 @@ FORMAT_RFC1036: Final[str] = "ddd, DD MMM YY HH:mm:ss Z"
 FORMAT_RFC1123: Final[str] = "ddd, DD MMM YYYY HH:mm:ss Z"
 FORMAT_RFC2822: Final[str] = "ddd, DD MMM YYYY HH:mm:ss Z"
 FORMAT_RFC3339: Final[str] = "YYYY-MM-DD HH:mm:ssZZ"
+FORMAT_RFC3339_STRICT: Final[str] = "YYYY-MM-DDTHH:mm:ssZZ"
 FORMAT_RSS: Final[str] = "ddd, DD MMM YYYY HH:mm:ss Z"
 FORMAT_W3C: Final[str] = "YYYY-MM-DD HH:mm:ssZZ"
 

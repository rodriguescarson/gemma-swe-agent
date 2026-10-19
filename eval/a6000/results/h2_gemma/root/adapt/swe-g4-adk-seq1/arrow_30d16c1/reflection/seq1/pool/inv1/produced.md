diff --git a/setup.py b/setup.py
index dc4f0e7..5c46359 100644
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
+        "Development Status :: 5 - Production/Stable",
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

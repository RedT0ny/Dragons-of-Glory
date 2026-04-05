[app]
title = Dragons of Glory
package.name = dragonsofglory
package.domain = org.redtony

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,qml,js,svg,ttf,ico
source.exclude_dirs = .git,.github,build,dist,venv,.venv,__pycache__,android-wheels,ci-debug

version = 0.1

requirements = python3==3.11.11,hostpython3==3.11.11,shiboken6,PySide6

orientation = portrait
fullscreen = 0

android.archs = arm64-v8a
android.allow_backup = True
android.permissions = android.permission.INTERNET,android.permission.WRITE_EXTERNAL_STORAGE

android.api = 34
android.minapi = 24

p4a.branch = master
p4a.bootstrap = qt
p4a.local_recipes = src/deployment/recipes
p4a.extra_args = --qt-libs=Core,Gui,Widgets --load-local-libs=plugins_platforms_qtforandroid --init-classes=
android.add_jars = src/deployment/jar/PySide6/jar/Qt6Android.jar,src/deployment/jar/PySide6/jar/Qt6AndroidBindings.jar

log_level = 2
warn_on_root = 1

[buildozer]
log_level = 2
warn_on_root = 1
bin_dir = bin
[app]
title = DragonsOfGlory
input_file = main.py
project_dir = .
project_file = pyproject.toml
exec_directory = .
icon = assets/icon/DOG_icon.ico

[python]
python_path =
packages = src
extra_args =
android_packages = buildozer==1.5.0,Cython==0.29.33

[qt]
qml_files =
excluded_qml_plugins =

[android]
package_name = org.dragonsofglory.game
app_name = Dragons of Glory
wheel_pyside =
wheel_shiboken =
ndk_path =
sdk_path =
android_platform = android-34
permissions =
features =
local_libs =
extra_files = assets,data

[buildozer]
mode = debug
from PyInstaller.compat import is_win
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

datas = []
binaries = []

if is_win:
    datas = collect_data_files('qtwebview2', subdir='lib')
    binaries = collect_dynamic_libs('qtwebview2')
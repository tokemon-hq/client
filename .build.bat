@echo off

pyinstaller.exe -i tokemon.ico --noconsole --onefile --add-data main.py;src main.py

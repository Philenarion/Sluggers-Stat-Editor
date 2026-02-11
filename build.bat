@echo off
uvx pyinstaller --name sluggers-stat-editor --onefile --noconsole editorV3.py

rem Copy release-template contents into dist\
xcopy /s /y release-template\* dist\

rem Copy source code into dist\Source-Code\
mkdir dist\Source-Code 2>nul
copy /y editorV3.py dist\Source-Code\

echo Build complete: dist\sluggers-stat-editor.exe

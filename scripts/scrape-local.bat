@echo off
setlocal EnableDelayedExpansion
REM ============================================================
REM  car-tracker scrape-local -- egykattintasos futtato (Windows)
REM
REM  Mit csinal: a Tesla.com + Hasznaltauto.hu forrasokat szedi
REM  le a TE gepedrol (otthoni halozatrol ezek mukodnek, a napi
REM  GitHub-futtatas adatkozponti cimeirol nem), es ugyanabba a
REM  Supabase adatbazisba irja, amit a tobbi forras hasznal.
REM
REM  Hasznalat: dupla kattintas. Elso inditaskor elkeri a
REM  DATABASE_URL-t, es felajanlja a napi automatikus futtatast.
REM  A "set /p valasz" sorok szandekosan goto-folyammal, nem ( )
REM  blokkal kovetkeznek: cmd.exe a blokkot egyben ertekeli ki,
REM  igy a blokkon belul bekert valtozo erteke ott meg ures.
REM ============================================================

set "CONFIG=%~dp0car-tracker-database-url.txt"
set "REPO=git+https://github.com/Pacha-88/Car"

REM --- uv telepitese, ha meg nincs ---
where uv >nul 2>nul
if not errorlevel 1 goto :have_uv
echo Az "uv" futtato meg nincs telepitve - telepitem most (egyszeri lepes)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>nul
if not errorlevel 1 goto :have_uv
echo HIBA: az uv telepitese nem sikerult. Kezi telepites: https://docs.astral.sh/uv/
pause
exit /b 1
:have_uv

REM --- adatbazis-cim: elso futaskor bekeres, utana fajlbol ---
if exist "%CONFIG%" goto :have_config
echo.
echo Elso futtatas: add meg a Supabase kapcsolati cimet.
echo (Ugyanaz az ertek, mint a GitHub "DATABASE_URL" secret,
echo  postgresql+psycopg://... alakban.)
echo.
set "DBURL="
set /p DBURL="DATABASE_URL: "
if defined DBURL goto :save_config
echo HIBA: nem adtal meg cimet.
pause
exit /b 1
:save_config
REM Kesleltetett kiertekeles (!DBURL!), nem %DBURL%: egy & vagy ^ a
REM jelszoban a sima formaban kettevagta volna az echo parancsot, es fel
REM URL kerult volna a fajlba.
>"%CONFIG%" echo(!DBURL!
echo Elmentve ide: %CONFIG%
:have_config
set /p DATABASE_URL=<"%CONFIG%"
if defined DATABASE_URL goto :lock
echo HIBA: ures a konfiguracios fajl - torold es inditsd ujra: %CONFIG%
pause
exit /b 1

REM --- egyszerre csak egy futas ---
REM A .command parjaban ez mar regota megvan; itt hianyzott, pedig az
REM utemezett 07:30-as futas + egy kezi dupla kattintas ugyanabba az
REM adatbazisba irna parhuzamosan. A cmd nem tudja megkerdezni, el-e meg
REM a zar gazdaja, ezert kor alapjan dontunk: egy 3 oranal regebbi zar
REM egy osszeomlott futase, es atvesszuk - kulonben egyetlen rossz nap
REM vegleg megallitana a napi futast.
:lock
set "LOCKDIR=%~dp0.scrape-local.lock"
mkdir "%LOCKDIR%" 2>nul && goto :run
powershell -NoProfile -Command "if ((Get-Item -LiteralPath '%LOCKDIR%').LastWriteTime -lt (Get-Date).AddHours(-3)) { exit 0 } else { exit 1 }" 2>nul
if errorlevel 1 goto :lock_busy
rmdir /s /q "%LOCKDIR%" 2>nul
mkdir "%LOCKDIR%" 2>nul && goto :run
:lock_busy
echo Mar fut egy scrape ebbol a mappabol (zar: %LOCKDIR%).
echo Ha biztosan nem fut, torold a mappat es inditsd ujra.
if /I not "%~1"=="auto" pause
exit /b 0

:run
REM A csomag "browser" extraja a Playwright Python-oldalat hozza; a nagy
REM (~150 MB) bongeszo-binarist NEM toltjuk le elore, csak ha egy oldal
REM tenyleg megkoveteli. Legtobbszor a Chrome TLS-ujjlenyomat eleg.
set "FROM_SPEC=car-tracker[browser] @ %REPO%"
set "LOG=%~dp0scrape-local-last-run.log"
echo.
echo Scrape indul... (elso alkalommal 1-2 perc a letoltes, utana gyorsabb)
uv tool run --refresh --from "%FROM_SPEC%" car-tracker scrape-local > "%LOG%" 2>&1
set "RESULT=%ERRORLEVEL%"
type "%LOG%"

REM Ha barmelyik forras valodi bongeszot kert, telepitjuk es ujraprobaljuk.
findstr /C:"playwright install" "%LOG%" >nul 2>nul
if errorlevel 1 goto :after_run
echo.
echo Egy oldal valodi bongeszot igenyel - letoltom egyszer (~150 MB), majd ujraprobalom...
uv tool run --from "%FROM_SPEC%" python -m playwright install chromium
echo.
uv tool run --from "%FROM_SPEC%" car-tracker scrape-local > "%LOG%" 2>&1
set "RESULT=%ERRORLEVEL%"
type "%LOG%"
:after_run

echo.
if not "%RESULT%"=="0" goto :had_failure
echo KESZ - minden forras lefutott. A dashboard a kovetkezo napi
echo frissiteskor mutatja az uj adatot (vagy inditsd el kezzel a
echo GitHub Actions "Run workflow" gombjaval).
goto :maybe_schedule
:had_failure
echo Legalabb egy forras hibaval vegzodott - a reszletek fentebb.
echo Ami sikerult, az igy is elmentodott.

:maybe_schedule
REM --- napi automatikus futtatas felajanlasa (csak kezi inditaskor) ---
if /I "%~1"=="auto" goto :done
schtasks /Query /TN "car-tracker scrape-local" >nul 2>nul
if not errorlevel 1 goto :done
echo.
REM 07:30, nem 07:00: a GitHub-futas 05:00 UTC-kor indul, ami nyari
REM idoszamitasban pont 07:00 nalunk - ket futas ugyanabba az adatbazisba
REM ugyanabban a percben. Fel ora keses ezt megszunteti (a .command
REM ugyanezert 07:30-ra utemez).
set "SCHED="
set /p SCHED="Fusson ezentul minden nap automatikusan 07:30-kor? (i/n): "
if /I not "%SCHED%"=="i" goto :done
schtasks /Create /F /SC DAILY /ST 07:30 /TN "car-tracker scrape-local" /TR "\"%~f0\" auto"
echo Beallitva. Torles barmikor: schtasks /Delete /TN "car-tracker scrape-local"

:done
rmdir /s /q "%LOCKDIR%" 2>nul
if /I not "%~1"=="auto" pause
endlocal

#!/usr/bin/env bash
# ============================================================
#  car-tracker scrape-local — egykattintásos futtató (macOS/Linux)
#
#  Mit csinál: a Tesla.com + Használtautó.hu forrásokat szedi le
#  a TE gépedről (otthoni hálózatról ezek működnek, a napi
#  GitHub-futtatás adatközponti címeiről nem), és ugyanabba a
#  Supabase adatbázisba írja, amit a többi forrás használ.
#
#  Használat macOS-en: dupla kattintás (a .command kiterjesztést a
#  Finder Terminálban nyitja meg). Linuxon: bash scrape-local.command
#  Első indításkor elkéri a DATABASE_URL-t, és felajánlja a napi
#  automatikus futtatást (cron).
# ============================================================
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SELF="$SCRIPT_DIR/$(basename "$0")"
CONFIG="$SCRIPT_DIR/car-tracker-database-url.txt"
REPO="git+https://github.com/Pacha-88/Car"

# --- make future double-clicks work ---
# A file downloaded from a browser arrives without the execute bit and, on
# macOS, carrying com.apple.quarantine - so the first double-click fails
# with "Permission denied" before a single line of this script runs. It
# cannot fix that for its own first run (see the one-paste command in
# docs/DEPLOYMENT.md), but it can make every run after this one work.
chmod +x "$SELF" 2>/dev/null || true
xattr -d com.apple.quarantine "$SELF" 2>/dev/null || true

# --- egyszerre csak egy futas ---
# A cron 07:30-kor inditja, te pedig barmikor duplan kattinthatsz. Ket
# parhuzamos futas ugyanazokat a sorokat irja ugyanabban az adatbazisban:
# nem romlik el tole adat (a hibas kombo hibasnak szamit, es akkor nem
# nyugdijaz semmit), de az egyik futas ertelmetlen "duplicate key" hibaval
# all meg. Egyszerubb meg sem engedni.
LOCK="$SCRIPT_DIR/.scrape-local.lock"
acquire_lock() {
  mkdir "$LOCK" 2>/dev/null && { echo $$ > "$LOCK/pid"; return 0; }
  # Van egy zar. Egy osszeomlott futas (lefagyott gep, aramszunet, kilott
  # folyamat) is itt hagyja: olyankor az EXIT trap sosem futott le, es a
  # zar nelkule orokre ott maradna - a cron pedig minden reggel neman,
  # "mar fut" hivatkozassal lepne ki, azaz egyetlen rossz nap vegleg
  # megallitana a napi futast. Ezert a zar a tulajdonos PID-jet hordozza:
  # ha az a folyamat mar nem el, a zar gazdatlan, es atvesszuk.
  local pid
  pid="$(cat "$LOCK/pid" 2>/dev/null)"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    return 1  # tenyleg fut most is
  fi
  rm -rf "$LOCK"
  mkdir "$LOCK" 2>/dev/null && { echo $$ > "$LOCK/pid"; return 0; }
  return 1  # ket atvevo versenyzett, a masik nyert - az is egy elo futas
}
if ! acquire_lock; then
  echo "Már fut egy scrape ebből a mappából (zár: $LOCK)."
  echo "Ha biztosan nem fut, töröld a mappát és indítsd újra."
  [ "${1:-}" != "auto" ] && read -r -p "Nyomj Entert a kilépéshez..." _
  exit 0
fi
trap 'rm -rf "$LOCK" 2>/dev/null' EXIT INT TERM HUP

# --- uv telepítése, ha még nincs ---
if ! command -v uv >/dev/null 2>&1; then
  echo 'Az "uv" futtató még nincs telepítve — telepítem most (egyszeri lépés)...'
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "HIBA: az uv telepítése nem sikerült. Kézi telepítés: https://docs.astral.sh/uv/"
  read -r -p "Nyomj Entert a kilépéshez..." _
  exit 1
fi

# --- adatbázis-cím: első futáskor bekérés, utána fájlból ---
if [ ! -f "$CONFIG" ]; then
  echo
  echo "Első futtatás: add meg a Supabase kapcsolati címet."
  echo '(Ugyanaz az érték, mint a GitHub "DATABASE_URL" secret,'
  echo ' postgresql+psycopg://... alakban.)'
  echo
  read -r -p "DATABASE_URL: " DBURL
  if [ -z "$DBURL" ]; then
    echo "HIBA: nem adtál meg címet."
    exit 1
  fi
  printf '%s\n' "$DBURL" > "$CONFIG"
  chmod 600 "$CONFIG"
  echo "Elmentve ide: $CONFIG"
fi
DATABASE_URL="$(head -n1 "$CONFIG")"
if [ -z "$DATABASE_URL" ]; then
  echo "HIBA: üres a konfigurációs fájl — töröld és indítsd újra: $CONFIG"
  exit 1
fi
export DATABASE_URL

# --- futtatás (mindig a repó legfrissebb kódjával) ---
# A csomag "browser" extrája a Playwright Python-oldalát hozza; a nagy
# (~150 MB) böngésző-binárist NEM töltjük le előre, csak ha egy oldal
# tényleg megköveteli. Legtöbbször a Chrome TLS-ujjlenyomat elég.
FROM_SPEC="car-tracker[browser] @ $REPO"
LOG="$SCRIPT_DIR/scrape-local-last-run.log"

echo
echo "Scrape indul... (első alkalommal 1-2 perc a letöltés, utána gyorsabb)"
uv tool run --refresh --from "$FROM_SPEC" car-tracker scrape-local 2>&1 | tee "$LOG"
RESULT=${PIPESTATUS[0]}

# Ha barmelyik forras valodi bongeszot kert, telepitjuk es ujraprobaljuk.
if grep -q "playwright install" "$LOG" 2>/dev/null; then
  echo
  echo "Egy oldal valódi böngészőt igényel — letöltöm egyszer (~150 MB), majd újrapróbálom..."
  # Csak a beepitett Chromiumot toltjuk le (tartaleknak). Ha a gepen mar
  # van Google Chrome, a kod futasidoben AZT hasznalja (channel="chrome",
  # uj headless mod), telepites nelkul - ez kevesbe feltuno. A "python -m"
  # forma az uv "executable not provided by package" figyelmeztetes nelkul.
  uv tool run --from "$FROM_SPEC" python -m playwright install chromium
  echo
  uv tool run --from "$FROM_SPEC" car-tracker scrape-local 2>&1 | tee "$LOG"
  RESULT=${PIPESTATUS[0]}
fi

# --- kemeny blokk eseten: probaljuk a SAJAT Chrome-mal ---
# A 2-3. lepcso egy automata bongeszo, ami igyekszik hetkoznapinak latszani.
# Ez itt egy hetkoznapi bongeszo: te inditod, te bongeszel benne, es amit
# egyszer megoldasz (human-check), az a profilban marad a kovetkezo futasra.
# Sajat user-data-dir kell hozza: a Chrome 136 ota nem enged tavoli
# debuggolast az alapertelmezett profilon.
CHROME_APP="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_PROFILE="$HOME/.cache/car-tracker/chrome-cdp-profile"
if [ "$RESULT" -ne 0 ] && grep -q "hard block page" "$LOG" 2>/dev/null && [ -x "$CHROME_APP" ]; then
  # MELYIK oldal blokkolt? A futas a blokkolo oldalt elmenti
  # "last-blocked-<host>.html" neven, es ezt kiirja - ez a legmegbizhatobb
  # jel. Enelkul a szkript mindig a Hasznaltauto-t nyitotta meg, akkor is,
  # amikor a Tesla blokkolt: a felhasznalo betoltott egy magyar oldalt,
  # aztan a scrape a tesla.com-ot probalta rajta keresztul - es persze
  # ugyanugy blokkba futott. Rossz oldalt megoldani nem segit semmit.
  BLOCKED_HOST="$(grep -oE 'last-blocked-[A-Za-z0-9.-]+\.html' "$LOG" 2>/dev/null | head -n1 | sed -E 's/^last-blocked-//; s/\.html$//')"
  case "$BLOCKED_HOST" in
    *tesla*)         CDP_URL="https://www.tesla.com/de_DE/inventory/used/my"; CDP_SOURCE="tesla" ;;
    *hasznaltauto*)  CDP_URL="https://www.hasznaltauto.hu/szemelyauto/tesla/model_y"; CDP_SOURCE="hasznaltauto" ;;
    *)               CDP_URL="https://www.hasznaltauto.hu/szemelyauto/tesla/model_y"; CDP_SOURCE="" ;;
  esac
  echo
  echo "Egy oldal az automata böngészőt is elutasította (kemény blokk):"
  echo "  ${BLOCKED_HOST:-ismeretlen oldal}"
  echo "Megpróbálhatjuk a saját Chrome-oddal: megnyílik egy külön Chrome-ablak,"
  echo "abban kézzel betöltöd EZT az oldalt (és megoldod a human-checket, ha kér),"
  echo "utána a scrape ugyanazt az ablakot használja."
  read -r -p "Kipróbáljuk? (i/n): " TRY_CDP
  if [ "$TRY_CDP" = "i" ] || [ "$TRY_CDP" = "I" ]; then
    mkdir -p "$CHROME_PROFILE"
    "$CHROME_APP" --remote-debugging-port=9222 --user-data-dir="$CHROME_PROFILE" "$CDP_URL" >/dev/null 2>&1 &
    echo
    echo "Megnyílt egy Chrome-ablak ezen: $CDP_URL"
    echo "  - ha human-checket kér, oldd meg;"
    echo "  - ha ott is 'Sorry, you have been blocked' jön, akkor a hálózatodat"
    echo "    tiltja a site, ezen a scraper nem tud segíteni (pár nap múlva feloldódik)."
    read -r -p "Ha kész az oldal, nyomj Entert (a Chrome-ablakot hagyd nyitva)..." _
    export CAR_TRACKER_CHROME_CDP=http://localhost:9222
    # Csak azt a forrast probaljuk ujra, amelyik blokkolt. Enelkul az
    # ujraprobalas mindent ujraszedett - azt is, ami az elobb sikerult, es
    # a hatszaz magyar oldalt is, amit epp most toltottunk le.
    RETRY_LOG="$SCRIPT_DIR/scrape-local-retry.log"
    if [ -n "$CDP_SOURCE" ]; then
      uv tool run --from "$FROM_SPEC" car-tracker scrape-local --source "$CDP_SOURCE" 2>&1 | tee "$RETRY_LOG"
      RESULT=${PIPESTATUS[0]}
      # Az ujraprobalas CSAK a blokkolt forrast futtatta. Ha a fo futasban
      # MASIK forras is hibazott, a sikeres ujraprobalas nem mondhatja,
      # hogy "minden forras lefutott" - az a hiba meg mindig ott van.
      if [ "$RESULT" -eq 0 ] && grep "^FAILED" "$LOG" 2>/dev/null | grep -qv "FAILED $CDP_SOURCE/"; then
        echo
        echo "A blokkolt forrás ($CDP_SOURCE) most lefutott, de a fő futásban"
        echo "másik forrás is hibázott — annak a hibája továbbra is áll:"
        grep "^FAILED" "$LOG" | grep -v "FAILED $CDP_SOURCE/" | head -5
        RESULT=1
      fi
    else
      uv tool run --from "$FROM_SPEC" car-tracker scrape-local 2>&1 | tee "$RETRY_LOG"
      RESULT=${PIPESTATUS[0]}
    fi
    echo
    echo "A Chrome-ablakot most már bezárhatod (távoli debuggolással fut,"
    echo "ne hagyd nyitva feleslegesen)."
  fi
fi

echo
if [ "$RESULT" -eq 0 ]; then
  echo "KÉSZ — minden forrás lefutott. A dashboard a következő napi"
  echo 'frissítéskor mutatja az új adatot (vagy indítsd el kézzel a'
  echo 'GitHub Actions "Run workflow" gombjával).'
else
  echo "Legalább egy forrás hibával végződött — a részletek fentebb."
  echo "Ami sikerült, az így is elmentődött."
fi

# --- napi automatikus futtatás felajánlása (csak kézi indításkor) ---
if [ "${1:-}" != "auto" ]; then
  # 07:30, nem 07:00: a GitHub-futas 05:00 UTC-kor indul, ami nyari
  # idoszamitasban pont 07:00 nalunk - ket futas ugyanabba az adatbazisba
  # ugyanabban a percben. Fel ora keses ezt megszunteti.
  CRON_LINE="30 7 * * * /usr/bin/env bash \"$SCRIPT_DIR/$(basename "$0")\" auto >> \"$SCRIPT_DIR/scrape-local.log\" 2>&1"
  if ! crontab -l 2>/dev/null | grep -F "$(basename "$0")" >/dev/null; then
    echo
    read -r -p "Fusson ezentúl minden nap automatikusan 07:30-kor? (i/n): " SCHED
    if [ "$SCHED" = "i" ] || [ "$SCHED" = "I" ]; then
      (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
      echo "Beállítva (cron). Megnézés: crontab -l · törlés: crontab -e"
      if [ "$(uname)" = "Darwin" ]; then
        echo "macOS megjegyzés: ha a gép alszik 07:30-kor, a futás kimarad —"
        echo "a következő kézi vagy másnapi futás pótolja, adat nem vész el."
      fi
    fi
  fi
  read -r -p "Nyomj Entert a bezáráshoz..." _
fi

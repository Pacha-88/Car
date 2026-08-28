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
CONFIG="$SCRIPT_DIR/car-tracker-database-url.txt"
REPO="git+https://github.com/Pacha-88/Car"

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
echo
echo "Scrape indul... (első alkalommal 1-2 perc a letöltés, utána gyorsabb)"
uv tool run --refresh --from "$REPO" car-tracker scrape-local
RESULT=$?

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
  CRON_LINE="0 7 * * * /usr/bin/env bash \"$SCRIPT_DIR/$(basename "$0")\" auto >> \"$SCRIPT_DIR/scrape-local.log\" 2>&1"
  if ! crontab -l 2>/dev/null | grep -F "$(basename "$0")" >/dev/null; then
    echo
    read -r -p "Fusson ezentúl minden nap automatikusan 07:00-kor? (i/n): " SCHED
    if [ "$SCHED" = "i" ] || [ "$SCHED" = "I" ]; then
      (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
      echo "Beállítva (cron). Megnézés: crontab -l · törlés: crontab -e"
      if [ "$(uname)" = "Darwin" ]; then
        echo "macOS megjegyzés: ha a gép alszik 07:00-kor, a futás kimarad —"
        echo "a következő kézi vagy másnapi futás pótolja, adat nem vész el."
      fi
    fi
  fi
  read -r -p "Nyomj Entert a bezáráshoz..." _
fi

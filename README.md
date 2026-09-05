# Tuskometr

Tuskometr monitoruje transmisję na żywo, wykonuje lokalną transkrypcję po polsku i pokazuje na publicznym dashboardzie wystąpienia odmienionego nazwiska „Tusk”.

## Architektura

- `frontend/`: React 19, TypeScript, Vite, shadcn/ui, Tailwind CSS i Recharts.
- `backend/app/snapshot.py`: obliczanie statystyk.
- `backend/app/publisher.py`: okresowa publikacja statycznych JSON-ów.
- `deploy/Caddyfile.web`: frontend i JSON-y, bez dostępu do bazy i procesu Python.
- `backend/app/worker.py`: `yt-dlp` → FFmpeg → `faster-whisper` → detekcja → SQLite.
- SQLite z WAL przechowuje pełne transkrypcje przez 30 dni i wykryte wystąpienia bezterminowo.
- Zewnętrzny Caddy terminuję HTTPS i przekazuje ruch do statycznego serwera web.

Surowe audio jest przetwarzane w pamięci i nie jest przechowywane. Źródło YouTube
jest wydzielonym adapterem eksperymentalnym; można je zastąpić bezpośrednim
HLS/SRT/RTMP.

## Cloudflare Pages + R2

Frontend można wdrożyć na Pages, a publiczne dane publikować z VPS-a do R2.
Publisher wysyła niezmienione fragmenty historii tylko raz i przełącza manifest
po zapisaniu kompletnej wersji. VPS nie musi wtedy obsługiwać ruchu odwiedzających.
[Instrukcja konfiguracji Pages, R2, CORS i VPS-a](deploy/cloudflare-pages-r2.md).

## Backup poza VPS-em i odtwarzanie

Opcjonalna nakładka `docker-compose.backup.yml` włącza szyfrowany backup SQLite
przez restic do prywatnego S3/R2, z retencją i odtwarzaniem do osobnego pliku
lub głównej bazy podczas przerwy technicznej. Bez nakładki kopie pozostają lokalne.
[Konfiguracja, test odtwarzania i odzyskanie po utracie VPS-a](deploy/sqlite-backups.md).

## Uruchomienie przez Docker Compose

Wymagania: Docker z Compose, co najmniej 8 GB RAM i zalecane 4 vCPU dla modelu `small/int8`.

```bash
cp .env.example .env
docker compose up --build -d
docker compose logs -f worker
```

Dashboard będzie dostępny pod `https://localhost`. Dla domeny publicznej ustaw w `.env`:

```dotenv
DOMAIN=tuskometr.example.com
```

Pierwsze uruchomienie workera pobiera model Whisper do wolumenu `model-cache`, dlatego może potrwać kilka minut. Stan jest częścią publikowanego dashboardu.

Najważniejsze ustawienia:

| Zmienna | Domyślna wartość | Znaczenie |
| --- | --- | --- |
| `SOURCE_MODE` | `youtube` | `youtube`, `direct` albo lokalny `file` |
| `SOURCE_URL` | transmisja Republiki | URL lub ścieżka pliku |
| `ASR_MODEL` | `small` | Model faster-whisper |
| `ASR_COMPUTE_TYPE` | `int8` | Kwantyzacja dla CPU |
| `ASR_CPU_THREADS` | `4` | Liczba wątków inferencji |
| `CHUNK_SECONDS` | `25` | Długość okna audio |
| `CHUNK_STEP_SECONDS` | `20` | Krok, czyli overlap 5 sekund |

Jeżeli YouTube wymaga zalogowanej sesji, ustaw `YTDLP_COOKIES_FILE` i zamontuj plik cookies do kontenera workera. Nie umieszczaj cookies w repozytorium.

## Wybór transkrypcji: lokalna lub OVH API

Domyślnie `ASR_PROVIDER=local` używa lokalnego Faster Whisper. Aby korzystać
z OVH AI Endpoints, ustaw w `.env`:

```dotenv
ASR_PROVIDER=ovh
ASR_API_KEY=twoj-klucz-ovh
ASR_API_MODEL=whisper-large-v3
```

Można też wybrać `whisper-large-v3-turbo`. Klucz wygeneruj w projekcie Public Cloud,
w sekcji AI Endpoints. Nie umieszczaj go w repozytorium ani kodzie frontendu.
`ASR_API_BASE_URL` domyślnie wskazuje API OVH, a `ASR_API_TIMEOUT_SECONDS=60`
ogranicza czas oczekiwania na odpowiedź.

Po pierwszej aktualizacji kodu zbuduj obraz `docker compose build migrate`.
Po każdej zmianie dostawcy/modelu/klucza odtwórz worker:

```bash
docker compose up -d --no-deps --force-recreate worker
```

W development użyj również `-f docker-compose.yml -f docker-compose.dev.yml`.
Powrót do lokalnego modelu wymaga `ASR_PROVIDER=local` i odtworzenia workera.
Nie jest to przełącznik w publicznym dashboardzie.

W trybie OVH worker wysyła okna audio jako WAV przez HTTPS i odbiera tekst
z czasami słów. Detekcja, baza i dashboard pozostają na VPS. Audio nie jest
zapisywane na dysku. Lokalny model nie jest ładowany, a ustawienia CPU, beam size
i lokalnego fallbacku nie mają zastosowania. Benchmark opisany poniżej nadal
testuje wyłącznie modele lokalne.

Niepewne dopasowania są ponownie transkrybowane przez API na krótkim wycinku,
z podpowiedzią nazwiska przy `ASR_HOTWORDS_VERIFY=true`. To dodatkowe płatne
wywołania. Overlap 25/20 zwiększa ilość przesłanego audio o około 25%.
Prawdopodobieństwo słowa nie jest gwarantowane przez API: brak zapisujemy jako
0 w obecnym polu confidence (nie oznacza to oceny jakości transkrypcji).
Odpowiedź bez wymaganych timestampów jest błędem, zamiast tworzyć niedokładne trafienia.

Błąd lub timeout API przechodzi przez dotychczasowy mechanizm ponownego
łączenia źródła; nie przełącza automatycznie na CPU. Nie ma trwałej kolejki ani
odtwarzania utraconego audio, więc awaria może powodować luki. Nie ponawiamy
automatycznie pojedynczego zapytania, które mogło już zostać rozliczone.

## Statyczny dashboard i Cloudflare

Generator `publisher` odczytuje bazę co 30 sekund (dwa SELECT-y: wystąpienia
z ostatnich 30 dni i status). Publikuje komplet JSON-ów dla zakresów 1, 7 i 30 dni.
Wersja ma unikalny katalog, a mały `/dashboard/manifest.json` jest podmieniany
atomowo dopiero po zapisaniu wszystkich stron i synchronizacji plików na dysku.

Przeglądarka sprawdza manifest co 15 sekund. Jeśli wersja się nie zmieniła,
nie pobiera ponownie statystyk. Nowa wersja aktualizuje ekran bez przeładowania;
w trakcie pobierania poprzednie dane pozostają widoczne. Paginacja jest przypisana
do wersji, więc nie miesza publikacji. Nowa wersja resetuje listę do pierwszej
strony. Nie ma SSE ani publicznego dynamicznego API.

- Manifest: `Cache-Control: public, max-age=5, must-revalidate`.
- `/dashboard/versions/<version>/<days>-<page>.json`: roczny immutable cache.
- Hashowane JS/CSS: roczny immutable cache.
- HTML: no-cache, żeby aktualizacje aplikacji docierały do przeglądarki.
- Brakujące pliki i błędy: no-store, bez zastępowania ich HTML-em aplikacji.

Odczyty HTTP obsługuje Caddy w kontenerze `web`, który ma tylko frontend
i wolumen JSON-ów zamontowany read-only. Nie ma bazy, sekretu OVH ani Pythona.
TLS nadal obsługuje zewnętrzny kontener `caddy`. Restart generatora lub awaria
bazy nie usuwa opublikowanych danych. Po przekroczeniu 120 sekund od ich
wygenerowania dashboard sygnalizuje nieaktualność (także gdy manifest nadal
odpowiada HTTP 200). Worker bez audio przez 120 sekund jest oznaczany offline.

Konfiguracja:
- `DASHBOARD_REFRESH_SECONDS=30`: odstęp między publikacjami.
- `DASHBOARD_MAX_STALE_SECONDS=120`: próg ostrzeżenia w dashboardzie.
- `DASHBOARD_RETENTION_SECONDS=900`: czas zachowania starych wersji na origin.
- `DASHBOARD_OUTPUT_DIR=/snapshots`: katalog generatora uruchamianego samodzielnie.

Retencja usuwa wyłącznie stare wygenerowane wersje, nigdy bieżący manifest
ani dane źródłowe. Pliki JSON mogą nadal znajdować się w cache CDN/przeglądarki.
Koszt dysku zależy od liczby wykryć w 30 dniach oraz liczby zachowanych wersji.
Przy większej historii warto przejść na deduplikowane strony lub agregaty przyrostowe.
Blokada wolumenu zapobiega jednoczesnej publikacji przez dwa generatory.

Oczekiwane dodatkowe opóźnienie od zapisu wykrycia do bazy do odświeżenia
dashboardu: do około 50 sekund (30 generator + 5 cache manifestu + 15 polling),
plus czas obliczeń i pobierania. Nie zależy od liczby otwartych dashboardów.

Cloudflare wymaga [reguły cache](deploy/cloudflare-cache.md) dla JSON.
Pliki są publiczne; cache nie powinien obejmować sekretów ani diagnostyki.
Stare endpointy `/api/*` usunięto; starsza niż 30 dni historia pozostaje w bazie.

## Uruchomienie po aktualizacji

```bash
docker compose up -d --build
```

Compose uruchamia jednorazowo migracje, potem publisher, worker i backup.
Web może działać także przed pierwszą publikacją; frontend poczeka i ponowi
pobieranie manifestu. Nie używaj `down -v` przy aktualizacji — wolumeny zawierają dane.

## Development

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build web publisher worker backup
npm --prefix frontend install
npm --prefix frontend run dev
```

Vite przekazuje `/dashboard` i `/healthz` do Caddy pod `127.0.0.1:8000`.
Zmiana kodu publishera/workera wymaga restartu odpowiedniego kontenera.
Frontend nadal działa z HMR.

### Development na domowym serwerze

Tak jak Tracky, Tuskometr może działać jako usługa użytkownika `systemd`: Vite
z HMR jest dostępny w prywatnej sieci Tailscale pod
`http://100.80.64.94:3003`, a żądania JSON przekazuje do `127.0.0.1:8000`.
Web (wewnętrzny Caddy), publisher, worker i backup działają w Dockerze bez
zewnętrznego proxy TLS. Port web jest dostępny tylko pod 127.0.0.1.

```bash
npm --prefix frontend install
mkdir -p ~/.config/systemd/user
ln -s "$PWD/deploy/systemd/tuskometr-dev.service" \
  ~/.config/systemd/user/tuskometr-dev.service
systemctl --user daemon-reload
systemctl --user enable --now tuskometr-dev.service
```

Logi i status:

```bash
systemctl --user status tuskometr-dev.service
journalctl --user -u tuskometr-dev.service -f
```

Pierwszy start workera pobiera model Whisper do wolumenu Dockera i może przez
kilka minut wykazywać stan `starting`. Zmiana kodu workera wymaga restartu usługi;
frontend i API przeładowują się automatycznie.

## Testy

```bash
.venv/bin/pytest backend/tests
cd frontend && npm run build
```

Przed uruchomieniem 24/7 należy dodatkowo wykonać dwugodzinny benchmark na docelowym VPS-ie. P95 czasu obróbki powinno pozostać poniżej 80% długości audio, a opóźnienie dashboardu należy oceniać z uwzględnieniem publikacji i cache manifestu.

### Izolowany benchmark modeli ASR

Benchmark działa jako jednorazowy kontener bez wystawionych portów, Caddy, API i
produkcyjnej bazy danych. Każdy model otrzymuje dokładnie ten sam materiał i
przechodzi przez produkcyjne okna, detekcję, fuzzy matching oraz weryfikację
hotwords.

Umieść nagranie w `benchmark/samples/`, a następnie uruchom:

```bash
docker compose --profile tools run --build --rm benchmark \
  --audio /samples/test.wav \
  --models base,small,medium \
  --json-only > benchmark/reports/test.json
```

Pierwsze uruchomienie pobierze brakujące modele do istniejącego wolumenu
`model-cache`. Szybki test na początku nagrania można ograniczyć przez
`--max-seconds 300`. Liczbę wątków i parametry okien można nadpisać, np.:

```bash
docker compose --profile tools run --build --rm benchmark \
  --audio /samples/test.wav \
  --models medium \
  --cpu-threads 6 \
  --chunk-seconds 25 \
  --chunk-step-seconds 20 \
  --json-only > benchmark/reports/medium-vps3.json
```

Do pomiaru skuteczności skopiuj `benchmark/samples/truth.example.json`, wpisz
rzeczywiste pozycje wystąpień i dodaj `--truth /samples/truth.json`. Pole `form`
jest opcjonalne; bez niego liczy się dowolna obsługiwana odmiana nazwiska.
Raport zawiera czasy średnie/P50/P95/P99, real-time factor, symulowane
opóźnienie, szczytowe użycie RAM, transkrypcje okien, wykrycia oraz
precision/recall/F1.

## Uwaga dotycząca źródła

Automatyczne wydzielanie audio z publicznej transmisji YouTube może naruszać warunki platformy lub prawa nadawcy. Adapter YouTube powinien być traktowany jako PoC. Do wdrożenia produkcyjnego należy uzyskać zgodę nadawcy i autoryzowany feed.

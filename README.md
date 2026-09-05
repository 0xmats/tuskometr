# Tuskometr

Tuskometr monitoruje transmisję na żywo, wykonuje lokalną transkrypcję po polsku i pokazuje na publicznym dashboardzie wystąpienia odmienionego nazwiska „Tusk”.

## Architektura

- `frontend/`: React 19, TypeScript, Vite, shadcn/ui, Tailwind CSS i Recharts.
- `backend/app/main.py`: FastAPI, REST, SSE i statyczny build dashboardu.
- `backend/app/worker.py`: `yt-dlp` → FFmpeg → `faster-whisper` → detekcja → SQLite.
- SQLite z WAL przechowuje pełne transkrypcje przez 30 dni i wykryte wystąpienia bezterminowo.
- Caddy terminuję HTTPS i przekazuje ruch do FastAPI.

Surowe audio jest przetwarzane w pamięci i nie jest przechowywane. Źródło YouTube
jest wydzielonym adapterem eksperymentalnym; można je zastąpić bezpośrednim
HLS/SRT/RTMP.

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

Pierwsze uruchomienie workera pobiera model Whisper do wolumenu `model-cache`, dlatego może potrwać kilka minut. Stan można sprawdzić przez `GET /api/status`.

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

Po pierwszej aktualizacji kodu zbuduj obraz `docker compose build web`.
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

## Development

Backend:

```bash
python3 -m venv .venv
.venv/bin/pip install -e 'backend[dev]'
DATABASE_URL=sqlite:///./backend/dev.db FRONTEND_DIST=./frontend/dist \
  .venv/bin/uvicorn app.main:app --app-dir backend --reload
```

Worker wymaga dostępnego w `PATH` programu FFmpeg:

```bash
DATABASE_URL=sqlite:///./backend/dev.db SOURCE_MODE=file SOURCE_URL=/ścieżka/test.wav \
  .venv/bin/python -m app.worker
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Vite przekazuje `/api` i `/healthz` do backendu na porcie 8000.

### Development na domowym serwerze

Tak jak Tracky, Tuskometr może działać jako usługa użytkownika `systemd`: Vite
z HMR jest dostępny w prywatnej sieci Tailscale pod
`http://100.80.64.94:3003`, a żądania API przekazuje do `127.0.0.1:8000`.
Backend, worker i backup działają w Dockerze bez Caddy i bez publicznych portów.
Kod backendu jest zamontowany w kontenerze, a Uvicorn automatycznie go przeładowuje.

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

Przed uruchomieniem 24/7 należy dodatkowo wykonać dwugodzinny benchmark na docelowym VPS-ie. P95 czasu obróbki powinno pozostać poniżej 80% długości audio, a opóźnienie dashboardu poniżej 60 sekund.

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

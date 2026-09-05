# Cloudflare Pages + R2

Frontend działa na Pages, publiczne JSON-y w R2 Standard, a VPS wykonuje obliczenia
oraz połączenia wychodzące do R2. Nie są wymagane Workers ani Pages Functions.

## 1. Bucket i domena danych

Utwórz osobny bucket R2 Standard `tuskometr-public`. Podłącz własną domenę,
np. `data.example.com`, w Settings → Custom Domains. Nie używaj `r2.dev` produkcyjnie.
Bucket zawiera wyłącznie publiczne statystyki i cytaty, nigdy bazę ani transkrypcje.
Nie ustawiaj reguły lifecycle usuwającej wszystkie obiekty po określonym czasie:
stare pliki historii mogą nadal należeć do aktualnego dashboardu.

W CORS wklej `deploy/r2-cors.json`, zastępując domeny faktyczną domeną strony
oraz adresem projektu Pages. Dla preview dodaj dokładny origin, jeśli ma działać.
Nagłówki `Date` i `Age` muszą być dostępne dla przeglądarki: służą wykrywaniu
nieaktualnych danych niezależnie od zegara użytkownika.

W Cache Rules ustaw dla domeny danych i ścieżki `/dashboard/*`:
- Eligible for cache (JSON domyślnie nie jest cache'owany).
- Edge TTL: Use cache-control header if present, bypass cache if not.
- Browser TTL: Respect origin.
- Nie nadpisuj TTL i nie cache'uj błędów. Zachowaj ścieżkę w kluczu cache.

Publisher ustawia 5 sekund dla manifestu i rok dla niezmiennych plików.
Po zmianie CORS wyczyść istniejący cache domeny danych.

## 2. VPS: tylko obliczenia i publikacja

Utwórz poświadczenia R2 S3 z prawami Object Read & Write ograniczonymi do tego
bucketu. Access Key ID i Secret Access Key to poświadczenia S3, nie globalny token
Cloudflare. Umieść je wyłącznie w `.env` na VPS-ie:

```dotenv
R2_ENDPOINT_URL=https://ACCOUNT_ID.r2.cloudflarestorage.com
R2_BUCKET=tuskometr-public
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
ASR_PROVIDER=ovh
ASR_API_KEY=...
```

Z repozytorium uruchom:

```bash
docker compose -f docker-compose.yml -f docker-compose.r2.yml up -d --build
```

Nakładka wyłącza domyślne uruchamianie web i Caddy. Jeśli wcześniej działały,
zatrzymaj je przed przejściem (wyłącznie kontenery tego projektu):

```bash
docker compose stop web caddy
```

Nie usuwaj wolumenów. `dashboard-data` przechowuje rejestr wysłanych obiektów;
po restarcie publisher nie wysyła całej historii ponownie. Uruchamiaj tylko jeden
publisher dla danego bucketu, również przy migracji na drugi VPS.
Poświadczenia R2 trafiają tylko do publishera, nie do workera ani frontendu.
Backup bazy domyślnie pozostaje lokalny. Dodaj `docker-compose.backup.yml`, aby
włączyć [szyfrowane kopie do prywatnego bucketu](sqlite-backups.md).

## 3. Cloudflare Pages

Połącz repozytorium w Pages i ustaw:
- Root directory: `frontend`
- Build command: `npm ci && npm run build`
- Build output directory: `dist`
- Build environment: `NODE_VERSION=22`
- Publiczna zmienna builda: `VITE_DATA_ORIGIN=https://data.example.com`

Nie dodawaj do Pages kluczy R2 ani OVH. Zmiana `VITE_DATA_ORIGIN` wymaga nowego
builda. Pages publikuje stronę przy zmianach kodu, nie przy aktualizacji danych.
Można też lokalnie zbudować frontend z tą zmienną i wgrać katalog `frontend/dist`
przez Pages Direct Upload. Nie wgrywaj całego repozytorium.

## 4. Weryfikacja

```bash
curl -sS -D - https://data.example.com/dashboard/manifest.json
curl -sS -D - -H 'Origin: https://tuskometr.example.com' https://data.example.com/dashboard/manifest.json
```

Powtórz w ciągu 5 sekund: oczekuj `CF-Cache-Status: HIT`, nagłówka `Age`,
`Access-Control-Allow-Origin` oraz ekspozycji `Date`/`Age`. Otwórz adres jednego
z dashboardów z manifestu i sprawdź `Pokaż starsze` w aplikacji. Przeglądarka
powinna pobierać dane wyłącznie z domeny R2, bez połączeń z VPS-em.
Zatrzymanie publishera na ponad 120 sekund powinno oznaczyć dane jako nieaktualne.

## Koszt i spójność

Historia jest dzielona według stałych przedziałów ID, a pliki adresowane skrótem
SHA-256 treści. Dodanie cytatu nie przesuwa wszystkich stron. Identyczne fragmenty
są współdzielone między zakresami 1/7/30 dni. Pierwsza strona jest w dashboardzie;
starsze strony nie powielają wykresów i statusu.

Każda publikacja zapisuje zwykle trzy dashboardy i manifest: około 345 600 PUT-ów
na 30 dni przy odświeżaniu co 30 sekund, plus nowe/zmienione fragmenty historii.
Nie wykonujemy HEAD ani LIST dla każdego pliku. Pierwsza publikacja wysyła historię.
Zmiany cytatów i przesuwanie granic zakresów mogą wymagać dodatkowych zapisów.
Darmowy limit jest współdzielony z pozostałym użyciem R2 na koncie.

Manifest przełącza się dopiero po pomyślnym wysłaniu wszystkich plików. Przy błędzie
pozostaje poprzednia kompletna wersja. Co godzinę publisher usuwa nieużywane obiekty
starsze niż 24h; aktualne pliki są chronione również przy błędach kolejnych publikacji.
Długo otwarta stara wersja po retencji może wymagać odświeżenia.
Nie usuwaj obiektów ręcznie: rejestr lokalny zakłada, że nadal istnieją. Po utracie
rejestru ponowna publikacja odtworzy aktualne pliki, ale osierocone obiekty z poprzedniego
rejestru wymagają osobnego sprzątania. W razie usunięcia bucketu odtwórz go i usuń
lokalny rejestr R2 przy zatrzymanym publisherze przed ponowną publikacją.

## Lokalny development

Bez nakładki R2 działa dotychczasowy lokalny publisher i Caddy.
Pozostaw `VITE_DATA_ORIGIN` puste, aby pobierać dane z tego samego origin.

Źródła:
- https://developers.cloudflare.com/pages/framework-guides/deploy-a-vite3-project/
- https://developers.cloudflare.com/r2/buckets/public-buckets/
- https://developers.cloudflare.com/r2/buckets/cors/
- https://developers.cloudflare.com/r2/pricing/

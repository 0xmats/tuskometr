# Cloudflare: statyczny dashboard

Włącz proxy DNS dla domeny Tuskometru. W Caching → Cache Rules dodaj regułę:

```text
(http.host eq "TWOJA-DOMENA" and starts_with(http.request.uri.path, "/dashboard/"))
```

- Cache eligibility: Eligible for cache (JSON nie jest cache'owany domyślnie).
- Edge TTL: respektuj Cache-Control origin, bez nadpisania TTL.
- Browser TTL: respektuj nagłówki origin.
- Zachowaj ścieżkę w kluczu cache — każda wersja ma inny URL.
- Nie dodawaj cache błędów ani reguły ignorującej no-store.

Manifest ma TTL 5 sekund i must-revalidate. JSON-y pod /dashboard/versions/
oraz hashowane /assets/ mają roczny immutable cache. HTML wymaga rewalidacji.
Nie ustawiaj jednego długiego TTL dla całego /dashboard/ — zatrzymałoby to
aktualizacje manifestu. Nie cache'uj /healthz.

Weryfikacja po wdrożeniu:

```bash
curl -sS -D - 'https://TWOJA-DOMENA/dashboard/manifest.json'
```

Powtórz w ciągu 5 sekund: oczekiwany CF-Cache-Status HIT i nagłówek Age.
Pobierz URL z pola dashboards: powinien mieć roczny immutable Cache-Control,
ETag i poprawny JSON. Nieistniejący plik wersji powinien mieć 404 i no-store,
nigdy index.html ani długo cache'owany błąd.

Przy przejściu ze starego API usuń poprzednią regułę /api/*. Przy zmianie schematu
manifestu wyczyść jego cache. Pliki wersjonowane nigdy nie są nadpisywane.

Reguła Cloudflare wymaga ustawienia w panelu; Compose konfiguruje wyłącznie origin.

Dokumentacja:
- https://developers.cloudflare.com/cache/concepts/default-cache-behavior/
- https://developers.cloudflare.com/cache/how-to/cache-rules/settings/

# SQLite: szyfrowany backup poza VPS-em i odtwarzanie

Tak jak w Athleo używamy restic i prywatnego storage S3/R2. Zostajemy przy SQLite.
Kopia powstaje przez SQLite Backup API, uwzględnia zatwierdzone dane z WAL i jest
sprawdzana przez `integrity_check` oraz `foreign_key_check`. Dopiero gotowy plik
trafia do szyfrowanego repozytorium. Nie kopiujemy bezpośrednio aktywnego pliku `.db`.

## Konfiguracja

1. Utwórz **osobny, prywatny** bucket R2 Standard, np. `tuskometr-backups`.
   Bez publicznej domeny, `r2.dev` i reguł lifecycle kasujących pliki repozytorium.
   Nie używaj publicznego bucketu dashboardu.
2. Utwórz osobny token S3 Object Read & Write ograniczony do bucketu backupów.
3. Skopiuj `deploy/backup.env.example` do `deploy/backup.env`, uzupełnij endpoint,
   klucze S3 i silne, losowe `RESTIC_PASSWORD`. Zapisz hasło w menedżerze haseł
   poza VPS-em: jego utrata uniemożliwia odtworzenie backupów.
   Ustaw `chmod 600 deploy/backup.env`.
4. Używaj stałego `BACKUP_RESTIC_HOST`, również po wymianie VPS-a. Dla stagingu
   wybierz osobny host i osobny prefix repozytorium.

Z katalogu repozytorium ustaw zestaw plików Compose dla wszystkich poleceń:

```bash
# Frontend i dane na Cloudflare:
export COMPOSE_FILE=docker-compose.yml:docker-compose.r2.yml:docker-compose.backup.yml
# Alternatywnie lokalne serwowanie strony:
# export COMPOSE_FILE=docker-compose.yml:docker-compose.backup.yml

docker compose build migrate
docker compose run --rm --no-deps backup python -m app.backup init
docker compose up -d
```

`init` uruchom tylko raz dla nowego repozytorium. Błąd połączenia lub hasła nie
powoduje automatycznej inicjalizacji nowego repozytorium. Na istniejącym wdrożeniu
po zmianie konfiguracji odtwórz kontener `docker compose up -d --force-recreate backup`.
Sekrety backupu otrzymuje tylko kontener backupu, nie frontend, worker czy publisher.
Możesz wskazać plik spoza repo przez `TUSKOMETR_BACKUP_ENV_FILE=/opt/tuskometr/backup.env`.

Bez nakładki `docker-compose.backup.yml` nadal działa dotychczasowy backup lokalny.

## Operacje

```bash
# Jednorazowa kopia lokalna + zaszyfrowana kopia zewnętrzna:
docker compose run --rm --no-deps backup python -m app.backup once
# Lista punktów odtwarzania dla tego projektu/hosta:
docker compose run --rm --no-deps backup python -m app.backup list
# Pełne sprawdzenie repozytorium, łącznie z odczytem danych:
docker compose run --rm --no-deps backup python -m app.backup check
# Próbne odtworzenie do nowego pliku w wolumenie backup-data:
./scripts/restore-sqlite.sh latest test
```

Lista pokazuje identyfikatory snapshotów. Zamiast `latest` możesz podać konkretny ID.
Próbne odtworzenie nie zatrzymuje aplikacji ani nie nadpisuje działającej bazy.
Weryfikuje integralność i obecność tabel Tuskometru; warto dodatkowo obejrzeć dane
w odzyskanym pliku. Pliki próbnego odtwarzania `restore-*.db` pozostają do inspekcji;
usuwaj je po sprawdzeniu, nie podlegają automatycznej retencji lokalnych snapshotów.

Daemon robi kopię przy starcie i codziennie o 03:30 UTC. Po błędzie ponawia próbę
za pięć minut; nie udaje sukcesu, gdy upload się nie powiedzie. Lokalnie zachowuje
7 kopii, a restic zachowuje ostatnie 10 oraz 14 dziennych i 8 tygodniowych.
Retencja restic uruchamia się wyłącznie po udanej kopii, z filtrem projektu i hosta.
Nie ustawiaj wartości retencji na zero. Obserwuj `docker compose logs backup`;
nie ma jeszcze zewnętrznych powiadomień o błędach.

## Zastąpienie głównej bazy

To operacja przywracająca dane do wybranego punktu w czasie. Uruchom ją świadomie
z katalogu wdrożenia i tym samym `COMPOSE_FILE`/nazwą projektu. Najpierw wykonaj test.

```bash
./scripts/restore-sqlite.sh SNAPSHOT_ID --main
```

Skrypt najpierw pobiera i sprawdza kandydat, potem zatrzymuje `worker`, `publisher`
i `backup`, sprawdza stan usług, tworzy kopię dotychczasowej bazy w
`/backups/before-restore`, podmienia plik, uruchamia migracje i wznawia usługi.
Jeżeli obecna baza jest uszkodzona, zachowywane są jej surowe pliki wraz z WAL
w podkatalogu `before-restore/raw-*`; te kopie usuwa się ręcznie po diagnostyce.
Nie może wtedy działać inny ręcznie uruchomiony proces czy drugi projekt Compose
korzystający z tej bazy. Nie uruchamiaj równoległych poleceń backup/restore/deploy.
W razie błędu po zatrzymaniu usług skrypt pozostawia je zatrzymane do wyjaśnienia
problemu. Kopia sprzed operacji pozostaje dostępna w wolumenie backup-data.
Nie wywołuj ręcznie `activate --offline` przy działających czytelnikach/pisarzach SQLite.

Publisher wygeneruje nowy dashboard. Poprzedni może być widoczny do czasu publikacji
nowego manifestu i wygaśnięcia krótkiego cache. Nie odtwarzamy starych JSON-ów.

## Odtworzenie po utracie VPS-a

1. Odtwórz repozytorium kodu, `.env` i `backup.env` z menedżera haseł; zachowaj
   endpoint/prefix repozytorium, hasło i `BACKUP_RESTIC_HOST`.
2. Zbuduj obrazy, ale jeszcze nie uruchamiaj workera/publishera. **Nie wykonuj init**.
3. Ustaw `COMPOSE_FILE`, uruchom `list`, próbny restore, a potem restore `--main`.
   Skrypt utworzy bazę w nowym wolumenie i wykona migracje.
4. Sprawdź logi i aktualizację dashboardu. Uruchom web/Caddy, jeśli ich używasz.

Backup zawiera całą główną bazę: wykrycia, przechowywane transkrypcje, sesje i status.
Nie zawiera sekretów, modeli ASR, plików aplikacji ani rejestru publishera R2.
Rejestr R2 po utracie jest odbudowywany przez ponowną publikację; osierocone stare
JSON-y mogą wymagać osobnego sprzątania (patrz instrukcja Pages/R2).
Usunięte z żywej bazy transkrypcje mogą nadal istnieć w starszych backupach aż do
wygaśnięcia retencji restic.

Źródła:
- https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html
- https://restic.readthedocs.io/en/stable/040_backup.html
- https://restic.readthedocs.io/en/stable/050_restore.html

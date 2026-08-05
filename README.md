# HORECA SNACKYOU — agent casă de marcat

Program mic care rulează pe **PC-ul din local** (cel cu UnityPOS) și trimite
bonurile în cloud non-stop. Citește UnityPOS **local** (root@localhost) și
împinge datele în cloud prin **internet (HTTPS)** — nu deschide niciun port,
nu depinde de aceeași rețea ca telefonul.

## De ce e mai bun decât varianta cu Mac-ul

- **Nu mai contează WiFi-ul** — agentul vorbește cu cloud-ul prin internet, ca telefonul.
- **Rămâne conectat tot timpul** — pornește automat cu Windows.
- **Fără probleme de IP/GRANT** — `root@localhost` merge mereu; schimbarea IP-ului nu-l mai rupe.

Limită: când PC-ul e oprit (noaptea), nu curg bonuri noi (normal). Istoricul
rămâne în cloud, accesibil de pe telefon 24/7.

## Cum obții `horeca-snackyou.exe`

Executabilul se construiește pe Windows (nu se poate pe Mac). Două căi:

- **A. GitHub Actions (recomandat, fără să instalezi nimic):** la push, workflow-ul
  `build-horeca-agent.yml` îl construiește în cloud și îl publică ca artifact
  descărcabil (`horeca-snackyou-exe`). Descarci `.exe`-ul gata făcut.
  - **Atenție la descărcare:** artifactul vine ca `.zip` → **dezarhivează-l întâi**
    (click-dreapta → „Extract All”), apoi rulează `.exe`-ul din folderul extras.
  - **SmartScreen la prima rulare:** fiind un exe nesemnat, Windows afișează „Windows
    protected your PC”. Apasă **„More info” → „Run anyway”** (e normal pentru un
    program făcut de tine, nu descărcat de pe internet).
- **B. Local, pe PC-ul cu UnityPOS:** instalezi Python 3.10+ (bifează „Add to PATH”),
  apoi dublu-click pe `build.bat`. Rezultatul: `dist\horeca-snackyou.exe`.

## Cum îl folosești (pe PC-ul cu UnityPOS)

1. Copiază `horeca-snackyou.exe` într-un folder (ex: `C:\HorecaSnackYou\`).
2. Dublu-click pe el → pornește **configurarea ghidată**:
   - se conectează la UnityPOS local (cere parola MySQL dacă e nevoie);
   - cere un **cod de conectare** din aplicație (Setări → Conexiune POS →
     „Generează cod”), forma `SNK-XXXX-XXXX`;
   - întreabă dacă pornește automat cu Windows (da).
3. Gata — lasă fereastra deschisă. Sincronizează singur.

## Comenzi (din CMD, opțional)

```
horeca-snackyou.exe            configurare (prima dată) apoi pornire
horeca-snackyou.exe setup      reconfigurează
horeca-snackyou.exe run        pornește sync-ul continuu
horeca-snackyou.exe status     arată starea (cursor, coadă, erori)
horeca-snackyou.exe install    pornire automată cu Windows
horeca-snackyou.exe uninstall  dezactivează pornirea automată
```

## Fișiere lângă exe

- `horeca-snackyou.config.json` — configurarea (cloud, token, parolă UnityPOS). **Nu-l trimite nimănui.**
- `horeca-snackyou.state.db` — cursor + coadă locală (rezistă la restart).

## Cum funcționează (tehnic)

Citește `bonuri`/`vanzari` din UnityPOS (SQL identic cu sync-ul dovedit al
backend-ului) și le trimite la `POST /pos/sync` cu antet `X-POS-Token`. Coadă
durabilă SQLite cu cursor dublu (read/synced), retry cu backoff, dead-letter la
erori de validare. Idempotent pe `(tenant_id, cod_unitypos)` → zero duplicate,
chiar dacă retrimite. Token opac, revocabil din aplicație.

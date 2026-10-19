# Diagnostic țintit Z 1.2 / installer 1.0.7
- Utilizează configurația existentă; nu o scrie și nu schimbă starea agentului.
- SELECT parametrizat, doar 3 tabele confirmate în schema reală: ultimele 50 poziții registru, 10 registre, 20 sesiuni. Fără date angajați sau tabele autentificare.
- Identifică locația POS din procese, scurtături Desktop/Start Menu și registrul aplicațiilor instalate; nu execută țintele scurtăturilor.
- Scanare limitată; doar documente text cu nume fiscal/Z pot produce fragmente, maximum 5 x 16KiB, doar când conținutul are marker raport Z. Redactează credențiale uzuale. Nicio transmitere automată.
- Raportul diferențiază indicii, lipsa datelor și sursa fiscală verificată (rămâne false până la validare).
- Teste locale sintetice plus build/test reinstalare Windows. Config și SQLite rămân byte-for-byte identice la upgrade.

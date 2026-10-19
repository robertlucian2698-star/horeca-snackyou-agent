# Arhiva UnityPOS — mostre automate 1.0.9

Scop: verificarea conținutului rapoartelor zilnice găsite, fără a cere căutări/exporturi manuale. Fișierele candidate nu sunt declarate Z fiscal până la verificare.

- Refolosește discovery și POST /pos/diagnostics existent; nicio schimbare a endpointurilor de bonuri sau a configurației.
- Inspectează doar subfolderul rapoarte_zilnice din instalările descoperite (sau acel folder dacă este rădăcina descoperită), fără recursie/junction/symlink. Nu scanează documentele personale.
- Enumerare separată de limita de200fișiere a diagnosticului general: cel mult10000intrări și3secunde per arhivă. Alege cele mai recente două rapoarte după data din nume, nu după ordinea lexicografică.
- Citește PDF doar pentru nume raport_zilnic-N-YYYY-MM-DD.pdf, vechi de minimum60secunde, maximum64KiB/document; maximum2documente în total. Verifică antet PDF, stabilitate și SHA256; include base64 plus metadate. Fără execuție de PDF sau conținut POS.
- Raportul păstrează limită250KiB; dacă este prea mare reduce schema/metadatele înainte de mostre. Trunchierea/erorile sunt explicite. Document prea mare nu blochează bonurile.
- Versiunea colectorului declanșează un diagnostic nou după upgrade, chiar dacă ultimul a fost trimis acum mai puțin de6ore. Outbox vechi este trimis înainte de colectarea celui nou.
- Teste sintetice: selectare recentă peste200fișiere, symlink/junction, fișier mare/instabil/nonPDF, limite, retry și upgrade, păstrarea config/coadă. BuildWindows și test reinstalare înainte de livrare.
- Nu modificăm live backend/frontend: contractul JSON existent acceptă mostrele. Mostrele vor putea fi analizate după pornirea noului agent; nu afirmăm validare POS înainte de primire.

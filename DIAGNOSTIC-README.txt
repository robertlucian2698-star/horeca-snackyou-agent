SNACKYOU - INSTALARE DIAGNOSTIC AUTOMAT 1.1
Windows 10/11 Intel/AMD 64 biti. Nu necesita Python instalat sau drepturi admin.

1. Copiaza ZIP pe Desktop-ul calculatorului casei.
2. Click dreapta > Extract All / Extragere totala.
3. Deschide folderul extras si dublu click INSTALEAZA-DIAGNOSTIC.cmd.
4. Lasa agentul si UnityPOS pornite. Configuratia se cauta automat in
   instalarea standard, langa diagnosticul integrat si langa agentul activ.
   Daca exista mai multe configuratii, alege doar numarul celei dorite.
5. La final Explorer selecteaza fisierul diagnostic-z-....json. Trimite-l aici.
   Daca nu gaseste configuratia sau sursa POS, trimite tot raportul rezultat.
   Nu copia si nu trimite configuratia agentului.

Acest pachet instaleaza NUMAI diagnosticul separat sub
%LOCALAPPDATA%/SnackYouDiagnostic/diagnostic-1.1-... si il ruleaza.
NU inlocuieste agentul de bonuri, NU opreste procese, NU schimba startup,
NU modifica baza sau configuratia existenta. Reinstalarea creeaza un folder nou.
Nu reprezinta inca noul installer complet horeca-snackyou-setup.exe.

Cauta folderul UnityPOS din procesele active si locatiile standard.
Daca instalarea e particularizata si nu e detectata, raportul spune explicit.
Citeste schema MySQL, nu randuri business. Enumera metadate de fisiere,
nu continutul lor. Fara upload; tokenul si parolele nu se includ in raport.
Numele relative de fisiere/tabele pot fi comerciale; trimite raportul privat.
Nu emite raport fiscal sau inchidere de zi. Candidatele nu confirma sursa Z.

Limite: maximum 10001 coloane schema, 3 foldere POS, 5000 intrari/200 rezultate
si circa 10 secunde per folder; timeout de conexiune 5s, citire 8s.
Daca Windows blocheaza pornirea, nu dezactiva protectiile: trimite mesajul.
Testat local pe date sintetice; rularea reala Windows/MySQL ramane de verificat.

Python 3.13.16 embedded oficial, licenta runtime/LICENSE.txt:
https://www.python.org/downloads/release/python-31316/
PyMySQL 1.2.0: licenta PyMySQL-LICENSE.txt.

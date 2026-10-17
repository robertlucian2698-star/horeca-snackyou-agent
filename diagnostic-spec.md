# Diagnostic automat Z — contract 1.1
- Un click instalează componenta separată și pornește diagnosticul; fără oprirea agentului.
- Detectare config din folderul executabilului, LOCALAPPDATA/APPDATA HorecaSnackYou și calea agentului activ; o singură configurație este aleasă automat. Mai multe cer număr; niciuna produce raport explicit, fără cerere de cale.
- Detectare folder POS din executabil UnityPOS activ sau locații standard, scanare bounded.
- Metadate numai, fără secrete/rânduri business/upload. Nu se ating config/state/executabilul agentului, startup sau servicii.
- Raport JSON salvat, selectat în Explorer. Absența sursei este rezultat de diagnostic, nu dovadă că nu există Z.
- Installer principal include executabil separat și opțiune/scurtătură diagnostic; pachetul complementar CMD poate fi livrat fără rebuild agent.
- Verificare: teste sintetice pentru autodetect, ambiguitate, absență, redactare, scanare limitată și păstrarea agentului. Probe Windows/POS reale încă necesare.

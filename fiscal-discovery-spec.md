# Descoperire fiscală UnityPrinter

Reper validat de fotografie: raport zilnic UnityPOS501 are aceleași sume ca Z0507/18oct2026: cash731/card641/total1372. Numerele nu sunt interschimbabile. Reperul nu este hardcodat în agent.

Colector read-only în workerul existent, versiune nouă. Pleacă exclusiv din directoare UnityPrinter descoperite sau subfolder printer/UnityPrinter al UnityPOS. Citește numai câmpuri whitelist din data.xml: cm,driver,com,baudrate,driver_path,bf_path,bf_name,bf_answer,printer_path. Fără alte valori/configuri/secrete; respinge DTD/entity, UNC, rădăcini disc, symlink/junction, pathuri cu userinfo. Căile către executabile se transformă în directoare, fără execuție.

Inspectează până la6directoare referite, max2000intrări/3sec/depth2 fiecare; inventar max80fișiere relevante/root. Scanează maximum20fișiere text recente/global (.txt/.log/.csv/.xml/.jrn), head+tail bounded32KiB, fără fișiereconfig/cred/SQL/surse/binare. Extrage max3fragmente globale,2048caractere, numai în jurul marcajelor explicite raport fiscal zilnic / Z nr / raport Z. Redactează chei credentiale. Păstrează truncarea/erorile, nume,tip,size,mtime, nu declarăfiscalZconfirmat automat.

Nu lansează driver, nu trimitecomenzi, nu deschideCOM, nu modificăPOS/config/cursor. Erorile colectorului nu împiedicădiagnosticulgeneral sau bonurile. Compatibilitate cuPOSTdiagnostics existent; limitepayloadverificate. Teste exclusivsintetice Windows/path/file/credential/redaction/bounds și integrareworker. PCreal necesar pentru rezultatul final.

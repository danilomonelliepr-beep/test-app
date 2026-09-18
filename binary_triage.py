"""
═══════════════════════════════════════════════════════════════════════════
ESAME DI UN ESEGUIBILE — quando il sorgente è andato perso.

Non è un decompilatore: è quello che si può dire di un binario **senza**
decompilarlo, e serve a due cose. La prima è capire subito in che caso si è,
perché il caso cambia tutto:

  · .NET (VB.NET, C#) e Java → i nomi di classi, metodi e proprietà sono
    DENTRO il file. Un decompilatore (ILSpy, dnSpy, CFR) restituisce codice
    quasi identico all'originale, spesso ricompilabile. È recupero, non
    ricostruzione.
  · Python impacchettato (PyInstaller) → si estrae e si decompila il bytecode:
    buono fino a Python 3.8, più incerto dopo.
  · VB6 in p-code → si recupera parecchio, form comprese.
  · Nativo (C, C++, Delphi, VB6 nativo) → Ghidra o IDA danno C
    FUNZIONALMENTE EQUIVALENTE: niente nomi veri, niente commenti, strutture
    indovinate. Serve a capire cosa fa, non a ricompilare. Con il file `.pdb`
    dei simboli la qualità fa un salto.

La seconda è che, anche senza decompilare, un binario dice già molto: contro
quali librerie è linkato (una `OCI.dll` vuol dire Oracle), che stringhe
contiene — query SQL, percorsi, messaggi, connection string — quando è stato
costruito, che risorse si porta dentro.

Il resoconto che esce di qui è TESTO, e come tutto il resto può essere dato in
pasto all'estrattore. Ma è testo di natura diversa dal sorgente, e va detto:
vedi `provenienza` in `app.py`.

── USO ───────────────────────────────────────────────────────────────────
    python binary_triage.py PROGRAMMA.EXE
    python binary_triage.py PROGRAMMA.EXE --stringhe 400
Da codice:
    from binary_triage import esamina, resoconto
    dati = esamina(percorso_o_bytes, nome="PROGRAMMA.EXE")
    print(resoconto(dati))

Non richiede niente oltre alla libreria standard. Se `pefile` è installato si
usa per gli import di Windows, altrimenti si legge l'intestazione a mano.
═══════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

__version__ = "2026.09.18g"

import re
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# =============================================================================
# CHE COSA È QUESTO FILE
# =============================================================================
FIRME = [
    (b"MZ", "PE", "eseguibile o libreria Windows"),
    (b"\x7fELF", "ELF", "eseguibile Linux/Unix"),
    (b"\xca\xfe\xba\xbe", "CLASS", "classe Java compilata"),
    (b"PK\x03\x04", "ZIP", "archivio (jar, war, apk, o installatore)"),
    (b"\xcf\xfa\xed\xfe", "MACHO", "eseguibile macOS"),
    (b"\xfe\xed\xfa\xce", "MACHO", "eseguibile macOS"),
]

# Come si riconosce chi l'ha prodotto, e quindi che strada prendere.
# Come si riconosce chi l'ha prodotto, e quindi che strada prendere.
# `minimo` = quante firme devono combaciare, `formati` = su quali file vale.
# Non è pedanteria: parole come «Borland» o «System.Classes» compaiono dentro
# binari che con Delphi non c'entrano niente — `objdump` su Linux veniva
# riconosciuto come Delphi perché conosce i formati Borland. Una diagnosi
# sbagliata qui manda a usare lo strumento sbagliato per mezza giornata.
INDIZI = [
    ("NET", "Codice gestito .NET (VB.NET o C#)",
     [b"mscoree.dll", b"_CorExeMain", b"BSJB", b"System.Runtime", b"mscorlib"], 1, ("PE",),
     "I nomi di classi, metodi e proprietà sono nel file. ILSpy o dnSpy "
     "restituiscono VB.NET o C# molto vicino all'originale, spesso "
     "ricompilabile: si perdono i commenti e i nomi delle variabili locali."),
    ("JAVA", "Codice Java",
     [b"META-INF/MANIFEST.MF", b"java/lang/Object", b".class"], 1, ("CLASS", "ZIP"),
     "Stessa situazione del .NET: CFR o Procyon danno codice molto vicino "
     "all'originale."),
    ("PYINSTALLER", "Python impacchettato con PyInstaller",
     [b"PyInstaller", b"_MEIPASS", b"pyi-runtime-tmpdir", b"pyimod"], 1, ("PE", "ELF", "MACHO"),
     "Si estrae con pyinstxtractor e si decompila il bytecode: affidabile "
     "fino a Python 3.8, più incerto sulle versioni recenti."),
    ("VB6", "Visual Basic 6",
     [b"MSVBVM60.DLL", b"MSVBVM50.DLL", b"VB5!"], 1, ("PE",),
     "Se compilato in p-code si recupera parecchio, form comprese "
     "(VB Decompiler). Se compilato in nativo, molto meno."),
    ("DELPHI", "Delphi o C++ Builder",
     [b"TApplication", b"Embarcadero", b"Borland", b"System.Classes",
      b"TForm", b"Vcl.Forms", b"SOFTWARE\\Borland"], 3, ("PE",),
     "IDR o DeDe ricostruiscono bene le form e parte della struttura."),
    ("DOTNET_SINGLE", "Eseguibile .NET autonomo (single-file)",
     [b"DOTNET_BUNDLE", b"hostfxr", b"hostpolicy"], 2, ("PE", "ELF"),
     "Va prima estratto il bundle, poi vale quanto detto per il .NET."),
    ("GO", "Go",
     [b"go:buildid", b"runtime.main", b"Go build ID"], 2, ("PE", "ELF", "MACHO"),
     "Il binario contiene i nomi dei pacchetti e delle funzioni: "
     "si ricostruisce la struttura, non il sorgente."),
    ("RUST", "Rust", [b"rustc", b"core::panicking", b"cargo registry"], 2, ("PE", "ELF", "MACHO"),
     "Come Go: nomi presenti, sorgente no."),
]

# Le DLL che raccontano cosa fa il programma, non come è stato scritto.
LIBRERIE_PARLANTI = {
    "oci.dll": "Oracle (client OCI)", "oraociei": "Oracle (client istantaneo)",
    "sqlncli": "SQL Server (native client)", "odbc32.dll": "ODBC",
    "msado": "ADO", "libpq": "PostgreSQL", "libmysql": "MySQL",
    "wininet.dll": "HTTP (WinINet)", "winhttp.dll": "HTTP (WinHTTP)",
    "ws2_32.dll": "rete (socket)", "mswsock": "rete (socket)",
    "crypt32.dll": "crittografia", "advapi32.dll": "registro di sistema, servizi, utenti",
    "netapi32": "rete Windows", "mapi32": "posta (MAPI)",
    "wsock32.dll": "rete (socket, vecchia)", "ole32.dll": "COM",
    "oleaut32.dll": "COM/automazione", "shell32.dll": "shell di Windows",
    "kernel32.dll": "sistema (file, processi, memoria)",
    "user32.dll": "interfaccia grafica", "gdi32.dll": "disegno",
    "comctl32.dll": "controlli grafici", "msvcrt.dll": "runtime C",
    "version.dll": "versioni dei file", "wintrust": "firme digitali",
}

# Le stringhe che valgono la pena di essere tirate fuori per prime.
INTERESSANTI = [
    ("SQL", re.compile(r"\b(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|MERGE\s+INTO|"
                       r"CREATE\s+(?:TABLE|VIEW|PROCEDURE)|EXEC(?:UTE)?\s)\b", re.I)),
    ("connection string", re.compile(r"(Data Source=|Provider=|Server=|Driver=\{|jdbc:|"
                                     r"Initial Catalog=|User Id=|DSN=)", re.I)),
    ("address", re.compile(r"https?://|ftp://|\\\\[A-Za-z0-9_.$-]+\\")),
    ("path", re.compile(r"[A-Za-z]:\\[^\s\"<>|]{4,}")),
    ("file", re.compile(r"\b[\w.-]{2,60}\.(?:csv|txt|xml|json|ini|cfg|dat|xls[xm]?|dbf|log|rpt)\b", re.I)),
    ("credential", re.compile(r"\b(password|passwd|pwd|user(?:name)?|api[_-]?key|token|secret)\b\s*[=:]", re.I)),
    ("message", re.compile(r"^[A-Z][A-Za-z].{14,}[.!?]$")),
]


def _stringhe(dati: bytes, minimo: int = 6) -> List[str]:
    """Le stringhe leggibili, sia a un byte sia UTF-16 (Windows le usa molto)."""
    fuori = []
    for grezza in re.findall(rb"[\x20-\x7e]{%d,}" % minimo, dati):
        fuori.append(grezza.decode("ascii", "ignore"))
    for grezza in re.findall(rb"(?:[\x20-\x7e]\x00){%d,}" % minimo, dati):
        fuori.append(grezza.decode("utf-16-le", "ignore").rstrip("\x00"))
    visti, unici = set(), []
    for s in fuori:
        s = s.strip()
        if s and s.lower() not in visti:
            visti.add(s.lower())
            unici.append(s)
    return unici


def _pe(dati: bytes) -> Dict[str, Any]:
    """Quel poco dell'intestazione PE che si legge a mano: quando è stato
    costruito, per che macchina, se è .NET. Se `pefile` c'è si aggiungono gli
    import veri, che valgono molto di più."""
    info: Dict[str, Any] = {}
    try:
        inizio_pe = struct.unpack_from("<I", dati, 0x3C)[0]
        if dati[inizio_pe:inizio_pe + 4] != b"PE\x00\x00":
            return info
        macchina, _sezioni, stampa = struct.unpack_from("<HHI", dati, inizio_pe + 4)
        info["macchina"] = {0x14C: "x86 (32 bit)", 0x8664: "x64 (64 bit)",
                            0x1C0: "ARM", 0xAA64: "ARM64"}.get(macchina, hex(macchina))
        if 0 < stampa < 4102444800:   # fino al 2100: oltre è un valore finto
            info["costruito"] = datetime.fromtimestamp(stampa, timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
        opzionale = inizio_pe + 24
        magia = struct.unpack_from("<H", dati, opzionale)[0]
        info["formato_pe"] = {0x10B: "PE32", 0x20B: "PE32+"}.get(magia, hex(magia))
    except Exception:
        pass
    try:
        import pefile   # facoltativo: se c'è, gli import sono precisi
        pe = pefile.PE(data=dati, fast_load=True)
        pe.parse_data_directories(directories=[
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
        librerie = {}
        for voce in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []) or []:
            nome = (voce.dll or b"").decode("ascii", "ignore")
            funzioni = [(i.name or b"").decode("ascii", "ignore")
                        for i in voce.imports if i.name]
            librerie[nome] = funzioni
        if librerie:
            info["import"] = librerie
    except ImportError:
        pass
    except Exception:
        pass
    return info


def esamina(percorso_o_dati, nome: str = "", max_stringhe: int = 250) -> Dict[str, Any]:
    """Tutto quello che si può dire del binario senza decompilarlo."""
    if isinstance(percorso_o_dati, (bytes, bytearray)):
        dati = bytes(percorso_o_dati)
        nome = nome or "(in memoria)"
    else:
        percorso = Path(percorso_o_dati)
        dati = percorso.read_bytes()
        nome = nome or percorso.name

    esito: Dict[str, Any] = {"nome": nome, "byte": len(dati), "formato": "sconosciuto",
                             "descrizione": "", "tecnologie": [], "librerie": [],
                             "import": {}, "stringhe": {}, "note": []}

    for firma, formato, descrizione in FIRME:
        if dati.startswith(firma):
            esito["formato"], esito["descrizione"] = formato, descrizione
            break

    basso = dati.lower()
    for chiave, etichetta, firme, minimo, formati, consiglio in INDIZI:
        if esito["formato"] not in formati:
            continue
        quante = sum(1 for f in firme if f.lower() in basso)
        if quante >= minimo:
            esito["tecnologie"].append({"codice": chiave, "cosa": etichetta,
                                        "firme_trovate": quante,
                                        "come_recuperare": consiglio})

    if esito["formato"] == "PE":
        # una lettura sola: `_pe` apre il file con pefile, e farlo due volte
        # costa il doppio senza aggiungere niente
        intestazione = _pe(dati)
        import_veri = intestazione.pop("import", None) or {}
        esito.update(intestazione)
        esito["import"] = import_veri
        nomi_dll = list(import_veri) or re.findall(r"[\w.-]+\.dll", dati.decode("latin-1"), re.I)
        viste = set()
        for dll in nomi_dll:
            b = dll.lower()
            if b in viste:
                continue
            viste.add(b)
            spiega = next((v for k, v in LIBRERIE_PARLANTI.items() if k in b), "")
            esito["librerie"].append({"dll": dll, "cosa_dice": spiega})

    tutte = _stringhe(dati)
    for etichetta, regola in INTERESSANTI:
        trovate = [s for s in tutte if regola.search(s)]
        if trovate:
            esito["stringhe"][etichetta] = trovate[:max_stringhe]
    esito["stringhe_totali"] = len(tutte)

    if not esito["tecnologie"]:
        esito["note"].append(
            "Nessuna firma riconosciuta: probabilmente codice nativo (C, C++, "
            "Delphi o VB6 compilato nativo). Ghidra o IDA danno codice C "
            "funzionalmente equivalente, non il sorgente: niente nomi veri, "
            "niente commenti. Se esiste il file .pdb dei simboli, recuperarlo: "
            "cambia completamente la qualità del risultato.")
    if b"RSDS" in dati:
        percorso_pdb = re.search(rb"RSDS.{20}([ -~]{4,200}\.pdb)", dati, re.S)
        if percorso_pdb:
            esito["note"].append(
                "Il binario dichiara il percorso dei simboli di compilazione: "
                + percorso_pdb.group(1).decode("ascii", "ignore")
                + " — se quel file .pdb esiste ancora, la decompilazione migliora molto.")
    return esito


def resoconto(esito: Dict[str, Any], max_per_gruppo: int = 40) -> str:
    """Il resoconto in testo: quello che si legge, e quello che si dà in pasto
    all'estrattore quando il sorgente non c'è."""
    r = [f"BINARY TRIAGE REPORT — {esito['nome']}",
         "=" * 68,
         f"Size: {esito['byte']:,} bytes",
         f"Format: {esito['formato']} ({esito['descrizione'] or 'n/d'})"]
    if esito.get("formato_pe"):
        r.append(f"PE flavour: {esito['formato_pe']}")
    if esito.get("macchina"):
        r.append(f"Architecture: {esito['macchina']}")
    if esito.get("costruito"):
        r.append(f"Build timestamp: {esito['costruito']}")

    r.append("")
    r.append("HOW THIS WAS BUILT, AND WHAT CAN BE RECOVERED")
    r.append("-" * 68)
    if esito["tecnologie"]:
        for t in esito["tecnologie"]:
            r.append(f"· {t['cosa']}")
            r.append(f"  {t['come_recuperare']}")
    else:
        r.append("· Not recognised — most likely native code.")
    for nota in esito["note"]:
        r.append(f"· {nota}")

    if esito["librerie"]:
        r.append("")
        r.append("LINKED LIBRARIES (what the program talks to)")
        r.append("-" * 68)
        for lib in esito["librerie"][:max_per_gruppo]:
            r.append(f"  {lib['dll']:<28} {lib['cosa_dice']}")

    if esito.get("import"):
        r.append("")
        r.append("IMPORTED FUNCTIONS (first few per library)")
        r.append("-" * 68)
        for dll, funzioni in list(esito["import"].items())[:15]:
            if funzioni:
                r.append(f"  {dll}: " + ", ".join(funzioni[:12])
                         + (" …" if len(funzioni) > 12 else ""))

    for etichetta, righe in esito["stringhe"].items():
        r.append("")
        r.append(f"STRINGS — {etichetta.upper()} ({len(righe)} found)")
        r.append("-" * 68)
        for s in righe[:max_per_gruppo]:
            r.append("  " + s[:200])
        if len(righe) > max_per_gruppo:
            r.append(f"  … and {len(righe) - max_per_gruppo} more")

    r.append("")
    r.append(f"({esito.get('stringhe_totali', 0):,} readable strings in total.)")
    return "\n".join(r)


def _main() -> int:  # pragma: no cover
    import argparse
    ap = argparse.ArgumentParser(description="Esame di un eseguibile di cui manca il sorgente.")
    ap.add_argument("file", help="il binario da esaminare")
    ap.add_argument("--stringhe", type=int, default=40, help="quante stringhe per gruppo")
    a = ap.parse_args()
    print(resoconto(esamina(a.file), max_per_gruppo=a.stringhe))
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(_main())

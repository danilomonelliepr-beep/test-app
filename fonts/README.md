# Caratteri

IBM Plex Sans e IBM Plex Mono, usati dal PDF (`exporter.py`) per avere la stessa
faccia dell'applicazione. Quattro file, circa 730 KB in tutto.

Licenza **SIL Open Font License 1.1** (`LICENSE.txt`): si possono ridistribuire
dentro un progetto, anche commerciale, a due condizioni — la licenza viaggia con
i file, e i font non si vendono da soli. Entrambe rispettate tenendoli qui.

Origine: pacchetti npm `@ibm/plex-sans` e `@ibm/plex-mono`, convertiti da WOFF a
TTF perché ReportLab legge solo TTF.

Se questa cartella manca, il PDF ricade su Helvetica: cambia la faccia, non il
contenuto.

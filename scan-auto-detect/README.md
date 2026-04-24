# Deye Auto Detect

Scripts de terminal para detectar `IP`, `serial` e modelo do logger/inversor Deye com uma heuristica mais robusta.

## Arquivos

- `deye_auto_detect.py`: nucleo compartilhado em Python
- `run_mac_linux.sh`: launcher para macOS e Linux
- `run_windows.bat`: launcher para Windows

## Como usar

macOS / Linux:

```bash
cd /Users/gabriel/HomeyApp/gpm.python.deye/scan-auto-detect
bash run_mac_linux.sh
```

Windows:

```bat
cd \Users\gabriel\HomeyApp\gpm.python.deye\scan-auto-detect
run_windows.bat
```

## O que o script faz

1. Descobre loggers por UDP quando o IP fica em branco.
2. Quando voce informa so o IP, tenta obter o serial por UDP unicast e depois por HTTP.
3. Testa a conexao antes da leitura completa.
4. Faz auto-deteccao de modelo usando os JSONs atuais da pasta `inverter_definitions`.
5. Gera um arquivo `.txt` com o diagnostico no Desktop do usuario, ou na home se nao houver Desktop.

## Dependencias

Nao instala nem usa `pysolarmanv5`.

O script funciona com Python 3 e usa um transporte Solarman V5 embutido no proprio ficheiro, para evitar dependencias externas e diferencas entre sistemas operativos.

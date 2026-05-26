# TODO

## Concluído ✅

- **Widget Homey** (v1.4.0) — `energy-summary` com layout dinâmico por capabilities.
  Dark/light mode. Primeiro app Python na Homey store com widget.

- **Advanced sensors checkbox no pairing** — capabilities básicas vs opcionais separadas.
- **PV3/PV4 apenas quando detectados** — filtro por valores reais no pairing.
- **Derived PV power para string/micro** — calculado em runtime (V×I).
- **Script de scan universal** — `scan-auto-detect/` cobre todos os 4 modelos.
- **Sun times cacheado** — calculado 1x/dia.
- **TCP socket leak** (v1.3.22) — `read_all()` com `try/finally`; `drain()` com timeout.
  Half-open connections bloqueavam o logger por 15-20 min.
- **Night offline sem set_unavailable** (v1.3.22) — warning após 3 erros (~3 min),
  unavailable só após 120 erros (~2 h). Buffer de 30 min antes do pôr do sol.
- **Offline notifications** (v1.3.22) — timeline Homey após X min offline (padrão 10).
  Notificação de recovery quando polling retoma. Configurável por device.
- **Auto-fill coordenadas** (v1.3.22) — `solar_latitude`/`solar_longitude` preenchidos
  automaticamente da geolocalização do Homey quando estão em zero.
- **Wi-Fi signal display** (v1.3.22) — logger retorna percentagem, não dBm.
  Corrigido em `device.py` e `driver.py`.
- **Publicado na Homey App Store** — v1.3.8 publicada.

## Pendente

- [ ] **Publicar v1.3.22 na Homey App Store** — contém fixes críticos (TCP leak, night mode).
- [ ] **Detecção de modelo ambígua** — primeira tentativa de pairing detectou `deye_micro`
  (score=21) em vez de `deye_string` (score=25) no mesmo hardware. Investigar lógica de
  scoring em `driver.py` (`_score_model`).
- [ ] **`set_warning` visual no Python SDK** — o warning triangle aparece nos logs mas
  pode não renderizar na UI do Homey app (limitação do Python runtime). Precisa teste isolado.
- [ ] **Flow cards fase 2**:
  - Trigger `solar_power_changed`
  - Trigger `grid_export_started` / `grid_import_started`
  - Trigger `inverter_status_changed`
  - Condition `is_producing`, `grid_is_exporting`
  - Trigger `battery_soc_changed` (hybrid)
- [ ] **L2/L3 no deye_string.json** — registros 74,75,77,78 para trifásicos.
- [x] **Widget Homey** — `widgets/energy-summary/` implementado (v1.4.0).
  Layout dinâmico por capabilities: 1–4 células conforme Solar/Grid/Load/Battery disponíveis.
  Dark mode automático. Primeiro app Python na store com widget.

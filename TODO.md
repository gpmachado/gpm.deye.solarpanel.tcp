# TODO

## Concluído ✅

- **Advanced sensors checkbox no pairing** — capabilities básicas vs opcionais separadas.
  `_ADVANCED_CAPS` em driver.py controla o que aparece sem o checkbox.
- **PV3/PV4 apenas quando detectados** — filtro por valores reais no pairing;
  PV1/PV2 sempre mantidos mesmo quando lidos a zero.
- **Separação básico / avançado por modelo** — implementado via `_ADVANCED_CAPS` +
  checkbox. Battery e Grid Meter tiles sempre criados quando detectados (não dependem do checkbox).
- **Derived PV power para string/micro** — calculado em runtime (V×I) já que não há
  registros diretos de potência PV nesses modelos.
- **Script de scan universal** — `deye_scan_mac.sh` cobre todos os 4 modelos com
  auto-discovery UDP (serial automático) e auto-detecção de modelo.
- **Sun times cacheado** — calculado 1x/dia, não em cada poll.
- **`add_capability` (snake_case)** — corrigido de `addCapability`.

## Pendente

- [ ] **Publicar no Homey App Store** — versão v1.3.3 pronta, aguarda testes do Luis (hybrid).
- [ ] **Flow cards fase 2** — padrões retirados do app FusionSolar (Huawei, JS):
  - **Trigger `solar_power_changed`** — dispara sempre que `measure_power.solar` muda
    valor; comparar `prev = get_capability_value(cap)` antes de `set_capability_value`,
    só disparar o trigger se `prev != new`. Simples de implementar em `device.py`.
  - **Trigger `grid_export_started` / `grid_import_started`** — rastrear `_prev_exporting`
    bool na classe; a cada poll, detectar transição (import→export ou export→import) em
    `measure_power.grid` (negativo = exportando no Deye) e disparar o trigger
    correspondente. Útil para automações tipo "quando começou a exportar, ligue X".
  - **Trigger `inverter_status_changed`** — comparar `_prev_status` com o novo valor de
    `Running Status`; disparar quando mudar (Normal → Fault, etc.).
  - **Condition `is_producing`** — `get_capability_value('measure_power.solar') > 0`.
  - **Condition `grid_is_exporting`** — lê o bool `_prev_exporting` já rastreado.
  - **Trigger `battery_soc_changed`** (hybrid) — dispara quando `measure_battery` muda;
    rastrear com `_prev_soc`. Útil para automações de SOC (ex: acima de 80%, ligue A/C).
- [ ] **Script de scan para Hoymiles** — `hoymiles_scan_mac.sh` equivalente.
- [ ] **L2/L3 no deye_string.json** — registros 74,75,77,78 para utilizadores trifásicos
  (Gabriel é monofásico, mas outros utilizadores podem precisar).
- [ ] **Luis re-pair** — verificar se as capabilities PV1/PV2 do hybrid foram corrigidas
  após o fix da detecção noturna.

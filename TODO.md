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
- [ ] **Flow cards fase 2** — threshold de produção solar, SOC da bateria, trigger
  de importação/exportação da rede.
- [ ] **Script de scan para Hoymiles** — `hoymiles_scan_mac.sh` equivalente.
- [ ] **L2/L3 no deye_string.json** — registros 74,75,77,78 para utilizadores trifásicos
  (Gabriel é monofásico, mas outros utilizadores podem precisar).
- [ ] **Luis re-pair** — verificar se as capabilities PV1/PV2 do hybrid foram corrigidas
  após o fix da detecção noturna.

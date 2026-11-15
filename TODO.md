# TODO

## Prioridade

- [ ] **Diagnóstico de registradores para sistemas híbridos** — criar um modo temporário
  no pairing que conecte usando IP e serial do logger, leia intervalos informados e gere
  uma saída copiável. Não salvar uma segunda instância do dispositivo.
  Parcial: `scan-auto-detect/sofar_register_dump.py` (fora do app) e
  `scan-auto-detect/test_registers.py <ip> <serial> <modelo>` já fazem isso no terminal.
- [ ] **Auto-detect Deye pelo registro 0x0000 ("Device")** — davidrapan `deye_p3.yaml`:
  2 = string, 3 = híbrido monofásico, 4 = micro, 5 = híbrido trifásico LV, 6/7/8 = HV.
  Ler um registro substitui a pontuação heurística (que falha à noite) e resolve LV × HV.
  Confirmar com um dump de cada família antes de trocar.
- [ ] **Validar o perfil beta `deye_sg01hp3` (HV)** — criado a partir da coluna HV do
  davidrapan `deye_p3.yaml`: PV1/PV2 e bateria ×10, tensão da bateria ×0,1; o resto igual
  ao `deye_sg04lp3`. Falta um dump de um HV real (Stemacone, fórum #31, SUN-20K-SG01HP3)
  para conferir PV, totais e sinais. Validado → tirar o "(beta)" e auto-detectar pelo
  registro 0x0000. Conferir também o README: "Sun-5k-SG01HP3 (single-phase)" — HP3
  normalmente é trifásico HV.
- [ ] **Adicionar L2/L3 ao `deye_string.json`** — validar os registros 74, 75, 77 e 78
  em um inversor string trifásico antes de expor as capabilities.

## Feito

- [x] **Validar bateria em hardware híbrido** — SOC, sinais e Charge/Discharge Power
  conferidos no SOFAR ESI-12K-T1 (issues #7, #8, 1.4.13); labels `Power Usage` /
  `Power Delivery` substituídos (opção D, issue #3).

## Depois

- [ ] **Widget "Power Flow" (1.4.17)** — fluxo de energia como o display SOFAR: Solar →
  INV → Bateria / Rede / Casa, setas animadas no sentido do fluxo, SOC da bateria.
  Reusar `get_solar_summary()` (app.py) — já traz solar, grid, load, battery (+ = carga)
  e battery_soc de Deye e SOFAR. Sem bateria/rede (string/micro): esconder esses ramos.
  Casas com 2+ inversores: adicionar definição no widget para escolher o dispositivo.
- [ ] Avaliar trigger de alteração significativa de potência solar.
- [ ] Avaliar trigger de mudança de status do inversor.
- [ ] Avaliar trigger de mudança de SOC da bateria.

# TODO

## Prioridade

- [ ] **Diagnóstico de registradores para sistemas híbridos** — criar um modo temporário
  no pairing que conecte usando IP e serial do logger, leia intervalos informados e gere
  uma saída copiável. Não salvar uma segunda instância do dispositivo.
- [ ] **Validar bateria em hardware híbrido** — conferir SOC e sinais de
  `measure_power` / `measure_power.battery` com os registradores brutos antes de alterar
  cálculos ou publicar os labels `Power Usage` e `Power Delivery`.
- [ ] **Adicionar L2/L3 ao `deye_string.json`** — validar os registros 74, 75, 77 e 78
  em um inversor string trifásico antes de expor as capabilities.

## Depois

- [ ] **Widget "Power Flow" (1.4.14)** — fluxo de energia como o display SOFAR: Solar →
  INV → Bateria / Rede / Casa, setas animadas no sentido do fluxo, SOC da bateria.
  Reusar `get_solar_summary()` (app.py) — já traz solar, grid, load, battery (+ = carga)
  e battery_soc de Deye e SOFAR. Sem bateria/rede (string/micro): esconder esses ramos.
  Casas com 2+ inversores: adicionar definição no widget para escolher o dispositivo.
- [ ] Avaliar trigger de alteração significativa de potência solar.
- [ ] Avaliar trigger de mudança de status do inversor.
- [ ] Avaliar trigger de mudança de SOC da bateria.

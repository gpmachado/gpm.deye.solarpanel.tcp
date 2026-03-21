# Third-Party Notices

This project incorporates material from the following third-party works.

---

## ha-solarman

**Repository:** https://github.com/StephanJoubert/home_assistant_solarman  
**Author:** Stephan Joubert and contributors  
**License:** MIT

The register definitions in `lib/deyeRegisters.js` and the register parsing rules
in `lib/registerParser.js` were derived from the inverter definition files and
parser logic in ha-solarman.

Rule numbering, offset/scale formula (`decoded = (raw - offset) * scale`),
and register addresses for the Deye G0* string inverter family are based on
the YAML definitions found in the `inverter_definitions/` directory of that project.

---

## pysolarmanv5

**Repository:** https://github.com/jmccrohan/pysolarmanv5  
**Author:** Jonathan McCrohan and contributors  
**License:** MIT

The SolarmanV5 frame structure implemented in `lib/solarmanV5.js` —
including header layout, payload prefix offsets, checksum algorithm,
and request/response framing — was derived from the protocol documentation
and reference implementation in pysolarmanv5.

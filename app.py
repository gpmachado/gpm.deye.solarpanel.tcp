from homey.app import App


class MyApp(App):

    async def on_init(self):
        await super().on_init()
        self.log("Initialized MyApp")
        self._register_flow_conditions()

    def _register_flow_conditions(self):
        """Register run listeners for all condition flow cards."""

        async def _is_solar_producing(args, state):
            device = args.get("device")
            if not device:
                return False
            power = device.get_capability_value("measure_power") or 0
            return float(power) > 5.0

        async def _is_battery_charging(args, state):
            device = args.get("device")
            if not device:
                return False
            # battery_charging_state is the authoritative source (normalized enum)
            status = device.get_capability_value("battery_charging_state")
            if status is not None:
                return status == "charge"
            # Fallback: measure_power on the battery device is already normalized
            # (positive = charging, per Homey convention) — NOT the raw Deye value
            power = device.get_capability_value("measure_power") or 0
            return float(power) > 0

        async def _is_grid_feeding(args, state):
            device = args.get("device")
            if not device:
                return False
            grid = device.get_capability_value("measure_power.grid") or 0
            return float(grid) < 0  # negative = exporting to grid

        try:
            self.homey.flow.get_condition_card("is_solar_producing") \
                .register_run_listener(_is_solar_producing)
            self.homey.flow.get_condition_card("is_battery_charging") \
                .register_run_listener(_is_battery_charging)
            self.homey.flow.get_condition_card("is_grid_feeding") \
                .register_run_listener(_is_grid_feeding)
        except Exception as e:
            self.log(f"Flow condition registration failed: {e}")


homey_export = MyApp

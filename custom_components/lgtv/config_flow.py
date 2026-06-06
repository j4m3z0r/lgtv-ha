import voluptuous as vol
from homeassistant import config_entries
from .const import DOMAIN
from aiopylgtv import WebOsClient
import asyncio

class LGTVConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self.client = None
        self.ip_address = None

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            self.ip_address = user_input["ip_address"]
            await self.async_set_unique_id(self.ip_address)
            self._abort_if_unique_id_configured()
            self.client = WebOsClient(self.ip_address)
            
            try:
                await asyncio.wait_for(self.client.connect(), timeout=30)
            except asyncio.TimeoutError:
                errors["base"] = "pairing_failed"
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=self.ip_address,
                    data={"ip_address": self.ip_address, "client_key": self.client.client_key},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("ip_address"): str,
            }),
            errors=errors,
        )

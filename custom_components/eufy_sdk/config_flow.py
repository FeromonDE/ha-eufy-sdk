"""Config flow for eufy_sdk — connect to the bridge, then drive 2FA/captcha to login."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    EufySdkApiClient,
    EufySdkApiClientCommunicationError,
    EufySdkApiClientError,
)
from .const import CONF_HOST, CONF_PORT, DEFAULT_PORT, DOMAIN, LOGGER


class EufySdkFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Ask for the bridge address, then walk the user through login (2FA / captcha)."""

    VERSION = 1

    def __init__(self) -> None:
        """Hold the in-flight bridge connection across steps."""
        self._client: EufySdkApiClient | None = None
        self._host: str = ""
        self._port: int = DEFAULT_PORT

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Step 1: the bridge's host + port."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._host = str(user_input[CONF_HOST]).strip()
            # NumberSelector hands back a float (3012.0); int-ify it for the WS URL.
            self._port = int(user_input[CONF_PORT])
            await self.async_set_unique_id(f"{self._host}:{self._port}")
            self._abort_if_unique_id_configured()
            try:
                self._client = EufySdkApiClient(
                    self._host, self._port, async_get_clientsession(self.hass)
                )
                await self._client.connect()
            except EufySdkApiClientCommunicationError as err:
                LOGGER.warning("bridge connect failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                return await self._continue_auth()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST,
                        default=(user_input or {}).get(CONF_HOST, vol.UNDEFINED),
                    ): selector.TextSelector(),
                    vol.Required(
                        CONF_PORT,
                        default=(user_input or {}).get(CONF_PORT, DEFAULT_PORT),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=65535, mode=selector.NumberSelectorMode.BOX
                        ),
                    ),
                },
            ),
            errors=errors,
        )

    async def _continue_auth(self) -> config_entries.ConfigFlowResult:
        """Route to the right step for the bridge's current auth state."""
        if self._client is None:
            return self.async_abort(reason="cannot_connect")
        try:
            auth = await self._client.auth_status()
        except EufySdkApiClientError as err:
            LOGGER.error("auth.status failed: %s", err)
            await self._client.close()
            self._client = None
            return self.async_abort(reason="cannot_connect")

        state = auth.get("state")
        if state == "ok":
            await self._client.close()  # the coordinator opens its own connection
            self._client = None
            return self.async_create_entry(
                title=f"eufy bridge ({self._host})",
                data={CONF_HOST: self._host, CONF_PORT: self._port},
            )
        if state == "require_2fa":
            return await self.async_step_twofa()
        if state == "require_captcha":
            return await self.async_step_captcha()
        # "pending": ask the bridge for a challenge, then re-route.
        await self._client.retrigger_auth()
        return await self._continue_auth()

    async def async_step_twofa(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Submit the 2FA code that was sent to the account."""
        if self._client is None:
            return self.async_abort(reason="cannot_connect")
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get("resend"):
                await self._client.retrigger_auth()
                return await self._continue_auth()
            auth = await self._client.submit_2fa(str(user_input["code"]))
            if auth.get("state") == "ok":
                return await self._continue_auth()
            errors["base"] = "invalid_2fa"

        return self.async_show_form(
            step_id="twofa",
            data_schema=vol.Schema(
                {
                    vol.Required("code"): selector.TextSelector(),
                    vol.Optional("resend", default=False): selector.BooleanSelector(),
                },
            ),
            errors=errors,
        )

    async def async_step_captcha(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Show the captcha image (markdown in the description) and take the answer."""
        if self._client is None:
            return self.async_abort(reason="cannot_connect")
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get("refresh"):
                await self._client.retrigger_auth()
                return await self._continue_auth()
            auth = await self._client.submit_captcha(str(user_input["answer"]))
            if auth.get("state") == "ok":
                return await self._continue_auth()
            errors["base"] = "invalid_captcha"

        auth = await self._client.auth_status()
        image = auth.get("image", "")
        return self.async_show_form(
            step_id="captcha",
            data_schema=vol.Schema(
                {
                    vol.Required("answer"): selector.TextSelector(),
                    vol.Optional("refresh", default=False): selector.BooleanSelector(),
                },
            ),
            # The frontend renders the description as markdown; embed the data-URI.
            description_placeholders={
                "image": f"![captcha]({image})"
                if image
                else "(captcha unavailable — tick refresh)"
            },
            errors=errors,
        )

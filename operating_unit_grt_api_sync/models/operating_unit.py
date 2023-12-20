import logging
import os
from datetime import datetime

import requests

from odoo import fields, models

_logger = logging.getLogger(__name__)


class OperatingUnit(models.Model):
    _inherit = "operating.unit"

    synced_with_grt = fields.Boolean(
        "Is Synced with GRT API", default=False, readonly=True
    )

    def _get_grt_api_params(self):
        """
        Returns GRT API url and API key that are necessary for fetching data
        from GRT API.
        """
        return (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("operating_unit_grt_api_sync.grt_api_url", None),
            os.environ.get("GRT_API_KEY", None),
        )

    def _fetch_grt_operating_unit_data(self):
        """Requests data from GRT API and returns it as a dictionary."""
        api_url, api_key = self._get_grt_api_params()
        if not api_url or not api_key:
            _logger.error("GRT API Sync: API url or key has not been provided.")
            return
        try:
            _logger.info("GRT API Sync: Requesting data from GRT API.")
            r = requests.get(
                api_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=30
            )
            if r.status_code == 200:
                _logger.info("GRT API Sync: Successfully received data from GRT API.")
                return r.json()
            else:
                error_message = r.json().get("detail")
                _logger.warning(
                    f"GRT API Sync: Request to GRT API failed with "
                    f"status code {r.status_code}: {error_message}."
                )
        except Exception as e:
            _logger.error(f"GRT API Sync: Request to GRT API failed with error {e}.")

    def _sync_operating_unit_data_with_grt(self):
        """Main method used by scheduled action to sync data with GRT API."""
        if data := self._fetch_grt_operating_unit_data():  # noqa: E231 E701
            self._process_grt_operating_unit_data(data)

    @staticmethod
    def _prepare_branch_name(branch_name):
        """Returns branch name with proper prefix."""
        return branch_name if branch_name == "OU Office" else f"Branch {branch_name}"

    def _prepare_ou_create_vals(self, code, data, ou_code_company_mapping):
        """Returns dictionary with values used to create a new operating unit."""
        branch_name = self._prepare_branch_name(data["branch"])
        name = f"{code} - OU {data['operating_unit']}, {branch_name}"
        company_id = ou_code_company_mapping[code[:3]]
        return {
            "name": name,
            "code": code,
            "company_id": company_id,
            "valid_from": data["valid_from"],
            "valid_until": data["valid_until"],
            "synced_with_grt": True,
        }

    def _prepare_ou_partner_create_vals(self, data, country_mapping):
        """
        Returns dictionary with values used to create new partner used by
        operating unit.
        """
        branch_name = self._prepare_branch_name(data["branch"])
        country_id = country_mapping[data["country"]]
        return {
            "name": f"OU {data['operating_unit']}, {branch_name}",
            "city": data["branch"],
            "country_id": country_id,
        }

    def _create_new_operating_unit(self, data, ou_code_company_mapping):
        """
        Creates new operating units and related partners based on data received from
        GRT API.
        """
        vals = []
        partner_vals = []
        countries = self.env["res.country"].search([])
        country_mapping = {country.name: country.id for country in countries}
        for code, branch_data in data.items():
            create_vals = self._prepare_ou_create_vals(
                code, branch_data, ou_code_company_mapping
            )
            vals.append(create_vals)
            partner_create_vals = self._prepare_ou_partner_create_vals(
                branch_data, country_mapping
            )
            partner_vals.append(partner_create_vals)
        partners = self.env["res.partner"].create(partner_vals)
        vals_with_partner = []
        for partner, data in zip(partners, vals):
            data.update({"partner_id": partner.id})
            vals_with_partner.append(data)
        self.create(vals_with_partner)

    def _update_operating_unit(self, data):
        """Updates OU validity dates and sets synced_with_grt to True if necessary."""
        self.ensure_one()
        vals = {}
        if self.valid_from != data["valid_from"]:
            vals["valid_from"] = data["valid_from"]
        if self.valid_until != data["valid_until"]:
            vals["valid_until"] = data["valid_until"]
        if not self.synced_with_grt:
            vals["synced_with_grt"] = True
        if vals:
            self.write(vals)

    @staticmethod
    def _filter_branches_data(data, ou_code_company_mapping):
        """Filters data received from GRT API to only include branches (L5) data."""
        return [
            d
            for d in data
            if d["management_id"][:3] in ou_code_company_mapping
            and d["management_id_level_number"] == 5
        ]

    def _prepare_api_data(self, data, ou_code_company_mapping):
        """
        Filters data received from GRT API to keep only branches (Level 5) data and
        checks if the required keys are present. If so, returns a dictionary with GRT
        code prefixes as keys and dictionaries with data as values.
        """

        # Process the branches (Level 5) data only.
        if branches_data := self._filter_branches_data(  # noqa: E231 E701
            data, ou_code_company_mapping
        ):
            try:
                api_data = {
                    d["management_id"]: {
                        "valid_from": d["operational_from"],
                        "valid_until": d["operational_until"],
                        "branch": d["l5_branch"],
                        "operating_unit": d["l8_operating_unit"],
                        "country": d["l10_operating_country"],
                    }
                    for d in branches_data
                }
                return api_data
            except KeyError as e:
                _logger.error(
                    f"GRT API Sync: Received data from GRT API is "
                    f"missing key: {e.args[0]}."
                )

    def _get_ou_code_company_mapping(self):
        """
        Returns dictionary with GRT code prefixes as keys and matching company IDs
        as values.
        """
        ou_code_company_mapping = {}
        compatible_companies = self.env["res.company"].search(
            [("grt_code_prefixes", "!=", False)]
        )
        for company in compatible_companies:
            prefixes = company.grt_code_prefixes.replace(" ", "").split(",")
            ou_code_company_mapping.update(
                {prefix.strip(): company.id for prefix in prefixes}
            )
        return ou_code_company_mapping

    def _process_grt_operating_unit_data(self, data):
        """
        Processes data received from GRT API by comparing identically structured data
        received from GRT API with existing data. If the OU code is present locally,
        update the OU if necessary. Otherwise create a new OU.
        """
        ou_code_company_mapping = self._get_ou_code_company_mapping()

        if api_data := self._prepare_api_data(  # noqa: E231 E701
            data, ou_code_company_mapping
        ):
            operating_units = self.search([])
            operating_units_data = {
                ou.code: {
                    "valid_from": datetime.strftime(ou.valid_from, "%Y-%m-%d")
                    if ou.valid_from
                    else None,
                    "valid_until": datetime.strftime(ou.valid_until, "%Y-%m-%d")
                    if ou.valid_until
                    else None,
                    "country": ou.partner_id.country_id.name,
                }
                for ou in operating_units
            }

            if ou_create_data := {  # noqa: E231 E701
                k: v for k, v in api_data.items() if k not in operating_units_data
            }:
                self._create_new_operating_unit(ou_create_data, ou_code_company_mapping)

            if ou_update_data := {  # noqa: E231 E701
                k: v for k, v in operating_units_data.items() if k in api_data
            }:
                for code, data in ou_update_data.items():
                    if api_data[code] != data:
                        operating_unit = operating_units.filtered(
                            lambda b: b.code == code
                        )
                        operating_unit._update_operating_unit(api_data[code])

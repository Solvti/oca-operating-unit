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
        ConfigParameter = self.env["ir.config_parameter"]
        api_url = ConfigParameter.sudo().get_param(
            "operating_unit_grt_api_sync.grt_api_url", None
        )
        api_key = os.environ.get(
            "GRT_API_KEY", None
        ) or ConfigParameter.sudo().get_param(
            "operating_unit_grt_api_sync.grt_api_key", None
        )
        return api_url, api_key

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

    def _sync_operating_unit_data_with_grt_cron(self):
        """Main method used by scheduled action to sync data with GRT API."""
        if data := self._fetch_grt_operating_unit_data():
            self._process_grt_operating_unit_data(data)

    def _get_ou_create_vals(self, code, data):
        """Returns dictionary with values used to create a new operating unit."""
        return {
            "code": code,
            "name": data["name"],
            "company_id": data["company_id"],
            "valid_from": data["valid_from"],
            "valid_until": data["valid_until"],
            "synced_with_grt": True,
        }

    def _get_ou_partner_create_vals(self, data):
        """
        Returns dictionary with values used to create new partner used by
        operating unit.
        """
        return {
            "name": data["name"],
            "city": data["branch"],
            "country_id": data["country_id"],
        }

    def _get_create_vals_operating_unit(self, code, new_data):
        """
        Creates new partner for operating unit and creates related partner based on data received from
        GRT API.
        """
        create_vals = self._get_ou_create_vals(code, new_data)
        partner_create_vals = self._get_ou_partner_create_vals(new_data)
        partner = self.env["res.partner"].create(partner_create_vals)
        create_vals["partner_id"] = partner.id
        return create_vals

    def _get_update_vals_operating_unit(self, new_data, existing_data):
        """
        Checks if there are any difference between grt api & existing data.
        Compares new data with existing data.
        Returns: Dict of values to update on operating unit.
        """
        vals = {}
        if new_data.get("name") != existing_data.get("name"):
            vals["name"] = new_data["name"]
        if new_data.get("valid_from") != existing_data.get("valid_from"):
            vals["valid_from"] = new_data["valid_from"]
        if new_data.get("valid_until") != existing_data.get("valid_until"):
            vals["valid_until"] = new_data["valid_until"]
        return vals

    def _is_code_company(self, branch_data, ou_code_company_mapping):
        return branch_data.get("management_id", "")[:3] in ou_code_company_mapping

    def _is_branch_level(self, branch_data):
        """Check if branch is on the level 5 (branch)."""
        return branch_data.get("management_id_level_number", 0) == 5

    def _get_grt_api_branches(self, data):
        """
        Filters data received from GRT API to keep only branches (Level 5) data and
        checks if the required keys are present. If so, returns a dictionary with GRT
        code prefixes as keys and dictionaries with data as values.
        """
        ou_code_company_mapping = self._get_ou_code_company_mapping()
        countries = self.env["res.country"].search([])
        country_mapping = {country.name: country.id for country in countries}

        branches_data = {}
        for branch_data in data:
            if not self._is_branch_level(branch_data):
                continue
            if not self._is_code_company(branch_data, ou_code_company_mapping):
                continue
            try:
                ou_code = branch_data["management_id"]
                name = self._get_operating_unit_name(ou_code, branch_data)
                country_name = branch_data.get("l10_operating_country", "")
                branches_data[ou_code] = {
                    "name": name,
                    "valid_from": branch_data.get("operational_from", False),
                    "valid_until": branch_data.get("operational_until", False),
                    "branch": branch_data.get("l5_branch", ""),
                    "country": country_name,
                    "country_id": country_mapping.get(country_name, False),
                    "company_id": ou_code_company_mapping.get(ou_code[:3], False),
                }
            except KeyError as e:
                _logger.error(
                    f"GRT API Sync: Received data from GRT API is "
                    f"missing key: {e.args[0]}."
                )
        return branches_data

    def _get_operating_unit_name(self, code, branch_data):
        """
        Get operating unit name. If it's not a office add Branch prefix to the branch name.
        Concat OU name with branch name.
        """
        ou_name = f"{code} - OU {branch_data.get('l8_operating_unit', '')}"
        if branch_data.get("is_office"):
            branch_name = f", {branch_data.get('l5_branch', '')}"
        else:
            branch_name = f", Branch {branch_data.get('l5_branch', '')}"
        return ou_name + branch_name

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

    def _get_existing_operating_unit_data(self):
        operating_units = self.search([])
        operating_units_data = {
            ou.code: {
                "object": ou,
                "name": ou.name,
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
        return operating_units_data

    def _process_grt_operating_unit_data(self, data):
        """
        Processes data received from GRT API by comparing identically structured data
        received from GRT API with existing data. If the OU code is present locally,
        update the OU if necessary. Otherwise create a new OU.
        """
        if branches_data := self._get_grt_api_branches(data):
            create_vals_list = []
            existing_operating_units_data = self._get_existing_operating_unit_data()
            for code, branch_data in branches_data.items():
                existing_operating_unit_data = existing_operating_units_data.get(code)
                if existing_operating_unit_data:
                    vals = self._get_update_vals_operating_unit(
                        branch_data, existing_operating_unit_data
                    )
                    if vals:
                        vals["synced_with_grt"] = True
                        existing_operating_unit_data.get("object").write(vals)
                        self._log_grt_api_changes(
                            f"Updated operating unit for code = {code} with values: {vals}",
                            "update",
                        )
                else:
                    vals = self._get_create_vals_operating_unit(code, branch_data)
                    create_vals_list.append(vals)
            if create_vals_list:
                self.create(create_vals_list)
                self._log_grt_api_changes(
                    f"Created new operating units with values: {create_vals_list}",
                    "create",
                )
                _logger.info(
                    f"GRT API Sync: Successfully created [{len(create_vals_list)}] Operating Units."
                )

    def _log_grt_api_changes(self, message, action_type):
        """Log api changes to ir.logging table."""

        def log(message, action_type):
            with self.pool.cursor() as cr:
                cr.execute(
                    """
                    INSERT INTO ir_logging(create_date, create_uid, type, dbname, name, level, message, path, line, func)
                    VALUES (NOW() at time zone 'UTC', %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                    (
                        self.env.uid,
                        "server",
                        self._cr.dbname,
                        __name__,
                        "info",
                        message,
                        "sync",
                        action_type,
                        "Sync with GRT API",
                    ),
                )

        log(message, action_type)

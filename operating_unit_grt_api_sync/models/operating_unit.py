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

    def _get_grt_api_url(self):
        return (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("operating_unit_grt_api_sync.grt_api_url", False)
        )

    def _fetch_grt_data(self):
        api_key = os.environ.get("GRT_API_KEY")
        if not api_key:
            _logger.error("GRT API Sync: API key has not been provided.")
            return
        url = self._get_grt_api_url()
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            _logger.info("GRT API Sync: Requesting data from GRT API.")
            r = requests.get(url, headers=headers, timeout=30)
            if r.status_code == 200:
                _logger.info("GRT API Sync: Requesting data from GRT API.")
                return r.json()
            else:
                error_message = r.json().get("detail")
                _logger.warning(
                    f"GRT API Sync: Request to GRT API failed with "
                    f"status code {r.status_code}: {error_message}."
                )
        except Exception as e:
            _logger.error(f"GRT API Sync: Request to GRT API failed with error {e}.")

    def _sync_branches_data_with_grt(self):
        if data := self._fetch_grt_data():  # noqa: E231 E701
            self._process_grt_branch_data(data)

    @staticmethod
    def _prepare_branch_name(branch_name):
        return branch_name if branch_name == "OU Office" else f"Branch {branch_name}"

    def _prepare_branch_create_vals(self, code, data, ou_code_company_mapping):
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

    def _prepare_branch_partner_create_vals(self, data, country_mapping):
        branch_name = self._prepare_branch_name(data["branch"])
        country_id = country_mapping[data["country"]]
        return {
            "name": f"OU {data['operating_unit']}, {branch_name}",
            "city": data["branch"],
            "country_id": country_id,
        }

    def _create_new_branches(self, data, ou_code_company_mapping):
        vals = []
        partner_vals = []
        countries = self.env["res.country"].search([])
        country_mapping = {country.name: country.id for country in countries}
        for code, branch_data in data.items():
            create_vals = self._prepare_branch_create_vals(
                code, branch_data, ou_code_company_mapping
            )
            vals.append(create_vals)
            partner_create_vals = self._prepare_branch_partner_create_vals(
                branch_data, country_mapping
            )
            partner_vals.append(partner_create_vals)
        partners = self.env["res.partner"].create(partner_vals)
        vals_with_partner = []
        for partner, data in zip(partners, vals):
            data.update({"partner_id": partner.id})
            vals_with_partner.append(data)
        self.create(vals_with_partner)

    @staticmethod
    def _filter_branches_data(data, ou_code_company_mapping):
        return [
            d
            for d in data
            if d["management_id"][:3] in ou_code_company_mapping
            and d["management_id_level_number"] == 5
        ]

    @staticmethod
    def _filter_branches_to_update(recs, data):
        """Filter the recordset to only include records that need to be updated."""
        return recs.filtered(
            lambda mid: mid.valid_from != data[mid.code]["operational_from"]
            or mid.valid_until != data[mid.code]["operational_until"]
            or not mid.synced_with_grt
        )

    def _update_branch(self, data):
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

    def _process_grt_branch_data(self, data):
        compatible_companies = self.env["res.company"].search(
            [("grt_code_prefix", "!=", False)]
        )
        ou_code_company_mapping = {
            c.grt_code_prefix: c.id for c in compatible_companies
        }

        if data := self._filter_branches_data(  # noqa: E231 E701
            data, ou_code_company_mapping
        ):
            api_data = {
                d["management_id"]: {
                    "valid_from": d["operational_from"],
                    "valid_until": d["operational_until"],
                    "branch": d["l5_branch"],
                    "operating_unit": d["l8_operating_unit"],
                    "country": d["l10_operating_country"],
                }
                for d in data
            }
            branches = self.search([])
            branches_data = {
                b.code: {
                    "valid_from": datetime.strftime(b.valid_from, "%Y-%m-%d")
                    if b.valid_from
                    else None,
                    "valid_until": datetime.strftime(b.valid_until, "%Y-%m-%d")
                    if b.valid_until
                    else None,
                    "country": b.partner_id.country_id.name,
                }
                for b in branches
            }

            if branches_create_data := {  # noqa: E231 E701
                k: v for k, v in api_data.items() if k not in branches_data
            }:
                self._create_new_branches(branches_create_data, ou_code_company_mapping)

            if branches_update_data := {  # noqa: E231 E701
                k: v for k, v in branches_data.items() if k in api_data
            }:
                api_data = {
                    d["management_id"]: {
                        "valid_from": d["operational_from"],
                        "valid_until": d["operational_until"],
                    }
                    for d in data
                }
                for code, data in branches_update_data.items():
                    if api_data[code] != data:
                        branch = branches.filtered(lambda b: b.code == code)
                        branch._update_branch(api_data[code])

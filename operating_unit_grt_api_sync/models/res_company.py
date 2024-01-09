from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = "res.company"

    grt_code_prefixes = fields.Char(
        string="GRT Code Prefixes",
        help="Enter GRT code prefixes related to this company, separated by comma.",
    )

    @api.constrains("grt_code_prefixes")
    def _check_code_prefix_unique(self):
        """Check if grt code prefix is unique across companies."""
        ou_code_company_mapping = self.env[
            "operating.unit"
        ]._get_ou_code_company_mapping()
        for rec in self:
            prefixes = (
                rec.grt_code_prefixes.replace(" ", "").split(",")
                if rec.grt_code_prefixes
                else []
            )
            for prefix in prefixes:
                company_id = ou_code_company_mapping.get(prefix)
                if company_id and company_id != rec.id:
                    raise ValidationError(
                        _(
                            f"GRT code prefix = [{prefix}] already exists in company ID = [{company_id}]"
                        )
                    )

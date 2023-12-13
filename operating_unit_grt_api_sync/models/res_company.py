from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    grt_code_prefix = fields.Char(string="GRT Code Prefix")

    _sql_constraints = [
        (
            "grt_code_prefix_uniq",
            "unique (grt_code_prefix)",
            "GRT code prefix must be unique.",
        )
    ]

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    grt_code_prefixes = fields.Char(
        string="GRT Code Prefixes",
        help="Enter GRT code prefixes related to this company, separated by comma.",
    )

    _sql_constraints = [
        (
            "grt_code_prefixes_uniq",
            "unique (grt_code_prefixes)",
            "GRT code prefixes must be unique.",
        )
    ]

# Copyright (C) 2018 by Camptocamp
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from odoo import fields, models


class MisBudgetItem(models.Model):
    _inherit = "mis.budget.item"

    operating_unit_id = fields.Many2one(
        comodel_name="operating.unit", string="Operating Unit",
    )

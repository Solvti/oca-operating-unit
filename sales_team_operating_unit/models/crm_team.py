# Copyright 2016-17 ForgeFlow S.L. (http://www.forgeflow.com)
# Copyright 2017-TODAY Serpent Consulting Services Pvt. Ltd.
#   (<http://www.serpentcs.com>)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CrmTeam(models.Model):

    _inherit = "crm.team"

    operating_unit_id = fields.Many2one(
        "operating.unit",
        default=lambda self: self.env["res.users"].operating_unit_default_get(),
        string="Management ID",
    )

    @api.constrains("operating_unit_id", "company_id")
    def _check_company_operating_unit(self):
        for team in self:
            if (
                team.company_id
                and team.operating_unit_id
                and team.company_id != team.operating_unit_id.company_id
            ):
                raise UserError(
                    _(
                        "Configuration error, "
                        "The Company in the Sales Team and in the "
                        "Management ID must be the same."
                    )
                )

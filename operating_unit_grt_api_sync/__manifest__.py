{
    "name": "Operating Unit GRT API Sync",
    "summary": "Sync operating unit data from GRT API.",
    "version": "13.0.1.0.0",
    "category": "Generic",
    "author": "Solvti Sp. z o.o. (Ltd), Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/operating-unit",
    "license": "LGPL-3",
    "depends": ["operating_unit", "operating_unit_validity_date"],
    "data": [
        "data/ir_config_parameter.xml",
        "data/ir_cron.xml",
        "views/res_company_views.xml",
        "views/operating_unit_views.xml",
    ],
    "demo": ["demo/res_company_demo.xml"],
}

# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
# Copyright 2020 Tecnativa - Pedro M. Baeza

from datetime import datetime, timedelta

from odoo import api, fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    type_id = fields.Many2one(
        comodel_name="sale.order.type",
        string="Type",
        compute="_compute_sale_type_id",
        store=True,
        readonly=False,
        states={
            "sale": [("readonly", True)],
            "done": [("readonly", True)],
            "cancel": [("readonly", True)],
        },
        default=lambda so: so._default_type_id(),
        ondelete="restrict",
        copy=True,
        check_company=True,
    )

    @api.model
    def _default_type_id(self):
        company_id = self.env.context.get("force_company", self.env.company.id)
        return self.env["sale.order.type"].search(
            [("company_id", "in", [company_id, False])], limit=1
        )

    @api.depends("partner_id", "company_id")
    def _compute_sale_type_id(self):
        for record in self:
            if not record.partner_id:
                record.type_id = self.env["sale.order.type"].search(
                    [("company_id", "in", [record.company_id.id, False])], limit=1
                )
            else:
                sale_type = (
                    record.partner_id.with_context(
                        force_company=record.company_id.id
                    ).sale_type
                    or record.partner_id.commercial_partner_id.with_context(
                        force_company=record.company_id.id
                    ).sale_type
                )
                if sale_type:
                    record.type_id = sale_type
                else:  # HACK: Avoid CacheMiss when no sale_type is set
                    record.type_id = record.type_id

    @api.onchange("type_id")
    def onchange_type_id(self):
        # TODO: To be changed to computed stored readonly=False if possible in v14?
        vals = {}
        for order in self:
            order_type = order.type_id
            # Order values
            vals = {}
            if order_type.warehouse_id:
                vals.update({"warehouse_id": order_type.warehouse_id})
            if order_type.picking_policy:
                vals.update({"picking_policy": order_type.picking_policy})
            if order_type.payment_term_id:
                vals.update({"payment_term_id": order_type.payment_term_id})
            if order_type.pricelist_id:
                vals.update({"pricelist_id": order_type.pricelist_id})
            if order_type.incoterm_id:
                vals.update({"incoterm": order_type.incoterm_id})
            if order_type.analytic_account_id:
                vals.update({"analytic_account_id": order_type.analytic_account_id})
            if order_type.quotation_validity_days:
                vals.update(
                    {
                        "validity_date": fields.Date.to_string(
                            datetime.now()
                            + timedelta(order_type.quotation_validity_days)
                        )
                    }
                )
            if vals:
                order.update(vals)
            # Order line values
            line_vals = {}
            line_vals.update({"route_id": order_type.route_id.id})
            order.order_line.update(line_vals)

    @api.model
    def create(self, vals):
        if vals.get("name", "/") == "/" and vals.get("type_id"):
            sale_type = self.env["sale.order.type"].browse(vals["type_id"])
            if sale_type.sequence_id:
                vals["name"] = sale_type.sequence_id.next_by_id()
        return super(SaleOrder, self).create(vals)

    def write(self, vals):
        """A sale type could have a different order sequence, so we could
        need to change it accordingly"""
        if vals.get("type_id"):
            sale_type = self.env["sale.order.type"].browse(vals["type_id"])
            if sale_type.sequence_id:
                for record in self:
                    if (
                        record.state in {"draft", "sent"}
                        and record.type_id.sequence_id != sale_type.sequence_id
                    ):
                        new_vals = vals.copy()
                        new_vals["name"] = sale_type.sequence_id.next_by_id()
                        super(SaleOrder, record).write(new_vals)
                    else:
                        super(SaleOrder, record).write(vals)
                return True
        return super().write(vals)

    def _prepare_invoice(self):
        res = super(SaleOrder, self)._prepare_invoice()
        if self.type_id.journal_id:
            res["journal_id"] = self.type_id.journal_id.id
        if self.type_id:
            res["sale_type_id"] = self.type_id.id
        return res


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    @api.onchange("product_id")
    def product_id_change(self):
        res = super(SaleOrderLine, self).product_id_change()
        if self.order_id.type_id.route_id:
            self.update({"route_id": self.order_id.type_id.route_id})
        return res

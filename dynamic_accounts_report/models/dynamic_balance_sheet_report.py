# -*- coding: utf-8 -*-
################################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2023-TODAY Cybrosys Technologies(<https://www.cybrosys.com>).
#    Author: Ammu Raj (odoo@cybrosys.com)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
################################################################################
import io
import json
import datetime
import xlsxwriter
import logging
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools.date_utils import get_month, get_fiscal_year, get_quarter, \
    subtract

_logger = logging.getLogger(__name__)

class ProfitLossReport(models.TransientModel):
    """For creating Profit and Loss and Balance sheet report."""
    _name = 'dynamic.balance.sheet.report'
    _description = 'Profit Loss Report'

    company_id = fields.Many2one('res.company', required=True,
                                 default=lambda self: self.env.company,
                                 help='Select the company to which this' \
                                      'record belongs.')
    journal_ids = fields.Many2many('account.journal',
                                   string='Journals', required=True,
                                   default=[],
                                   help='Select one or more journals.')
    account_ids = fields.Many2many("account.account", string="Accounts",
                                   help='Select one or more accounts.')
    analytic_ids = fields.Many2many(
        "account.analytic.account", string="Analytic Accounts",
        help="Analytic accounts associated with the current record.")
    target_move = fields.Selection([('posted', 'Posted'), ('draft', 'Draft')],
                                   string='Target Move', required=True,
                                   default='posted',
                                   help='Select the target move status.')
    date_from = fields.Date(string="Start date",
                            help="Specify the start date.")
    date_to = fields.Date(string="End date", help="Specify the end date.")

    @api.model_create_multi
    def create(self, vals):
        """Create one or more records of ProfitLossReport.
        :param vals: A dictionary or a list of dictionaries containing the field values for the records to be created.
        :return: A recordset of the created ProfitLossReport records."""
        return super(ProfitLossReport, self).create({})

    @api.model
    def view_report(self, option, comparison, comparison_type):
        datas = []
        account_types = {
            'income': 'income',
            'income_other': 'income_other',
            'expense': 'expense',
            'expense_depreciation': 'expense_depreciation',
            'expense_direct_cost': 'expense_direct_cost',
            'asset_receivable': 'asset_receivable',
            'asset_cash': 'asset_cash',
            'asset_current': 'asset_current',
            'asset_non_current': 'asset_non_current',
            'asset_prepayments': 'asset_prepayments',
            'asset_fixed': 'asset_fixed',
            'liability_payable': 'liability_payable',
            'liability_credit_card': 'liability_credit_card',
            'liability_current': 'liability_current',
            'liability_non_current': 'liability_non_current',
            'equity': 'equity',
            'equity_unaffected': 'equity_unaffected',
        }
        financial_report_id = self.browse(option)
        current_year = fields.Date.today().year
        current_date = fields.Date.today()
        if financial_report_id.target_move == 'draft':
            target_move = ['posted', 'draft']
        else:
            target_move = ['posted']

        # Base domain for account move lines
        domain = [('parent_state', 'in', target_move)]

        # Add date filter to domain
        if financial_report_id.date_from:
            domain.append(('date', '>=', financial_report_id.date_from))
        if financial_report_id.date_to:
            domain.append(('date', '<=', financial_report_id.date_to))

        # Add journal and account filters to the domain if selected
        if financial_report_id.journal_ids:
            domain.append(('journal_id', 'in', financial_report_id.journal_ids.ids))
        if financial_report_id.account_ids:
            domain.append(('account_id', 'in', financial_report_id.account_ids.ids))

        # Add analytic account filter to the domain if selected
        if financial_report_id.analytic_ids:
            # Prepare analytic IDs as strings for JSONB key check
            analytic_ids_str = [str(aid) for aid in financial_report_id.analytic_ids.ids]
            domain.append(('analytic_distribution', 'in', analytic_ids_str))

        if comparison:
            for count in range(0, int(comparison) + 1):
                if comparison_type == "month":
                    comparison_domain = domain + [
                        ('date', '>=', (current_date - datetime.timedelta(days=30 * count)).strftime('%Y-%m-01')),
                        ('date', '<=', (current_date - datetime.timedelta(days=30 * count)).strftime('%Y-%m-12'))
                    ]
                elif comparison_type == "year":
                    comparison_domain = domain + [
                        ('date', '>=', f'{current_year - count}-01-01'),
                        ('date', '<=', f'{current_year - count}-12-31')
                    ]

                account_move_lines = self.env['account.move.line'].search(comparison_domain)
                selected_analytic_ids = financial_report_id.analytic_ids.ids

                # Process the filtered lines
                account_entries = {}
                for account_type in account_types.values():
                    entries, raw_total = self._get_entries(
                        account_move_lines, self.env['account.account'].search(
                            [('account_type', '=', account_type)]), account_type, selected_analytic_ids, financial_report_id.date_from, financial_report_id.date_to)
                    account_entries[account_type] = (entries, raw_total)

                # Calculate totals using raw numeric values
                total_income = sum(
                    account_entries[account_type][1] for account_type in
                    ['income', 'income_other'])
                total_direct_cost = sum(
                    account_entries[account_type][1] for account_type in
                    ['expense_direct_cost']
                )
                total_expense_sum = sum(
                    account_entries[account_type][1] for account_type in
                    ['expense', 'expense_depreciation'])
                
                # Calculate gross profit (Income - Direct Cost)
                gross_profit = total_income - total_direct_cost
                
                # Calculate net profit/loss (Gross Profit - Expenses)
                net_profit_loss = gross_profit - total_expense_sum

                # Calculate balance sheet totals
                total_current_asset = sum(
                    account_entries[account_type][1] for account_type in
                    ['asset_receivable', 'asset_current', 'asset_cash',
                     'asset_prepayments'])
                total_assets = total_current_asset + sum(
                    account_entries[account_type][1] for account_type in
                    ['asset_fixed', 'asset_non_current'])
                total_current_liability = sum(
                    account_entries[account_type][1] for account_type in
                    ['liability_current', 'liability_payable'])
                total_liability = total_current_liability + sum(
                    account_entries[account_type][1] for account_type in
                    ['liability_non_current'])
                
                # Calculate equity
                total_unallocated_earning = net_profit_loss + sum(
                    account_entries[account_type][1] for account_type in
                    ['equity_unaffected'])
                total_equity = total_unallocated_earning + sum(
                    account_entries[account_type][1] for account_type in
                    ['equity'])
                
                # Calculate total balance (Liabilities + Equity)
                total_balance = total_liability + total_equity

                data_for_period = {
                    'total': net_profit_loss,  # Net Profit/Loss
                    'total_expense': "{:,.2f}".format(abs(total_expense_sum)),  # Display expenses as positive
                    'total_income': "{:,.2f}".format(total_income),
                    'total_direct_cost': "{:,.2f}".format(total_direct_cost),
                    'gross_profit': "{:,.2f}".format(gross_profit),
                    'total_current_asset': "{:,.2f}".format(total_current_asset),
                    'total_assets': "{:,.2f}".format(total_assets),
                    'total_current_liability': "{:,.2f}".format(total_current_liability),
                    'total_liability': "{:,.2f}".format(total_liability),
                    'total_earnings': net_profit_loss,
                    'total_unallocated_earning': "{:,.2f}".format(total_unallocated_earning),
                    'total_equity': "{:,.2f}".format(total_equity),
                    'total_balance': "{:,.2f}".format(total_balance),
                    **{k: (v[0], "{:,.2f}".format(v[1])) for k, v in account_entries.items()}
                }
                datas.append(data_for_period)
        else:
            # Use the base domain for non-comparison case
            account_move_lines = self.env['account.move.line'].search(domain)
            selected_analytic_ids = financial_report_id.analytic_ids.ids

            # Process the filtered lines
            account_entries = {}
            for account_type in account_types.values():
                entries, raw_total = self._get_entries(
                    account_move_lines, self.env['account.account'].search(
                        [('account_type', '=', account_type)]), account_type, selected_analytic_ids, financial_report_id.date_from, financial_report_id.date_to)
                account_entries[account_type] = (entries, raw_total)

            # Calculate totals using raw numeric values
            total_income = sum(
                account_entries[account_type][1] for account_type in
                ['income', 'income_other'])
            total_direct_cost = sum(
                account_entries[account_type][1] for account_type in
                ['expense_direct_cost']
            )
            total_expense_sum = sum(
                account_entries[account_type][1] for account_type in
                ['expense', 'expense_depreciation'])
            
            # Calculate gross profit (Income - Direct Cost)
            gross_profit = total_income - total_direct_cost
            
            # Calculate net profit/loss (Gross Profit - Expenses)
            net_profit_loss = gross_profit - total_expense_sum

            # Calculate balance sheet totals
            total_current_asset = sum(
                account_entries[account_type][1] for account_type in
                ['asset_receivable', 'asset_current', 'asset_cash',
                 'asset_prepayments'])
            total_assets = total_current_asset + sum(
                account_entries[account_type][1] for account_type in
                ['asset_fixed', 'asset_non_current'])
            total_current_liability = sum(
                account_entries[account_type][1] for account_type in
                ['liability_current', 'liability_payable'])
            total_liability = total_current_liability + sum(
                account_entries[account_type][1] for account_type in
                ['liability_non_current'])
            
            # Calculate equity
            total_unallocated_earning = net_profit_loss + sum(
                account_entries[account_type][1] for account_type in
                ['equity_unaffected'])
            total_equity = total_unallocated_earning + sum(
                account_entries[account_type][1] for account_type in
                ['equity'])
            
            # Calculate total balance (Liabilities + Equity)
            total_balance = total_liability + total_equity

            data_for_period = {
                'total': net_profit_loss,  # Net Profit/Loss
                'total_expense': "{:,.2f}".format(abs(total_expense_sum)),  # Display expenses as positive
                'total_income': "{:,.2f}".format(total_income),
                'total_direct_cost': "{:,.2f}".format(total_direct_cost),
                'gross_profit': "{:,.2f}".format(gross_profit),
                'total_current_asset': "{:,.2f}".format(total_current_asset),
                'total_assets': "{:,.2f}".format(total_assets),
                'total_current_liability': "{:,.2f}".format(total_current_liability),
                'total_liability': "{:,.2f}".format(total_liability),
                'total_earnings': net_profit_loss,
                'total_unallocated_earning': "{:,.2f}".format(total_unallocated_earning),
                'total_equity': "{:,.2f}".format(total_equity),
                'total_balance': "{:,.2f}".format(total_balance),
                **{k: (v[0], "{:,.2f}".format(v[1])) for k, v in account_entries.items()}
            }
            datas.append(data_for_period)

        # Prepare the final return structure for JavaScript
        report_data_for_current_period = datas[0] if datas else {}
        filter_data = self._get_filter_data()

        return [report_data_for_current_period, filter_data, datas]

    def _get_entries(self, account_move_lines, account_ids, account_type, selected_analytic_ids_from_report=None, date_from=None, date_to=None):
        """
        Get the entries for the specified account type.
        :param account_move_lines: The account move lines to filter.
        :param account_ids: The account IDs to filter.
        :param account_type: The account type.
        :param selected_analytic_ids_from_report: List of analytic account IDs selected in the report filter.
        :return: A tuple containing the entries and the total amount.
        """
        entries = []
        total = 0
        
        for account in account_ids:
            filtered_lines = account_move_lines.filtered(lambda line: line.account_id == account)
            if filtered_lines:
                amount = 0
                for line in filtered_lines:
                    line_amount = 0  # Initialize line_amount for each line
                    
                    # Calculate the base amount for the line based on account type
                    if account_type in ['income', 'income_other']:
                        # For income accounts, credit increases and debit decreases
                        line_amount = line.credit - line.debit
                    elif account_type in ['expense', 'expense_depreciation', 'expense_direct_cost']:
                        # For expense accounts, debit increases and credit decreases
                        line_amount = line.debit - line.credit
                    elif account_type in ['asset_receivable', 'asset_cash', 'asset_current', 'asset_non_current', 'asset_prepayments', 'asset_fixed']:
                        # For asset accounts, debit increases and credit decreases
                        line_amount = line.debit - line.credit
                    elif account_type in ['liability_payable', 'liability_credit_card', 'liability_current', 'liability_non_current']:
                        # For liability accounts, credit increases and debit decreases
                        line_amount = line.credit - line.debit
                    elif account_type in ['equity', 'equity_unaffected']:
                        # For equity accounts, credit increases and debit decreases
                        line_amount = line.credit - line.debit
                    else:
                        line_amount = line.debit - line.credit

                    if selected_analytic_ids_from_report:
                        line_analytic_total = 0
                        # First, try to get amount from analytic_distribution
                        if line.analytic_distribution:
                            temp_line_analytic_total = 0
                            for analytic_id_str, percentage in line.analytic_distribution.items():
                                try:
                                    analytic_id_int = int(analytic_id_str)
                                    if analytic_id_int in selected_analytic_ids_from_report:
                                        # Calculate the analytic amount based on the percentage
                                        calc_analytic_amount = line_amount * (percentage / 100)
                                        temp_line_analytic_total += calc_analytic_amount
                                except ValueError:
                                    continue
                            line_analytic_total = temp_line_analytic_total
                        
                        # If we have analytic distribution and it matches our selected analytics
                        if line_analytic_total != 0:
                            amount += line_analytic_total
                        # If no analytic distribution or no matching analytics, use full amount
                        else:
                            amount += line_amount
                    else:
                        # If no analytic accounts selected, use full line amount
                        amount += line_amount

                # Format the display amount based on account type
                display_amount = amount
                if account_type in ['expense', 'expense_depreciation', 'expense_direct_cost']:
                    display_amount = -abs(amount)  # Ensure expenses are displayed as negative

                entries.append({
                    'name': "{} - {}".format(account.code, account.name),
                    'amount': "{:,.2f}".format(display_amount),
                })
                total += amount
            else:
                entries.append({
                    'name': "{} - {}".format(account.code, account.name),
                    'amount': "{:,.2f}".format(0),
                })
        
        return entries, total

    def filter(self, vals):
        """
            Update the filter criteria based on the provided values.
            :param vals: A dictionary containing the filter values to update.
            :return: The updated record.
            """
        filter = []
        today = fields.Date.today()
        if vals == 'month':
            vals = {
                'date_from': get_month(today)[0].strftime("%Y-%m-%d"),
                'date_to': get_month(today)[1].strftime("%Y-%m-%d"),
            }
        elif vals == 'quarter':
            vals = {
                'date_from': get_quarter(today)[0].strftime("%Y-%m-%d"),
                'date_to': get_quarter(today)[1].strftime("%Y-%m-%d"),
            }
        elif vals == 'year':
            vals = {
                'date_from': get_fiscal_year(today)[0].strftime("%Y-%m-%d"),
                'date_to': get_fiscal_year(today)[1].strftime("%Y-%m-%d"),
            }
        elif vals == 'last-month':
            last_month_date = subtract(today, months=1)
            vals = {
                'date_from': get_month(last_month_date)[0].strftime(
                    "%Y-%m-%d"),
                'date_to': get_month(last_month_date)[1].strftime("%Y-%m-%d"),
            }
        elif vals == 'last-quarter':
            last_quarter_date = subtract(today, months=3)
            vals = {
                'date_from': get_quarter(last_quarter_date)[0].strftime(
                    "%Y-%m-%d"),
                'date_to': get_quarter(last_quarter_date)[1].strftime(
                    "%Y-%m-%d"),
            }
        elif vals == 'last-year':
            last_year_date = subtract(today, years=1)
            vals = {
                'date_from': get_fiscal_year(last_year_date)[0].strftime(
                    "%Y-%m-%d"),
                'date_to': get_fiscal_year(last_year_date)[1].strftime(
                    "%Y-%m-%d"),
            }
        if 'date_from' in vals:
            self.write({'date_from': vals['date_from']})
        if 'date_to' in vals:
            self.write({'date_to': vals['date_to']})
        if 'journal_ids' in vals:
            if int(vals['journal_ids']) in self.journal_ids.mapped('id'):
                self.update({'journal_ids': [(3, int(vals['journal_ids']))]})
            else:
                self.write({'journal_ids': [(4, int(vals['journal_ids']))]})
            filter.append({'journal_ids': self.journal_ids.mapped('code')})
        if 'account_ids' in vals:
            if int(vals['account_ids']) in self.account_ids.mapped('id'):
                self.update(
                    {'account_ids': [(3, int(vals['account_ids']))]})
            else:
                self.write({'account_ids': [(4, int(vals['account_ids']))]})
            filter.append({'account_ids': self.account_ids.mapped('name')})
        if 'analytic_ids' in vals:
            if int(vals['analytic_ids']) in self.analytic_ids.mapped('id'):
                self.update(
                    {'analytic_ids': [(3, int(vals['analytic_ids']))]})
            else:
                self.write({'analytic_ids': [(4, int(vals['analytic_ids']))]})
            filter.append({'analytic_ids': self.analytic_ids.mapped('name')})
        if 'target' in vals:
            self.write({'target_move': vals['target']})
            filter.append({'target_move': self.target_move})
        return filter

    def _get_filter_data(self):
        """
            Retrieve the filter data for journals and accounts.

            :return: A dictionary containing the filter data.
            """
        journal_ids = self.env['account.journal'].search([])
        journal = [{'id': journal.id, 'name': journal.name} for journal in
                   journal_ids]

        account_ids = self.env['account.account'].search([])
        account = [{'id': account.id, 'name': account.name} for account in
                   account_ids]

        analytic_ids = self.env['account.analytic.account'].search([])
        analytic = [{'id': analytic.id, 'name': analytic.name} for analytic in
                    analytic_ids]

        filter = {
            'journal': journal,
            'account': account,
            'analytic': analytic
        }
        return filter

    @api.model
    def comparison_filter(self, options, count):
        today = fields.Date.today()
        if not count:
            raise ValidationError(_("Please select the count."))
        last_month_date_list = []
        for i in range(1, int(count) + 1):
            last_month_date = subtract(today, months=i)
            vals = {
                'date_from': get_month(last_month_date)[0].strftime(
                    "%Y-%m-%d"),
                'date_to': get_month(last_month_date)[1].strftime("%Y-%m-%d"),
            }
            last_month_date_list.append(vals)
        return last_month_date_list

    @api.model
    def comparison_filter_year(self, options, count):
        today = fields.Date.today()
        if not count:
            raise ValidationError(_("Please select the count."))
        last_year_date_list = []
        for i in range(1, int(count) + 1):
            last_year_date = subtract(today, years=i)
            vals = {
                'date_from': get_fiscal_year(last_year_date)[0].strftime(
                    "%Y-%m-%d"),
                'date_to': get_fiscal_year(last_year_date)[1].strftime(
                    "%Y-%m-%d"),
            }
            last_year_date_list.append(vals)
        return last_year_date_list

    @api.model
    def get_xlsx_report(self, data, response, report_name):
        """Generate and return an XLSX report based on the provided data.
            :param data: The report data in JSON format.
            :param report_name: Name of the report.
            :param response: The response object to write the generated report to.
            """
        data = json.loads(data)
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet()
        head = workbook.add_format({'align': 'center', 'bold': True,
                                    'font_size': '20px'})
        sub_heading = workbook.add_format(
            {'align': 'center', 'bold': True, 'font_size': '10px',
             'border': 1})
        col_head = workbook.add_format({'align': 'center', 'bold': True,
                                        'font_size': '10px', 'border': 1})
        content = workbook.add_format({'align': 'center', 'font_size': '10px',
                                       'border': 1})
        if data.get('report_info') and data.get('report_info')[0].get(
                'report_name') == 'Profit and Loss':
            sheet.merge_range('A1:H2', 'Profit and Loss Report', head)
            sheet.merge_range('A3:H3', 'Financial Report', sub_heading)
            date_from = data.get('report_info')[0].get('date_from')
            date_to = data.get('report_info')[0].get('date_to')
            if data.get('report_info')[0].get('analytic_ids'):
                sheet.merge_range(
                    'A4:H4', f"Analytic Accounts: {', '.join([self.env['account.analytic.account'].browse(aid).name for aid in data.get('report_info')[0].get('analytic_ids')])}", sub_heading)
            else:
                sheet.merge_range('A4:H4', 'All Analytic Accounts', sub_heading)
            sheet.merge_range('A5:H5', f"Date: {date_from or 'All'} to {date_to or 'All'}", sub_heading)

            # Define columns based on 'comparison'
            columns = ['Account Code', 'Account Name', 'Total']
            if data.get('report_info')[0].get('comparison'):
                for i in range(int(data.get('report_info')[0].get('comparison')) + 1):
                    if data.get('report_info')[0].get('comparison_type') == "month":
                        columns.append(f'Month {i+1} Total')
                    elif data.get('report_info')[0].get('comparison_type') == "year":
                        columns.append(f'Year {i+1} Total')
            else:
                columns.append('Current Period Total')

            sheet.write_row('A6', columns, col_head)

            row = 6
            # Income section
            sheet.write(row, 0, 'Income', col_head)
            sheet.merge_range(row, 0, row, len(columns) - 1, 'Income', col_head)
            row += 1
            for entry_type in ['income', 'income_other']:
                for entry in data.get(entry_type)[0]:
                    sheet.write(row, 0, entry['name'].split(' - ')[0] if ' - ' in entry['name'] else '', content)
                    sheet.write(row, 1, entry['name'].split(' - ')[1] if ' - ' in entry['name'] else entry['name'], content)
                    col_idx = 2
                    for dt in data.get('report_info'):
                        if dt.get(entry_type):
                            total_value = dt.get(entry_type)[0][
                                data.get(entry_type)[0].index(entry)]['amount']
                            sheet.write(row, col_idx, total_value, content)
                            col_idx += 1
                row += 1
                sheet.write(row, 0, '', col_head)
                sheet.write(row, 1, 'Total Income', col_head)
                col_idx = 2
                for dt in data.get('report_info'):
                    total_income_value = dt.get('total_income')
                    sheet.write(row, col_idx, total_income_value, col_head)
                    col_idx += 1
                row += 1

            # Direct Cost section
            sheet.write(row, 0, 'Direct Cost', col_head)
            sheet.merge_range(row, 0, row, len(columns) - 1, 'Direct Cost', col_head)
            row += 1
            for entry_type in ['expense_direct_cost']:
                for entry in data.get(entry_type)[0]:
                    sheet.write(row, 0, entry['name'].split(' - ')[0] if ' - ' in entry['name'] else '', content)
                    sheet.write(row, 1, entry['name'].split(' - ')[1] if ' - ' in entry['name'] else entry['name'], content)
                    col_idx = 2
                    for dt in data.get('report_info'):
                        if dt.get(entry_type):
                            total_value = dt.get(entry_type)[0][
                                data.get(entry_type)[0].index(entry)]['amount']
                            sheet.write(row, col_idx, total_value, content)
                            col_idx += 1
                row += 1
                sheet.write(row, 0, '', col_head)
                sheet.write(row, 1, 'Total Direct Cost', col_head)
                col_idx = 2
                for dt in data.get('report_info'):
                    total_direct_cost_value = dt.get('total_direct_cost')
                    sheet.write(row, col_idx, total_direct_cost_value, col_head)
                    col_idx += 1
                row += 1
            
            # Gross Profit section (Income - Direct Cost)
            sheet.write(row, 0, '', col_head)
            sheet.write(row, 1, 'Gross Profit', col_head)
            col_idx = 2
            for dt in data.get('report_info'):
                total_income_net_direct_cost_value = dt.get('total_income_net_direct_cost')
                sheet.write(row, col_idx, "{:,.2f}".format(total_income_net_direct_cost_value), col_head) # Format Gross Profit
                col_idx += 1
            row += 1

            # Expenses section
            sheet.write(row, 0, 'Expenses', col_head)
            sheet.merge_range(row, 0, row, len(columns) - 1, 'Expenses', col_head)
            row += 1
            for entry_type in ['expense', 'expense_depreciation']:
                for entry in data.get(entry_type)[0]:
                    sheet.write(row, 0, entry['name'].split(' - ')[0] if ' - ' in entry['name'] else '', content)
                    sheet.write(row, 1, entry['name'].split(' - ')[1] if ' - ' in entry['name'] else entry['name'], content)
                    col_idx = 2
                    for dt in data.get('report_info'):
                        if dt.get(entry_type):
                            total_value = dt.get(entry_type)[0][
                                data.get(entry_type)[0].index(entry)]['amount']
                            sheet.write(row, col_idx, total_value, content)
                            col_idx += 1
                row += 1
                sheet.write(row, 0, '', col_head)
                sheet.write(row, 1, 'Total Expenses', col_head)
                col_idx = 2
                for dt in data.get('report_info'):
                    total_expense_value = dt.get('total_expense')
                    sheet.write(row, col_idx, total_expense_value, col_head)
                    col_idx += 1
                row += 1

            # Net Profit/Loss
            sheet.write(row, 0, '', col_head)
            sheet.write(row, 1, 'Net Profit/Loss', col_head)
            col_idx = 2
            for dt in data.get('report_info'):
                net_profit_loss_value = dt.get('total')
                sheet.write(row, col_idx, net_profit_loss_value, col_head)
                col_idx += 1
            row += 1

        elif data.get('report_info') and data.get('report_info')[0].get(
                'report_name') == 'Balance Sheet':
            sheet.merge_range('A1:H2', 'Balance Sheet Report', head)
            sheet.merge_range('A3:H3', 'Financial Report', sub_heading)
            date_from = data.get('report_info')[0].get('date_from')
            date_to = data.get('report_info')[0].get('date_to')
            if data.get('report_info')[0].get('analytic_ids'):
                sheet.merge_range(
                    'A4:H4', f"Analytic Accounts: {', '.join([self.env['account.analytic.account'].browse(aid).name for aid in data.get('report_info')[0].get('analytic_ids')])}", sub_heading)
            else:
                sheet.merge_range('A4:H4', 'All Analytic Accounts', sub_heading)
            sheet.merge_range('A5:H5', f"Date: {date_from or 'All'} to {date_to or 'All'}", sub_heading)

            columns = ['Account Code', 'Account Name', 'Total']
            if data.get('report_info')[0].get('comparison'):
                for i in range(int(data.get('report_info')[0].get('comparison')) + 1):
                    if data.get('report_info')[0].get('comparison_type') == "month":
                        columns.append(f'Month {i+1} Total')
                    elif data.get('report_info')[0].get('comparison_type') == "year":
                        columns.append(f'Year {i+1} Total')
            else:
                columns.append('Current Period Total')

            sheet.write_row('A6', columns, col_head)

            row = 6
            # Assets section
            sheet.write(row, 0, 'Assets', col_head)
            sheet.merge_range(row, 0, row, len(columns) - 1, 'Assets', col_head)
            row += 1
            for entry_type in ['asset_receivable', 'asset_cash', 'asset_current', 'asset_prepayments', 'asset_fixed', 'asset_non_current']:
                for entry in data.get(entry_type)[0]:
                    sheet.write(row, 0, entry['name'].split(' - ')[0] if ' - ' in entry['name'] else '', content)
                    sheet.write(row, 1, entry['name'].split(' - ')[1] if ' - ' in entry['name'] else entry['name'], content)
                    col_idx = 2
                    for dt in data.get('report_info'):
                        if dt.get(entry_type):
                            total_value = dt.get(entry_type)[0][
                                data.get(entry_type)[0].index(entry)]['amount']
                            sheet.write(row, col_idx, total_value, content)
                            col_idx += 1
                row += 1
                sheet.write(row, 0, '', col_head)
                sheet.write(row, 1, f"Total {entry_type.replace('_', ' ').title()}", col_head)
                col_idx = 2
                for dt in data.get('report_info'):
                    total_asset_value = dt.get(f'total_{entry_type}')
                    sheet.write(row, col_idx, total_asset_value, col_head)
                    col_idx += 1
                row += 1

            sheet.write(row, 0, '', col_head)
            sheet.write(row, 1, 'Total Assets', col_head)
            col_idx = 2
            for dt in data.get('report_info'):
                total_assets_value = dt.get('total_assets')
                sheet.write(row, col_idx, total_assets_value, col_head)
                col_idx += 1
            row += 1

            # Liabilities section
            sheet.write(row, 0, 'Liabilities', col_head)
            sheet.merge_range(row, 0, row, len(columns) - 1, 'Liabilities', col_head)
            row += 1
            for entry_type in ['liability_payable', 'liability_credit_card', 'liability_current', 'liability_non_current']:
                for entry in data.get(entry_type)[0]:
                    sheet.write(row, 0, entry['name'].split(' - ')[0] if ' - ' in entry['name'] else '', content)
                    sheet.write(row, 1, entry['name'].split(' - ')[1] if ' - ' in entry['name'] else entry['name'], content)
                    col_idx = 2
                    for dt in data.get('report_info'):
                        if dt.get(entry_type):
                            total_value = dt.get(entry_type)[0][
                                data.get(entry_type)[0].index(entry)]['amount']
                            sheet.write(row, col_idx, total_value, content)
                            col_idx += 1
                row += 1
                sheet.write(row, 0, '', col_head)
                sheet.write(row, 1, f"Total {entry_type.replace('_', ' ').title()}", col_head)
                col_idx = 2
                for dt in data.get('report_info'):
                    total_liability_value = dt.get(f'total_{entry_type}')
                    sheet.write(row, col_idx, total_liability_value, col_head)
                    col_idx += 1
                row += 1

            sheet.write(row, 0, '', col_head)
            sheet.write(row, 1, 'Total Liabilities', col_head)
            col_idx = 2
            for dt in data.get('report_info'):
                total_liability_value = dt.get('total_liability')
                sheet.write(row, col_idx, total_liability_value, col_head)
                col_idx += 1
            row += 1

            # Equity section
            sheet.write(row, 0, 'Equity', col_head)
            sheet.merge_range(row, 0, row, len(columns) - 1, 'Equity', col_head)
            row += 1
            for entry_type in ['equity', 'equity_unaffected']:
                for entry in data.get(entry_type)[0]:
                    sheet.write(row, 0, entry['name'].split(' - ')[0] if ' - ' in entry['name'] else '', content)
                    sheet.write(row, 1, entry['name'].split(' - ')[1] if ' - ' in entry['name'] else entry['name'], content)
                    col_idx = 2
                    for dt in data.get('report_info'):
                        if dt.get(entry_type):
                            total_value = dt.get(entry_type)[0][
                                data.get(entry_type)[0].index(entry)]['amount']
                            sheet.write(row, col_idx, total_value, content)
                            col_idx += 1
                row += 1
                sheet.write(row, 0, '', col_head)
                sheet.write(row, 1, f"Total {entry_type.replace('_', ' ').title()}", col_head)
                col_idx = 2
                for dt in data.get('report_info'):
                    total_equity_value = dt.get(f'total_{entry_type}')
                    sheet.write(row, col_idx, total_equity_value, col_head)
                    col_idx += 1
                row += 1

            # Total Liabilities and Equity
            sheet.write(row, 0, '', col_head)
            sheet.write(row, 1, 'Total Liabilities and Equity', col_head)
            col_idx = 2
            for dt in data.get('report_info'):
                total_balance_value = dt.get('total_balance')
                sheet.write(row, col_idx, total_balance_value, col_head)
                col_idx += 1
            row += 1

        workbook.close()
        response.headers['Content-Disposition'] = 'attachment; filename="%s.xlsx"' % report_name
        return output.getvalue()
